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


def _phone_exif(orientation: int) -> bytes:
    ex = Image.Exif()
    ex[0x010F] = "Apple"
    ex[0x0110] = "iPhone 15 Pro"
    ex[0x0112] = orientation
    sub = ex.get_ifd(0x8769)
    sub[37386] = 6.86          # focal length (mm)
    sub[41989] = 24            # 35 mm equivalent
    gps = ex.get_ifd(0x8825)
    gps[2] = (48.0, 51.0, 24.0)  # latitude: must not be copied
    return ex.tobytes()


def test_prepare_keeps_camera_exif_for_colmap_but_not_location(tmp_path):
    import pycolmap

    src = tmp_path / "src"
    src.mkdir()
    for i in range(3):  # landscape pixels, "rotate 90°" orientation → portrait working copies
        _noise_image(i, size=(800, 600)).save(src / f"img{i}.jpg", quality=95, exif=_phone_exif(6))
    work = tmp_path / "work"
    lg = StageLogger(Stage.PREPARE, work / "logs")
    prepare_images(src, work, FAST, lg)
    lg.close()
    out = Image.open(work / "images" / "img0.jpg")
    assert out.size == (600, 800)
    ex = out.getexif()
    assert ex.get(0x010F) == "Apple" and ex.get(0x0110) == "iPhone 15 Pro"
    assert 0x0112 not in ex                      # orientation already applied
    assert ex.get_ifd(0x8769).get(41989) == 24
    assert not ex.get_ifd(0x8825)                # no GPS
    # COLMAP reads it: one shared camera, focal from the 35 mm equivalent (diagonal convention)
    db = tmp_path / "db.db"
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"
    pycolmap.extract_features(db, work / "images", camera_mode=pycolmap.CameraMode.AUTO, reader_options=reader,
                              device=pycolmap.Device.cpu)
    with pycolmap.Database.open(db) as d:
        cams = d.read_all_cameras()
    assert len(cams) == 1
    import math
    assert abs(cams[0].focal_length - 24 * math.hypot(600, 800) / math.hypot(36, 24)) < 1.0
