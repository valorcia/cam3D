"""Video -> photo frames for photogrammetry (FFmpeg + OpenCV).

A video is *not* assumed to be better than photos: frames suffer from motion
blur, rolling shutter and compression. The selection therefore:

1. probes the video (duration, fps, resolution) with ffprobe;
2. extracts candidate frames at a rate giving ~4 candidates per kept frame,
   at full resolution (FFmpeg applies the phone's rotation metadata);
3. rejects motion-blurred frames (sharpness < 35 % of the video's median) and
   keeps the **sharpest** candidate in each time window (variance of Laplacian);
4. drops frames **too similar** to the previously kept one (camera not moving),
   keeping whichever of the two is sharper,
   and frames too dark / overexposed;
5. targets ``1.5 frames per second of video``, clamped to [30, 150].

Progress is measured: FFmpeg's ``out_time`` vs duration, then frames scored.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from ..events import CancelToken, StageLogger
from ..subprocess_utils import run_tool
from .prepare import sharpness_score


@dataclass
class VideoInfo:
    duration: float
    fps: float
    width: int
    height: int
    codec: str


@dataclass
class FrameSelection:
    video: VideoInfo
    candidates: int
    kept: int
    dropped_similar: int
    dropped_blur: int
    dropped_exposure: int
    frames: list[str]


def probe(ffprobe: str, video: Path) -> VideoInfo:
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,codec_name,avg_frame_rate,duration:format=duration",
                          "-of", "json", str(video)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("Vidéo illisible : format non reconnu par FFmpeg.")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("Aucune piste vidéo trouvée dans ce fichier.")
    s = streams[0]
    num, _, den = (s.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    duration = float(s.get("duration") or data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Durée de la vidéo inconnue.")
    return VideoInfo(duration, fps, int(s.get("width", 0)), int(s.get("height", 0)), s.get("codec_name", "?"))


def _thumb(gray: np.ndarray) -> np.ndarray:
    return cv2.resize(gray, (96, 72), interpolation=cv2.INTER_AREA).astype(np.float32)


def extract_frames(video: Path, out_dir: Path, ffmpeg: str, ffprobe: str, logger: StageLogger,
                   cancel: CancelToken | None = None, min_frames: int = 30, max_frames: int = 150,
                   frames_per_second: float = 1.5, similarity_threshold: float = 3.0,
                   blur_ratio: float = 0.35) -> FrameSelection:
    out_dir = Path(out_dir)
    cand_dir = out_dir / "candidates"
    for d in (cand_dir, out_dir / "selected"):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    info = probe(ffprobe, video)
    target = int(np.clip(round(info.duration * frames_per_second), min_frames, max_frames))
    rate = min(info.fps, max(0.5, 4 * target / info.duration))
    logger.start(f"Vidéo {info.width}×{info.height}, {info.duration:.1f} s à {info.fps:.0f} i/s : "
                 f"extraction de {rate:.2f} image(s)/s, objectif {target} images")

    def on_line(line: str) -> None:
        logger.raw(line)
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                t = int(line.split("=", 1)[1]) / 1e6
                logger.progress(min(0.5, 0.5 * t / info.duration), f"Extraction {t:.0f}/{info.duration:.0f} s")
            except ValueError:
                pass

    run_tool([ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(video), "-vf", f"fps={rate:.4f}",
              "-q:v", "2", "-progress", "pipe:1", "-nostats", str(cand_dir / "c_%05d.jpg")],
             on_line=on_line, cancel=cancel)
    cands = sorted(cand_dir.glob("c_*.jpg"))
    if len(cands) < 3:
        raise RuntimeError("Vidéo trop courte : moins de 3 images extraites.")

    scores: list[tuple[float, float, np.ndarray]] = []
    for i, c in enumerate(cands):
        if cancel:
            cancel.check()
        gray = cv2.imread(str(c), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            scores.append((0.0, 0.0, np.zeros((72, 96), np.float32)))
            continue
        scores.append((sharpness_score(gray), float(gray.mean()), _thumb(gray)))
        if i % 5 == 0:
            logger.progress(0.5 + 0.5 * (i + 1) / len(cands), f"Analyse de netteté {i + 1}/{len(cands)}")

    window = max(1, len(cands) // target)
    # Sharpness depends on the scene, so blur is judged relative to this video:
    # frames far below the median sharpness are motion-blurred.
    median_sharp = float(np.median([sc[0] for sc in scores])) or 1.0
    kept: list[int] = []
    dropped_sim = dropped_exp = dropped_blur = 0
    for start in range(0, len(cands), window):
        idx = range(start, min(start + window, len(cands)))
        good = [j for j in idx if 30 <= scores[j][1] <= 235]
        dropped_exp += len(idx) - len(good)
        sharp = [j for j in good if scores[j][0] >= blur_ratio * median_sharp]
        dropped_blur += len(good) - len(sharp)
        if not sharp:
            continue
        best = max(sharp, key=lambda j: scores[j][0])
        if kept:
            diff = float(np.mean(np.abs(scores[best][2] - scores[kept[-1]][2])))
            if diff < similarity_threshold:
                dropped_sim += 1
                if scores[best][0] > scores[kept[-1]][0]:
                    kept[-1] = best  # same view: keep the sharper frame
                continue
        kept.append(best)
    if len(kept) < 3:
        raise RuntimeError("Trop peu d'images exploitables dans la vidéo (floues, trop sombres ou caméra immobile).")
    frames = []
    for n, j in enumerate(kept, 1):
        dst = out_dir / "selected" / f"{video.stem}_{n:04d}.jpg"
        shutil.move(str(cands[j]), dst)
        frames.append(str(dst))
    shutil.rmtree(cand_dir, ignore_errors=True)
    sel = FrameSelection(info, len(cands), len(frames), dropped_sim, dropped_blur, dropped_exp, frames)
    logger.finish(f"{len(frames)} images retenues sur {len(cands)} candidates "
                  f"({dropped_sim} trop semblables, {dropped_blur} floues, {dropped_exp} mal exposées)",
                  kept=len(frames), candidates=len(cands))
    (out_dir / "selection.json").write_text(json.dumps(asdict(sel), indent=2), encoding="utf-8")
    return sel
