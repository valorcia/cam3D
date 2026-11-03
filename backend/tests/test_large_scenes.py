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
