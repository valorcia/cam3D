"""Large captures: matching / mapper choice and the vocabulary tree download."""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from cam3d.engine import vocab
from cam3d.engine.profiles import get_profile
from cam3d.engine.stages.sfm import EXHAUSTIVE_MAX, GLOBAL_MAPPER_MIN, _choose_mapper, _choose_matching


def test_strategy_follows_the_number_of_images():
    p = get_profile("high")
    assert _choose_matching(p, EXHAUSTIVE_MAX) == "exhaustive"
    assert _choose_matching(p, EXHAUSTIVE_MAX + 1) == "sequential"
    assert _choose_mapper(p, GLOBAL_MAPPER_MIN - 1) == "incremental"
    assert _choose_mapper(p, GLOBAL_MAPPER_MIN) == "global"
    forced = dataclasses.replace(p, matching="exhaustive", mapper="incremental")
    assert _choose_matching(forced, 5000) == "exhaustive"
    assert _choose_mapper(forced, 5000) == "incremental"


def test_vocab_download_is_verified_and_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("CAM3D_MODELS_DIR", str(tmp_path / "models"))
    payload = b"fake vocabulary" * 1000
    src = tmp_path / "vocab.bin"
    src.write_bytes(payload)
    url = src.as_uri()
    with pytest.raises(RuntimeError, match="somme de contrôle"):
        vocab.fetch_vocab_tree(log=lambda m: None, url=url, sha256="0" * 64)
    assert vocab.cached_vocab_tree() is None
    assert not list((tmp_path / "models").glob(".vocab-*"))  # no partial file left behind
    got = vocab.fetch_vocab_tree(log=lambda m: None, url=url, sha256=hashlib.sha256(payload).hexdigest())
    assert got.read_bytes() == payload
    assert vocab.cached_vocab_tree() == got


def test_no_vocab_falls_back_without_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("CAM3D_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("CAM3D_NO_DOWNLOAD", "1")
    logs: list[str] = []
    assert vocab.vocab_tree_for_run(logs.append) is None
    assert any("séquentiel seul" in m for m in logs)


def test_offline_download_failure_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("CAM3D_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.delenv("CAM3D_NO_DOWNLOAD", raising=False)

    def offline(*a, **k):
        raise OSError("réseau indisponible")

    monkeypatch.setattr(vocab, "fetch_vocab_tree", offline)
    logs: list[str] = []
    assert vocab.vocab_tree_for_run(logs.append) is None
    assert any("cam3d fetch-models" in m for m in logs)


def test_face_budget_grows_with_the_number_of_photos():
    from cam3d.engine.stages.mvs import FACES_MAX_SCALE, scaled_face_target
    fast, ultra = get_profile("fast"), get_profile("ultra")
    assert scaled_face_target(fast, 11) == fast.mesh_target_faces       # object: unchanged
    assert scaled_face_target(fast, 329) > 5 * fast.mesh_target_faces   # building: ~5.5×
    assert scaled_face_target(fast, 100_000) == FACES_MAX_SCALE * fast.mesh_target_faces
    assert scaled_face_target(ultra, 329) == 0                          # no decimation stays no decimation


def test_mesh_point_spacing_adapts_to_memory():
    from cam3d.engine.stages.mvs import safe_min_point_distance
    gib = 2 ** 30
    # the measured scene: fits in 16 GB with almost no change
    d, est = safe_min_point_distance(2.5, 15_726_000, 15 * gib)
    assert 2.5 <= d < 2.8 and 12e9 < est < 15e9
    # 4× more points with a finer spacing on the same machine: spaced out instead of crashing
    d, est = safe_min_point_distance(2.0, 60_000_000, 15 * gib)
    assert d > 4
    # plenty of memory or unknown memory: the profile's value
    assert safe_min_point_distance(2.0, 1_000_000, 64 * gib)[0] == 2.0
    assert safe_min_point_distance(2.0, 60_000_000, None)[0] == 2.0
