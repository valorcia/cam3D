"""Import of a scan captured with cam3D Capture through the encrypted relay.

Format (identical to capture/src/lib/crypto.ts):
  object  = b"C3D1" || IV (12 bytes) || AES-256-GCM(ciphertext + tag), AAD = object's relative path
  code    = "c3d1:" + base64url(JSON {"m": manifest URL, "k": base64url(32-byte key), "n": name})
  manifest (path "manifest.bin") = JSON {v, name, created, updated, photos: [{path, name, size, sha256, type}]}

Downloads are limited to HTTPS Vercel Blob hosts (no SSRF towards the local network);
CAM3D_RELAY_ALLOW adds origins for development and tests. Every photo is
authenticated (GCM tag) and checked (SHA-256) before being imported.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"C3D1"
BLOB_HOST_RE = re.compile(r"^[a-z0-9]+\.public\.blob\.vercel-storage\.com$")
MAX_MANIFEST = 2 * 1024 * 1024
MAX_OBJECT = 40 * 1024 * 1024
MAX_PHOTOS = 2000


class RelayError(ValueError):
    pass


@dataclass
class TransferCode:
    manifest_url: str
    key: bytes
    name: str


def _b64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def allowed_origins() -> list[str]:
    return [o.strip().rstrip("/") for o in os.environ.get("CAM3D_RELAY_ALLOW", "").split(",") if o.strip()]


def check_url(url: str) -> str:
    u = urlsplit(url)
    origin = f"{u.scheme}://{u.netloc}"
    if u.scheme == "https" and BLOB_HOST_RE.match(u.hostname or "") and not u.port:
        return url
    if origin in allowed_origins():
        return url
    raise RelayError("Adresse du relais non autorisée (seul le stockage Vercel Blob est accepté)")


def parse_code(code: str) -> TransferCode:
    c = (code or "").strip()
    if "#" in c:
        c = c.split("#", 1)[1]
    from urllib.parse import unquote

    c = unquote(c)
    if not c.startswith("c3d1:"):
        raise RelayError("Code de transfert invalide")
    try:
        d = json.loads(_b64url(c[5:]))
        key = _b64url(d["k"])
    except Exception as e:  # noqa: BLE001
        raise RelayError("Code de transfert illisible") from e
    if len(key) != 32 or not isinstance(d.get("m"), str):
        raise RelayError("Code de transfert incomplet")
    if not urlsplit(d["m"]).path.endswith("/manifest.bin"):
        raise RelayError("Code de transfert invalide")
    return TransferCode(check_url(d["m"]), key, str(d.get("n") or "Scan téléphone")[:120])


def decrypt_object(key: bytes, path: str, blob: bytes) -> bytes:
    if len(blob) < 32 or blob[:4] != MAGIC:
        raise RelayError(f"{path} : objet chiffré invalide")
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], path.encode())
    except Exception as e:  # cryptography.exceptions.InvalidTag
        raise RelayError(f"{path} : déchiffrement impossible (code erroné ou fichier altéré)") from e


def encrypt_object(key: bytes, path: str, plain: bytes, iv: bytes | None = None) -> bytes:
    """Used by tests and tools; the phone app does the same in JavaScript."""
    iv = iv or os.urandom(12)
    return MAGIC + iv + AESGCM(key).encrypt(iv, plain, path.encode())


_PATH_RE = re.compile(r"^[0-9a-f]{32}\.bin$")


def download_scan(code: TransferCode, out_dir: Path, client, on_progress=None, cancel=None) -> dict:
    """Fetch manifest + photos, decrypt, verify; write clear photos into out_dir. Returns the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    r = client.get(code.manifest_url, timeout=60)
    if r.status_code == 404:
        raise RelayError("Scan introuvable sur le relais (effacé après 7 jours, ou pas encore envoyé)")
    r.raise_for_status()
    if len(r.content) > MAX_MANIFEST:
        raise RelayError("Manifeste trop volumineux")
    manifest = json.loads(decrypt_object(code.key, "manifest.bin", r.content))
    photos = manifest.get("photos") or []
    if len(photos) > MAX_PHOTOS:
        raise RelayError("Trop de photos dans ce scan")
    files = []
    used: set[str] = set()
    for i, p in enumerate(photos):
        if cancel is not None:
            cancel.check()
        rel = str(p.get("path", ""))
        if not _PATH_RE.match(rel):
            raise RelayError("Manifeste invalide")
        url = check_url(urljoin(code.manifest_url, rel))
        resp = client.get(url, timeout=120)
        resp.raise_for_status()
        if len(resp.content) > MAX_OBJECT:
            raise RelayError(f"{p.get('name')} : fichier trop volumineux")
        plain = decrypt_object(code.key, rel, resp.content)
        if hashlib.sha256(plain).hexdigest() != p.get("sha256"):
            raise RelayError(f"{p.get('name')} : empreinte SHA-256 incorrecte")
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(p.get("name") or rel)).name).strip("._") or rel
        if not Path(name).suffix:
            name += ".jpg"
        base, n = Path(name), 1
        while name.lower() in used:
            name = f"{base.stem}_{n}{base.suffix}"
            n += 1
        used.add(name.lower())
        (out_dir / name).write_bytes(plain)
        files.append(str(out_dir / name))
        if on_progress:
            on_progress(i + 1, len(photos), name)
    return {"name": manifest.get("name") or code.name, "files": files, "count": len(files)}
