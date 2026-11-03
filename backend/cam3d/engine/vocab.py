"""Vocabulary tree used by COLMAP to find overlapping images in large captures.

Beyond a few hundred images, matching every pair is too slow; COLMAP instead
compares each image with the most similar ones, found with a visual vocabulary
(image retrieval). It also detects "loops": the end of a walk around a building
seen again at the start. The vocabulary is a free file published by the COLMAP
project (FAISS format, COLMAP >= 3.12); it is downloaded once, checked against
its SHA-256 and cached. No photo leaves the computer.

Offline or with CAM3D_NO_DOWNLOAD=1, large captures still work with sequential
matching only (no loop detection).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable

VOCAB_URL = "https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_faiss_flickr100K_words256K.bin"
VOCAB_SHA256 = "96ca8ec8ea60b1f73465aaf2c401fd3b3ca75cdba2d3c50d6a2f6f760f275ddc"
VOCAB_NAME = "vocab_tree_faiss_flickr100K_words256K.bin"


def models_dir() -> Path:
    env = os.environ.get("CAM3D_MODELS_DIR")
    if env:
        return Path(env).expanduser()
    data = os.environ.get("CAM3D_DATA_DIR")
    return (Path(data).expanduser() if data else Path.home() / "cam3D") / "models"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached_vocab_tree() -> Path | None:
    p = models_dir() / VOCAB_NAME
    return p if p.is_file() and p.stat().st_size > 0 else None


def fetch_vocab_tree(log: Callable[[str], None] = print, url: str = VOCAB_URL, sha256: str = VOCAB_SHA256,
                     timeout: float = 60.0, attempts: int = 3) -> Path:
    """Downloads the vocabulary once (verified) and returns its path. Raises on failure."""
    dest = models_dir() / VOCAB_NAME
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"Téléchargement du vocabulaire visuel COLMAP (une seule fois, ~72 Mo) : {url}")
    for i in range(1, attempts + 1):
        try:
            return _download(dest, url, sha256, timeout, log)
        except RuntimeError:
            raise  # wrong checksum: retrying would not help
        except Exception as e:
            if i == attempts:
                raise
            log(f"Téléchargement interrompu ({e}), nouvel essai {i + 1}/{attempts}")
            time.sleep(2 * i)
    raise AssertionError("unreachable")


def _download(dest: Path, url: str, sha256: str, timeout: float, log: Callable[[str], None]) -> Path:
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".vocab-", suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (fixed https URL)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        got = _sha256(tmp)
        if got != sha256:
            raise RuntimeError(f"somme de contrôle inattendue ({got[:12]}…) : fichier refusé")
        tmp.replace(dest)
        log(f"Vocabulaire enregistré : {dest}")
        return dest
    finally:
        if tmp.exists():
            tmp.unlink()


def vocab_tree_for_run(log: Callable[[str], None]) -> Path | None:
    """Path to use for a reconstruction, downloading it if allowed; None when unavailable."""
    p = cached_vocab_tree()
    if p:
        return p
    if os.environ.get("CAM3D_NO_DOWNLOAD") == "1":
        log("Vocabulaire visuel absent et téléchargement désactivé (CAM3D_NO_DOWNLOAD=1) : "
            "appariement séquentiel seul, sans détection de boucles.")
        return None
    try:
        return fetch_vocab_tree(log)
    except Exception as e:  # offline, proxy, disk full…
        log(f"Vocabulaire visuel indisponible ({e}) : appariement séquentiel seul, sans détection de boucles. "
            "Pour l'installer plus tard : cam3d fetch-models")
        return None
