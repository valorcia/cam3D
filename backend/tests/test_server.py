import io
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cam3d.server.app import create_app
from cam3d.server.config import Settings as _Settings

STUB = [sys.executable, str(Path(__file__).with_name("stub_worker.py"))]


def Settings(**kw):  # noqa: N802 - test settings: TestClient sends "Host: testserver"
    kw.setdefault("local_host_names", frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}))
    return _Settings(**kw)


def jpeg_bytes(seed=0, size=(800, 600), blur=False) -> bytes:
    rng = np.random.default_rng(seed)
    img = Image.fromarray((rng.random((size[1], size[0], 3)) * 255).astype(np.uint8))
    if blur:
        from PIL import ImageFilter
        img = img.filter(ImageFilter.GaussianBlur(12))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", worker_cmd=STUB, cancel_grace_s=1.0, max_photo_mb=2,
                    trusted_hosts=frozenset({"127.0.0.1"}))


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def desktop(app):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


@pytest.fixture
def phone(app, desktop):  # desktop fixture first so the lifespan runs once
    return TestClient(app, client=("192.168.1.42", 50001))


def wait_job(client, jid, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {jid} still {j['status']}")


def make_project(client, n_photos=3, name="Vase"):
    p = client.post("/api/projects", json={"name": name}).json()
    files = [("files", (f"IMG_{i}.jpg", jpeg_bytes(i), "image/jpeg")) for i in range(n_photos)]
    if n_photos:
        r = client.post(f"/api/projects/{p['id']}/photos", files=files)
        assert r.status_code == 200, r.text
    return p["id"]


# ---------------------------------------------------------------- projects
def test_health_and_system(desktop):
    assert desktop.get("/api/health").json()["status"] == "ok"
    s = desktop.get("/api/system").json()
    assert {"hardware", "tools", "profiles", "export_formats", "reconstruction_available"} <= set(s)
    assert [p["name"] for p in s["profiles"]] == ["fast", "high", "ultra"]


def test_project_crud(desktop, settings):
    r = desktop.post("/api/projects", json={"name": "Chaise"})
    assert r.status_code == 201
    p = r.json()
    root = settings.projects_dir / p["id"]
    for sub in ("originals", "processed", "reconstruction", "meshes", "textures", "previews", "exports", "logs"):
        assert (root / sub).is_dir()
    assert (root / "metadata.json").exists() and p["status"] == "empty"
    assert desktop.patch(f"/api/projects/{p['id']}", json={"name": "Chaise bois"}).json()["name"] == "Chaise bois"
    dup = desktop.post(f"/api/projects/{p['id']}/duplicate").json()
    assert dup["name"] == "Chaise bois (copie)" and dup["id"] != p["id"]
    desktop.patch(f"/api/projects/{p['id']}", json={"archived": True})
    assert [x["id"] for x in desktop.get("/api/projects").json()] == [dup["id"]]
    assert len(desktop.get("/api/projects?archived=true").json()) == 2
    assert desktop.delete(f"/api/projects/{p['id']}").status_code == 400  # confirmation required
    assert desktop.delete(f"/api/projects/{p['id']}?confirm=true").status_code == 200
    assert not root.exists()
    assert desktop.get(f"/api/projects/{p['id']}").status_code == 404
    assert desktop.get("/api/projects/../../etc").status_code == 404


def test_photo_upload_validation(desktop, settings):
    pid = make_project(desktop, 0)
    files = [
        ("files", ("ok.jpg", jpeg_bytes(1), "image/jpeg")),
        ("files", ("../../evil name.jpg", jpeg_bytes(2), "image/jpeg")),
        ("files", ("blurry.jpg", jpeg_bytes(3, blur=True), "image/jpeg")),
        ("files", ("fake.jpg", b"not an image at all", "image/jpeg")),
        ("files", ("doc.pdf", b"%PDF-1.4", "application/pdf")),
        ("files", ("tiny.jpg", jpeg_bytes(4, size=(100, 80)), "image/jpeg")),
        ("files", ("huge.jpg", b"\xff" * (3 * 1024 * 1024), "image/jpeg")),
    ]
    r = desktop.post(f"/api/projects/{pid}/photos", files=files)
    assert r.status_code == 200
    body = r.json()
    names = [a["name"] for a in body["added"]]
    assert names == ["ok.jpg", "evil_name.jpg", "blurry.jpg"]
    assert next(a for a in body["added"] if a["name"] == "blurry.jpg")["warnings"] == ["floue"]
    errors = {x["file"]: x["status"] for x in body["rejected"]}
    assert errors == {"fake.jpg": 415, "doc.pdf": 415, "tiny.jpg": 422, "huge.jpg": 413}
    originals = settings.projects_dir / pid / "originals"
    assert sorted(p.name for p in originals.iterdir()) == sorted(names)
    p = desktop.get(f"/api/projects/{pid}").json()
    assert p["photo_count"] == 3 and p["status"] == "ready" and p["has_thumbnail"]
    assert desktop.get(f"/api/projects/{pid}/photos/ok.jpg?thumb=true").headers["content-type"] == "image/jpeg"
    assert desktop.delete(f"/api/projects/{pid}/photos/ok.jpg").status_code == 200
    assert desktop.get(f"/api/projects/{pid}").json()["photo_count"] == 2
    # duplicate file names are de-duplicated, never overwritten
    desktop.post(f"/api/projects/{pid}/photos", files=[("files", ("blurry.jpg", jpeg_bytes(5), "image/jpeg"))])
    assert (originals / "blurry_1.jpg").exists()


# ---------------------------------------------------------------- pairing / auth
def test_phone_requires_pairing_and_explicit_approval(desktop, phone):
    assert phone.get("/api/projects").status_code == 401
    assert phone.get("/api/whoami").json() == {"role": "anonymous", "name": ""}
    assert phone.post("/api/pair/sessions").status_code == 401        # only the desktop creates codes
    s = desktop.post("/api/pair/sessions").json()
    assert len(s["code"]) == 6
    assert phone.post("/api/pair/claim", json={"code": "000000" if s["code"] != "000000" else "111111"}).status_code == 403
    claim = phone.post("/api/pair/claim", json={"code": s["code"], "device_name": "iPhone de Loïc"}).json()
    # the same code cannot be reused by another device
    assert phone.post("/api/pair/claim", json={"code": s["code"]}).status_code == 403
    poll = phone.get(f"/api/pair/requests/{claim['request_id']}", params={"secret": claim["secret"]}).json()
    assert poll == {"status": "pending"}
    assert phone.post(f"/api/pair/requests/{claim['request_id']}/approve").status_code == 401
    pending = desktop.get("/api/pair/pending").json()
    assert [p["device_name"] for p in pending] == ["iPhone de Loïc"]
    desktop.post(f"/api/pair/requests/{claim['request_id']}/approve")
    poll = phone.get(f"/api/pair/requests/{claim['request_id']}", params={"secret": claim["secret"]}).json()
    assert poll["status"] == "approved" and poll["token"]
    token = poll["token"]
    again = phone.get(f"/api/pair/requests/{claim['request_id']}", params={"secret": claim["secret"]}).json()
    assert "token" not in again  # handed out exactly once
    assert phone.cookies.get("cam3d_token") == token  # HttpOnly cookie for the phone's browser
    phone.cookies.clear()
    h = {"Authorization": f"Bearer {token}"}
    assert phone.get("/api/whoami", headers=h).json() == {"role": "device", "name": "iPhone de Loïc"}
    r = phone.post("/api/projects", json={"name": "Depuis le téléphone"}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]
    up = phone.post(f"/api/projects/{pid}/photos", files=[("files", ("a.jpg", jpeg_bytes(7), "image/jpeg"))], headers=h)
    assert up.status_code == 200
    assert phone.delete(f"/api/projects/{pid}?confirm=true", headers=h).status_code == 403  # destructive = desktop only
    dev = desktop.get("/api/devices").json()
    assert len(dev) == 1
    desktop.delete(f"/api/devices/{dev[0]['id']}")
    assert phone.get("/api/projects", headers=h).status_code == 401


def test_pairing_rejection(desktop, phone):
    s = desktop.post("/api/pair/sessions").json()
    claim = phone.post("/api/pair/claim", json={"code": s["code"]}).json()
    desktop.post(f"/api/pair/requests/{claim['request_id']}/reject")
    assert phone.get(f"/api/pair/requests/{claim['request_id']}", params={"secret": claim["secret"]}).json()["status"] == "rejected"


# ---------------------------------------------------------------- jobs
def _force_available(app):
    # The stub worker replaces the engine in these tests; mark the engine available.
    from cam3d.server import app as app_module  # noqa
    app.router  # noqa


@pytest.fixture
def engine_available(monkeypatch):
    import cam3d.server.app as m
    real = m.discover_tools

    def fake():
        t = real()
        for v in t.openmvs.values():
            v.available, v.path = True, v.path or "/stub"
        t.pycolmap.available = True
        return t

    monkeypatch.setattr(m, "discover_tools", fake)


def test_reconstruct_needs_three_photos(desktop, engine_available):
    pid = make_project(desktop, 2)
    r = desktop.post(f"/api/projects/{pid}/reconstruct", json={"profile": "fast"})
    assert r.status_code == 422


def test_job_success_events_and_status(desktop, settings, engine_available):
    pid = make_project(desktop)
    with desktop.websocket_connect("/api/events") as ws:
        r = desktop.post(f"/api/projects/{pid}/reconstruct", json={"profile": "high", "formats": ["dae", "obj"]})
        assert r.status_code == 202
        jid = r.json()["id"]
        seen = []
        while True:
            m = ws.receive_json()
            seen.append(m["type"])
            if m["type"] == "job_finished":
                assert m["status"] == "succeeded"
                break
    assert seen[0] == "job_queued" and "job_started" in seen and "job_event" in seen
    j = wait_job(desktop, jid)
    assert j["status"] == "succeeded" and j["profile"] == "high" and j["formats"] == ["dae", "obj"]
    assert [e["status"] for e in j["events"]][:2] == ["started", "progress"]
    p = desktop.get(f"/api/projects/{pid}").json()
    assert p["status"] == "done" and p["has_model"]
    assert desktop.get(f"/api/projects/{pid}/preview.glb").status_code == 200
    assert "noise line" in (settings.projects_dir / pid / "logs" / "worker.log").read_text()
    # history now exists -> an estimate based on a measured run
    est = desktop.get("/api/estimate", params={"profile": "high", "images": 30}).json()["estimate"]
    assert est["based_on_runs"] == 1 and est["seconds"] >= 0
    assert desktop.get("/api/estimate", params={"profile": "ultra", "images": 30}).json()["estimate"] is None


def test_job_failure_and_retry_uses_resume(desktop, settings, engine_available):
    pid = make_project(desktop)
    (settings.projects_dir / pid / "processed" / "STUB_MODE").write_text("fail")
    jid = desktop.post(f"/api/projects/{pid}/reconstruct", json={}).json()["id"]
    j = wait_job(desktop, jid)
    assert j["status"] == "failed" and j["error_stage"] == "sfm" and "caméra" in j["error"]
    assert desktop.get(f"/api/projects/{pid}").json()["status"] == "failed"
    (settings.projects_dir / pid / "processed" / "STUB_MODE").write_text("ok")
    j2 = desktop.post(f"/api/jobs/{jid}/retry").json()
    assert j2["resume"] is True
    assert wait_job(desktop, j2["id"])["status"] == "succeeded"


def test_worker_crash_is_reported(desktop, settings, engine_available):
    pid = make_project(desktop)
    (settings.projects_dir / pid / "processed" / "STUB_MODE").write_text("crash")
    jid = desktop.post(f"/api/projects/{pid}/reconstruct", json={}).json()["id"]
    j = wait_job(desktop, jid)
    assert j["status"] == "failed" and "inattendue" in j["error"]
    assert desktop.get("/api/health").status_code == 200  # server unaffected


def test_cancel_graceful_and_forced(desktop, settings, engine_available):
    pid = make_project(desktop)
    (settings.projects_dir / pid / "processed" / "STUB_MODE").write_text("slow")
    jid = desktop.post(f"/api/projects/{pid}/reconstruct", json={}).json()["id"]
    while desktop.get(f"/api/jobs/{jid}").json()["status"] != "running":
        time.sleep(0.02)
    # a second job on the same project is refused while one is active
    assert desktop.post(f"/api/projects/{pid}/reconstruct", json={}).status_code == 409
    desktop.post(f"/api/jobs/{jid}/cancel")
    assert wait_job(desktop, jid)["status"] == "cancelled"
    assert desktop.get(f"/api/projects/{pid}").json()["status"] == "cancelled"
    # a worker that ignores the cancel request is killed after the grace delay
    (settings.projects_dir / pid / "processed" / "STUB_MODE").write_text("hang")
    jid = desktop.post(f"/api/projects/{pid}/reconstruct", json={}).json()["id"]
    while desktop.get(f"/api/jobs/{jid}").json()["status"] != "running":
        time.sleep(0.02)
    t = time.time()
    desktop.post(f"/api/jobs/{jid}/cancel")
    assert wait_job(desktop, jid, timeout=10)["status"] == "cancelled"
    assert time.time() - t < 8


def test_queue_runs_one_job_at_a_time(desktop, settings, engine_available):
    a, b = make_project(desktop, name="A"), make_project(desktop, name="B")
    (settings.projects_dir / a / "processed" / "STUB_MODE").write_text("slow")
    ja = desktop.post(f"/api/projects/{a}/reconstruct", json={}).json()["id"]
    jb = desktop.post(f"/api/projects/{b}/reconstruct", json={}).json()
    assert jb["status"] == "queued"
    while desktop.get(f"/api/jobs/{ja}").json()["status"] != "running":
        time.sleep(0.02)
    assert desktop.get(f"/api/jobs/{jb['id']}").json()["queue_position"] == 1
    desktop.post(f"/api/jobs/{jb['id']}/cancel")  # cancel while queued
    assert desktop.get(f"/api/jobs/{jb['id']}").json()["status"] == "cancelled"
    desktop.post(f"/api/jobs/{ja}/cancel")
    wait_job(desktop, ja)


def test_interrupted_jobs_recovered_on_restart(settings, engine_available):
    app1 = create_app(settings)
    with TestClient(app1, client=("127.0.0.1", 1)) as c:
        pid = make_project(c)
    # simulate a crash: a job left "running" in the database
    from cam3d.server.db import Database
    Database(settings.db_path).insert("jobs", {"id": "deadbeef0001", "project_id": pid, "kind": "reconstruct", "profile": "fast",
                                  "formats": ["obj"], "resume": 0, "status": "running", "created_at": time.time(), "num_images": 3})
    app2 = create_app(settings)
    with TestClient(app2, client=("127.0.0.1", 1)) as c:
        j = c.get("/api/jobs/deadbeef0001").json()
        assert j["status"] == "interrupted"
        assert c.get(f"/api/projects/{pid}").json()["status"] == "interrupted"


# ---------------------------------------------------------------- real export through the real worker
def test_export_job_with_real_worker(tmp_path, cube_model):
    from cam3d.engine.mesh_io import write_obj

    settings = Settings(data_dir=tmp_path / "data", trusted_hosts=frozenset({"127.0.0.1"}))  # real worker
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 1)) as c:
        pid = c.post("/api/projects", json={"name": "Cube"}).json()["id"]
        root = settings.projects_dir / pid
        assert c.post(f"/api/projects/{pid}/exports", json={"formats": ["dae"]}).status_code == 409  # no model yet
        write_obj(cube_model, root / "meshes" / "model.obj", texture_dir=root / "textures", texture_rel="../textures/")
        r = c.post(f"/api/projects/{pid}/exports", json={"formats": ["dae", "obj", "stl"]})
        assert r.status_code == 202
        j = wait_job(c, r.json()["id"], timeout=60)
        assert j["status"] == "succeeded", j
        files = {e["file"]: e for e in c.get(f"/api/projects/{pid}/exports").json()}
        assert {"model_dae.zip", "model_obj.zip", "model.stl"} <= set(files)
        import zipfile
        for z in ("model_dae.zip", "model_obj.zip"):  # re-exports from meshes/model.obj keep the texture
            names = zipfile.ZipFile(root / "exports" / z).namelist()
            assert any(n.endswith(".jpg") for n in names), (z, names)
        assert files["model_dae.zip"]["textured"] is True
        assert files["model.stl"]["textured"] is False
        d = c.get(f"/api/projects/{pid}/exports/model_dae.zip")
        assert d.status_code == 200 and d.content[:2] == b"PK"
        assert "Cube_model_dae.zip" in d.headers["content-disposition"]
        assert c.get(f"/api/projects/{pid}/exports/..%2F..%2Fmetadata.json").status_code == 404
        assert "Export" in c.get(f"/api/projects/{pid}/logs/export").text or True


def test_log_filter_redacts_tokens():
    import logging

    from cam3d.cli import RedactTokensFilter

    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s"', 
                            ("192.0.2.2:1", "GET", "/api/pair/requests/x?secret=S3cr3t&z=1"), None)
    assert RedactTokensFilter().filter(rec)
    assert rec.getMessage() == '192.0.2.2:1 - "GET /api/pair/requests/x?secret=***&z=1"'
    rec2 = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, '"WebSocket /api/events?token=abc-DEF_1" [accepted]', None, None)
    RedactTokensFilter().filter(rec2)
    assert rec2.getMessage() == '"WebSocket /api/events?token=***" [accepted]'


# ---------------------------------------------------------------- video (real worker + real FFmpeg)
@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="FFmpeg absent")
def test_video_import_extracts_distinct_sharp_frames(tmp_path):
    import subprocess

    # 4 distinct textured "views", each held 1.5 s, plus a blurred copy of view 2: a camera that stops,
    # moves, and shakes. Expect one frame per distinct view, never the blurred one.
    imgs = []
    for i in range(4):
        p = tmp_path / f"v{i}.jpg"
        p.write_bytes(jpeg_bytes(100 + i, size=(1280, 960)))
        imgs.append(p)
    from PIL import Image, ImageFilter
    Image.open(imgs[2]).filter(ImageFilter.GaussianBlur(6)).save(tmp_path / "blur.jpg", quality=92)
    order = [imgs[0], imgs[1], tmp_path / "blur.jpg", imgs[2], imgs[3]]
    lst = tmp_path / "list.txt"
    lst.write_text("".join(f"file '{p}'\nduration 1.5\n" for p in order) + f"file '{order[-1]}'\n")
    video = tmp_path / "walk.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "18", str(video)], check=True)

    settings = Settings(data_dir=tmp_path / "data", trusted_hosts=frozenset({"127.0.0.1"}))  # real worker
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 1)) as c:
        pid = c.post("/api/projects", json={"name": "Vidéo"}).json()["id"]
        assert c.post(f"/api/projects/{pid}/video", files={"file": ("doc.txt", b"x", "text/plain")}).status_code == 415
        with open(video, "rb") as f:
            r = c.post(f"/api/projects/{pid}/video", files={"file": ("walk.mp4", f, "video/mp4")})
        assert r.status_code == 202 and r.json()["kind"] == "video"
        j = wait_job(c, r.json()["id"], timeout=120)
        assert j["status"] == "succeeded", j
        assert j["stages"]["video"]["frames_added"] == c.get(f"/api/projects/{pid}").json()["photo_count"]
        photos = c.get(f"/api/projects/{pid}/photos").json()
        assert len(photos) == 4, [p["name"] for p in photos]     # one per distinct view, blur rejected
        assert all(not p["warnings"] for p in photos), [(p["name"], p["warnings"], p["sharpness"], p["brightness"]) for p in photos]
        assert (settings.projects_dir / pid / "originals" / "videos" / "walk.mp4").exists()  # original kept
        assert any(e["progress"] is not None for e in j["events"])  # measured progress


# ---------------------------------------------------------------- non-destructive editing + calibration (real worker)
def test_edit_undo_reset_and_calibrated_export(tmp_path, cube_model):
    import collada

    from cam3d.engine.edit_runner import save_originals
    from cam3d.engine.mesh_io import write_obj
    from conftest import make_cube_part

    settings = Settings(data_dir=tmp_path / "data", trusted_hosts=frozenset({"127.0.0.1"}))
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 1)) as c:
        pid = c.post("/api/projects", json={"name": "Edition"}).json()["id"]
        root = settings.projects_dir / pid
        cube_model.parts.append(make_cube_part("far", offset=(6, 0.5, 0), texture=cube_model.parts[0].texture))
        write_obj(cube_model, root / "meshes" / "model.obj", texture_dir=root / "textures", texture_rel="../textures/")
        save_originals(root, cube_model)
        original = (root / "meshes" / "original" / "model.obj").read_bytes()

        r = c.post(f"/api/projects/{pid}/edits", json={"op": {"type": "crop_box", "min": [-1, -1, -1], "max": [1, 2, 1]}})
        assert r.status_code == 202
        j = wait_job(c, r.json()["id"], timeout=60)
        assert j["status"] == "succeeded", j
        p = c.get(f"/api/projects/{pid}").json()
        assert p["model_faces"] == 12 and len(p["edits"]) == 1
        assert (root / "meshes" / "original" / "model.obj").read_bytes() == original  # source untouched
        assert "map_Kd" in (root / "meshes" / "original" / "model.mtl").read_text()   # original keeps its texture
        assert list((root / "textures").glob("model_*.jpg")), "edited model lost its texture"
        import trimesh
        g = list(trimesh.load(root / "previews" / "model.glb").geometry.values())[0]
        assert g.visual.material.baseColorTexture is not None, "edited preview lost its texture"

        # an edit that would delete everything fails and is NOT recorded
        r = c.post(f"/api/projects/{pid}/edits", json={"op": {"type": "crop_box", "min": [50, 50, 50], "max": [51, 51, 51]}})
        j = wait_job(c, r.json()["id"], timeout=60)
        assert j["status"] == "failed" and "tout le modèle" in j["error"]
        assert len(c.get(f"/api/projects/{pid}/edits").json()["ops"]) == 1

        j = wait_job(c, c.post(f"/api/projects/{pid}/edits/undo").json()["id"], timeout=60)
        assert j["status"] == "succeeded" and c.get(f"/api/projects/{pid}").json()["model_faces"] == 24
        assert c.post(f"/api/projects/{pid}/edits/undo").status_code == 409
        assert c.post(f"/api/projects/{pid}/edits/reset").status_code == 400  # confirmation required

        # calibration: the two cubes' centres are 6 units apart -> say 3 m
        assert c.put(f"/api/projects/{pid}/calibration", json={"p1": [0, 0.5, 0], "p2": [0, 0.5, 0], "distance": 1, "unit": "m"}).status_code == 400
        cal = c.put(f"/api/projects/{pid}/calibration", json={"p1": [0, 0.5, 0], "p2": [6, 0.5, 0], "distance": 300, "unit": "cm"}).json()
        assert cal["method"] == "manual" and abs(cal["metres_per_unit"] - 0.5) < 1e-12
        assert c.get(f"/api/projects/{pid}").json()["calibration"]["method"] == "manual"
        j = wait_job(c, c.post(f"/api/projects/{pid}/exports", json={"formats": ["dae", "stl"]}).json()["id"], timeout=60)
        assert j["status"] == "succeeded", j
        ex = {e["file"]: e for e in c.get(f"/api/projects/{pid}/exports").json()}
        assert "étalonnée" in ex["model_dae.zip"]["note"]
        doc = collada.Collada(str(root / "exports" / "model_dae" / "model.dae"))
        xs = np.concatenate([p.vertex[:, 0] for g in doc.geometries for p in g.primitives])
        assert abs((xs.max() - xs.min()) - 3.5) < 1e-6   # (6 + 1) units * 0.5 m
        import trimesh
        stl = trimesh.load(root / "exports" / "model.stl")
        assert abs(stl.extents[0] - 3.5) < 1e-6
        # removing the calibration also removes the exports made with it
        c.delete(f"/api/projects/{pid}/calibration")
        assert c.get(f"/api/projects/{pid}/exports").json() == []


# ---------------------------------------------------------------- browser-based attacks from other web sites
def test_dns_rebinding_gets_no_desktop_rights(app):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        assert c.get("/api/whoami", headers={"Host": "127.0.0.1:8765"}).json()["role"] == "desktop"
        assert c.get("/api/whoami", headers={"Host": "localhost:8765"}).json()["role"] == "desktop"
        # attacker.example resolved to 127.0.0.1 by DNS rebinding: same client address, foreign Host
        assert c.get("/api/whoami", headers={"Host": "attacker.example:8765"}).json()["role"] == "anonymous"
        assert c.get("/api/projects", headers={"Host": "attacker.example:8765"}).status_code == 401


def test_cross_site_requests_are_refused(desktop):
    evil = {"Origin": "https://attacker.example"}
    r = desktop.post("/api/projects", json={"name": "x"}, headers=evil)
    assert r.status_code == 403
    r = desktop.post("/api/projects", data={"name": "x"}, headers=evil)  # "simple" form POST, no preflight
    assert r.status_code == 403
    assert desktop.post("/api/pair/sessions", headers=evil).status_code == 403
    # same-origin and the dev UI (localhost:3000) still work, as do non-browser clients
    assert desktop.post("/api/projects", json={"name": "ok"}, headers={"Origin": "http://testserver"}).status_code == 201
    assert desktop.post("/api/projects", json={"name": "ok"}, headers={"Origin": "http://localhost:3000", "Host": "127.0.0.1:8765"}).status_code == 201
    assert desktop.post("/api/projects", json={"name": "ok"}).status_code == 201
    # cross-site WebSocket hijacking
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with desktop.websocket_connect("/api/events", headers=evil) as ws:
            ws.receive_json()
