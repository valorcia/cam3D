"""Relay import: phone-encrypted scans downloaded and decrypted on the PC."""
import base64
import hashlib
import io
import json
import os
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cam3d.server.app import create_app
from cam3d.server.relay import RelayError, check_url, decrypt_object, encrypt_object, parse_code
from test_server import Settings, jpeg_bytes, wait_job

VECTOR = Path(__file__).resolve().parents[2] / "capture" / "src" / "lib" / "__fixtures__" / "vector.json"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def test_shared_vector_with_the_phone_app():
    v = json.loads(VECTOR.read_text(encoding="utf-8"))
    key, blob = bytes.fromhex(v["key_hex"]), bytes.fromhex(v["blob_hex"])
    assert decrypt_object(key, v["path"], blob).decode() == v["plain_utf8"]
    assert encrypt_object(key, v["path"], v["plain_utf8"].encode(), bytes.fromhex(v["iv_hex"])) == blob
    with pytest.raises(RelayError):
        decrypt_object(key, "autre.bin", blob)          # swapped file
    with pytest.raises(RelayError):
        decrypt_object(os.urandom(32), v["path"], blob)  # wrong key


def test_only_vercel_blob_hosts_are_fetched(monkeypatch):
    monkeypatch.delenv("CAM3D_RELAY_ALLOW", raising=False)
    assert check_url("https://abc123.public.blob.vercel-storage.com/scans/x/manifest.bin")
    for bad in ("http://abc123.public.blob.vercel-storage.com/x", "https://169.254.169.254/latest", "https://evil.example/x",
                "https://abc.public.blob.vercel-storage.com.evil.example/x", "http://127.0.0.1:8765/api/projects"):
        with pytest.raises(RelayError):
            check_url(bad)
    code = "c3d1:" + b64u(json.dumps({"m": "http://192.168.1.1/scans/a/manifest.bin", "k": b64u(os.urandom(32)), "n": "x"}).encode())
    with pytest.raises(RelayError):
        parse_code(code)


def _publish_scan(root: Path, key: bytes, photos: dict[str, bytes], scan_id: str = "a" * 32) -> str:
    d = root / "scans" / scan_id
    d.mkdir(parents=True)
    entries = []
    for i, (name, data) in enumerate(photos.items()):
        rel = f"{i:032x}.bin"
        (d / rel).write_bytes(encrypt_object(key, rel, data))
        entries.append({"path": rel, "name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "type": "image/jpeg"})
    manifest = {"v": 1, "name": "Vase bleu", "created": 1, "updated": 2, "photos": entries}
    (d / "manifest.bin").write_bytes(encrypt_object(key, "manifest.bin", json.dumps(manifest).encode()))
    return f"scans/{scan_id}"


@pytest.fixture
def relay_server(tmp_path, monkeypatch):
    root = tmp_path / "relay"
    root.mkdir()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
    srv.RequestHandlerClass.log_message = lambda *a: None
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("CAM3D_RELAY_ALLOW", origin)
    monkeypatch.setenv("NO_PROXY", "*")
    yield root, origin
    srv.shutdown()


def test_import_from_relay_creates_project_with_verified_photos(tmp_path, relay_server):
    root, origin = relay_server
    key = os.urandom(32)
    photos = {f"IMG_{i}.jpg": jpeg_bytes(200 + i) for i in range(5)}
    prefix = _publish_scan(root, key, photos)
    code = "c3d1:" + b64u(json.dumps({"m": f"{origin}/{prefix}/manifest.bin", "k": b64u(key), "n": "Vase bleu"}).encode())
    settings = Settings(data_dir=tmp_path / "data", trusted_hosts=frozenset({"127.0.0.1"}))
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as c:
        assert c.post("/api/relay/import", json={"code": "c3d1:nimportequoi"}).status_code == 400
        r = c.post("/api/relay/import", json={"code": f"https://capture.example/t/#{code}"})
        assert r.status_code == 202, r.text
        pid = r.json()["project"]["id"]
        assert r.json()["project"]["name"] == "Vase bleu"
        j = wait_job(c, r.json()["job"]["id"], timeout=60)
        assert j["status"] == "succeeded", j
        names = sorted(p["name"] for p in c.get(f"/api/projects/{pid}/photos").json())
        assert names == sorted(photos)
        orig = settings.projects_dir / pid / "originals"
        assert (orig / "IMG_0.jpg").read_bytes() == photos["IMG_0.jpg"]   # bit-exact after decryption
        assert not (settings.projects_dir / pid / "processed" / "relay_code.json").exists()  # key not kept

        # a tampered photo makes the import fail explicitly
        bad = root / prefix / f"{0:032x}.bin"
        data = bytearray(bad.read_bytes()); data[40] ^= 1; bad.write_bytes(bytes(data))
        r = c.post("/api/relay/import", json={"code": code})
        j = wait_job(c, r.json()["job"]["id"], timeout=60)
        assert j["status"] == "failed" and "altéré" in j["error"]
        # wrong key
        wrong = "c3d1:" + b64u(json.dumps({"m": f"{origin}/{prefix}/manifest.bin", "k": b64u(os.urandom(32)), "n": "x"}).encode())
        j = wait_job(c, c.post("/api/relay/import", json={"code": wrong}).json()["job"]["id"], timeout=60)
        assert j["status"] == "failed" and "déchiffrement" in j["error"]


def test_zip_import(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", trusted_hosts=frozenset({"127.0.0.1"}))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Scan/IMG_1.jpg", jpeg_bytes(1))
        z.writestr("../../evil.jpg", jpeg_bytes(2))
        z.writestr("notes.txt", "x")
        z.writestr("__MACOSX/._IMG_1.jpg", b"junk")
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as c:
        pid = c.post("/api/projects", json={"name": "Zip"}).json()["id"]
        r = c.post(f"/api/projects/{pid}/photos", files=[("files", ("scan.zip", buf.getvalue(), "application/zip"))])
        assert r.status_code == 200, r.text
        assert sorted(a["name"] for a in r.json()["added"]) == ["IMG_1.jpg", "evil.jpg"]
        assert not (settings.projects_dir.parent / "evil.jpg").exists()
        assert sorted(p.name for p in (settings.projects_dir / pid / "originals").iterdir()) == ["IMG_1.jpg", "evil.jpg"]
        bad = c.post(f"/api/projects/{pid}/photos", files=[("files", ("x.zip", b"not a zip", "application/zip"))])
        assert bad.status_code == 415
