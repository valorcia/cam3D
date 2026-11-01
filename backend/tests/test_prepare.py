import json

import numpy as np
from PIL import Image, ImageFilter

from cam3d.engine.events import Stage, StageLogger
from cam3d.engine.profiles import FAST
from cam3d.engine.stages.prepare import prepare_images


def _noise_image(seed: int, size=(640, 480)) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray((rng.random((size[1], size[0], 3)) * 255).astype(np.uint8))


def test_prepare_filters_blurry_images(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(4):
        _noise_image(i).save(src / f"img{i}.jpg", quality=95)
    _noise_image(9).filter(ImageFilter.GaussianBlur(12)).save(src / "blurry.jpg", quality=95)
    (src / "notes.txt").write_text("ignored")
    work = tmp_path / "work"
    lg = StageLogger(Stage.PREPARE, work / "logs")
    infos = prepare_images(src, work, FAST, lg)
    lg.close()
    assert len(infos) == 5
    blurry = [x for x in infos if not x.used]
    assert [x.name for x in blurry] == ["blurry.jpg"]
    assert sorted(p.name for p in (work / "images").iterdir()) == [f"img{i}.jpg" for i in range(4)]
    meta = json.loads((work / "images.json").read_text())
    assert meta[0]["width"] == 640
