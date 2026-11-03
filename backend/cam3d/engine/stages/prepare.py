"""Stage 1 - image preparation.

* validates formats (JPEG/PNG/HEIC are accepted; HEIC converted if possible),
* reads basic metadata (size, EXIF focal/orientation),
* scores sharpness (variance of Laplacian) and brightness,
* produces working copies limited to ``profile.max_image_size`` so that SfM and
  MVS stay within RAM/time budgets. Originals are never modified.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from ..events import CancelToken, StageLogger
from ..profiles import QualityProfile

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp"}


@dataclass
class ImageInfo:
    name: str                 # working file name (always .jpg/.png)
    source: str               # original path
    width: int
    height: int
    sharpness: float          # variance of Laplacian on a 800px-wide gray version
    brightness: float         # mean gray 0..255
    focal_35mm: float | None  # from EXIF when available
    blurry: bool
    too_dark: bool
    too_bright: bool
    used: bool                # excluded images are kept in metadata but not used


def _exif_focal_35mm(img: Image.Image) -> float | None:
    try:
        exif = img.getexif()
        # 41989 = FocalLengthIn35mmFilm ; 37386 = FocalLength (mm)
        ifd = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
        f35 = ifd.get(41989)
        if f35:
            return float(f35)
        return None
    except Exception:
        return None


def _camera_exif(img: Image.Image) -> bytes | None:
    """Minimal EXIF for the working copy: make, model and focal length only.

    COLMAP derives the focal length in pixels from FocalLengthIn35mmFilm, or from
    FocalLength + its sensor database (make/model), both independent of the resize,
    and lets photos of the same camera share one calibration. Orientation is not
    kept: it is already applied to the pixels. Nothing else (GPS, dates) is copied.
    """
    try:
        src = img.getexif()
        sub = src.get_ifd(0x8769) if hasattr(src, "get_ifd") else {}
        out = Image.Exif()
        for tag in (0x010F, 0x0110):  # Make, Model
            v = src.get(tag)
            if isinstance(v, str) and v.strip():
                out[tag] = v.strip("\x00 ")
        ifd = out.get_ifd(0x8769)
        for tag in (37386, 41989):  # FocalLength (mm), FocalLengthIn35mmFilm
            v = sub.get(tag)
            if v:
                ifd[tag] = v
        if not ifd and not len(out):
            return None
        return out.tobytes()
    except Exception:
        return None


def sharpness_score(gray: np.ndarray) -> float:
    h, w = gray.shape[:2]
    if w > 800:
        gray = cv2.resize(gray, (800, int(h * 800 / w)), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _open_image(path: Path) -> Image.Image:
    if path.suffix.lower() in {".heic", ".heif"}:
        try:
            import pillow_heif  # optional dependency

            pillow_heif.register_heif_opener()
        except ImportError as e:
            raise RuntimeError(
                f"{path.name}: format HEIC non pris en charge (installez 'pillow-heif' ou exportez en JPEG)."
            ) from e
    img = Image.open(path)
    return ImageOps.exif_transpose(img)  # bake EXIF orientation, essential for COLMAP


def prepare_images(
    source_dir: Path,
    work_dir: Path,
    profile: QualityProfile,
    logger: StageLogger,
    cancel: CancelToken | None = None,
    blur_threshold: float = 25.0,
    jpeg_quality: int = 95,
) -> list[ImageInfo]:
    source_dir, work_dir = Path(source_dir), Path(work_dir)
    images_dir = work_dir / "images"
    if images_dir.exists():
        shutil.rmtree(images_dir)
    images_dir.mkdir(parents=True)

    files = sorted(p for p in source_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXT and p.is_file())
    if len(files) < 3:
        raise RuntimeError(f"Au moins 3 photographies sont nécessaires ({len(files)} trouvée(s) dans {source_dir}).")
    logger.start(f"Préparation de {len(files)} image(s), taille max {profile.max_image_size or 'originale'} px")

    infos: list[ImageInfo] = []
    for i, src in enumerate(files):
        if cancel:
            cancel.check()
        try:
            img = _open_image(src)
            img.load()
        except Exception as e:
            logger.log(f"Ignoré {src.name}: image illisible ({e})")
            continue
        focal35 = _exif_focal_35mm(img)
        cam_exif = _camera_exif(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        ow, oh = img.size
        if profile.max_image_size and max(ow, oh) > profile.max_image_size:
            scale = profile.max_image_size / max(ow, oh)
            img = img.resize((round(ow * scale), round(oh * scale)), Image.LANCZOS)
        w, h = img.size
        arr = np.asarray(img.convert("L"))
        sharp = sharpness_score(arr)
        bright = float(arr.mean())
        blurry = sharp < blur_threshold
        too_dark = bright < 30
        too_bright = bright > 235
        used = not blurry and not too_dark and not too_bright

        out_name = f"{src.stem}.jpg"
        save_kw = {"exif": cam_exif} if cam_exif else {}
        img.save(images_dir / out_name, "JPEG", quality=jpeg_quality, subsampling=0, **save_kw)
        infos.append(ImageInfo(out_name, str(src), w, h, round(sharp, 2), round(bright, 1), focal35, blurry, too_dark, too_bright, used))
        if not used:
            reason = "floue" if blurry else "trop sombre" if too_dark else "surexposée"
            logger.log(f"{src.name}: exclue ({reason}, netteté={sharp:.1f}, luminosité={bright:.0f})")
        logger.progress((i + 1) / len(files), f"Image {i + 1}/{len(files)} : {src.name} ({w}x{h})")

    usable = [x for x in infos if x.used]
    if len(usable) < 3:
        # Fall back: keep everything rather than failing on a strict threshold.
        logger.log("Moins de 3 images jugées nettes : toutes les images sont conservées.")
        for x in infos:
            x.used = True
        usable = infos
    for x in infos:
        if not x.used:
            (images_dir / x.name).unlink(missing_ok=True)

    (work_dir / "images.json").write_text(json.dumps([asdict(x) for x in infos], indent=2), encoding="utf-8")
    logger.finish(f"{len(usable)} image(s) prête(s) sur {len(files)}", num_images=len(usable), num_excluded=len(infos) - len(usable))
    return infos
