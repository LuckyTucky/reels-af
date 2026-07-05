"""Per-beat first-frame + Veo image-to-video generation.

For each beat:
  1. Generate a 720×1280 first frame via Gemini Image (in render/images).
  2. Call Veo i2v with that frame + motion-hint prompt, sized to the
     beat's fixed Veo bucket (4 / 6 / 8s).

Two-tier fallback per beat:
  • Image fails  → placeholder solid-color frame + ken-burns still
  • Veo fails    → real first frame + ken-burns still (no animation)

A single beat never crashes the whole reel.
"""

from __future__ import annotations

import asyncio
import base64
import os
import random
from pathlib import Path
from typing import Optional

from agentfield.media_providers import OpenRouterProvider
from PIL import Image

_BROLL_EXTS = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}

import reel_af.sdk_patches  # noqa: F401
from reel_af.models import Beat, BeatArtifact, BeatVisual, MotionHint
from reel_af.render import cost as cost_track
from reel_af.render.images import generate_first_frame

VIDEO_MODEL = os.getenv(
    "REEL_AF_VIDEO_MODEL", "openrouter/google/veo-3.1-lite"
)

# Default OFF — ken-burns motion from generated stills is the cheap default
# (~$0.10/reel). Set REEL_AF_USE_VEO=true for full Veo i2v motion (~$1.20/reel).
USE_VEO = os.getenv("REEL_AF_USE_VEO", "false").lower() in ("1", "true", "yes")

# Veo i2v target resolution. 720×1280 is Veo Lite's native vertical res.
_VEO_W = 720
_VEO_H = 1280


def _image_to_data_url(path: Path) -> str:
    """Encode a local JPEG/PNG as a data: URL for Veo first_frame input."""
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    if suffix == "jpg":
        suffix = "jpeg"
    return (
        f"data:image/{suffix};base64,"
        f"{base64.b64encode(path.read_bytes()).decode()}"
    )


def _motion_clause(hint: MotionHint) -> str:
    """Map BeatVisual.motion_hint to a free-text Veo prompt clause.

    Veo takes a single prompt string with no separate motion field, so
    we append a "Camera: ..." sentence. ``static`` gets the explicit
    "no movement" phrasing so Veo doesn't drift.
    """
    if hint == "static":
        return "Camera: static, no movement"
    return f"Camera: {hint.replace('_', ' ')}"


def _placeholder_frame(out_path: Path, idx: int) -> Path:
    """Carte de secours de dernier recours quand la génération d'image échoue.

    Fond UNI sombre (teinte verte discrète, façon marque) — pas de dégradé
    deux-tons ni d'étiquette de débogage : une image ratée doit ressembler à
    un plan sobre intentionnel, pas à un bug. Le rendu la transforme en plan
    ken-burns pour que le reel ait quand même quelque chose à montrer."""
    _ = idx  # plus d'étiquette « beat N » dans la sortie
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (_VEO_W, _VEO_H), color=(13, 24, 19))
    img.save(str(out_path), format="JPEG", quality=88)
    return out_path


def _broll_clip() -> Optional[Path]:
    """Clip Envato de b-roll au hasard (bon-stock/broll/). Sert de visuel de
    secours quand la génération d'image d'un beat échoue — bien mieux qu'une
    carte unie. None si le dossier est absent ou vide."""
    root = Path(__file__).resolve().parents[3] / "bon-stock" / "broll"
    if not root.is_dir():
        return None
    vids = [
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower().lstrip(".") in _BROLL_EXTS
    ]
    return random.choice(vids) if vids else None


async def _clip_as_beat_video(src: Path, duration_s: float, out_path: Path) -> Path:
    """Normalise un clip vidéo (Envato) en plan de beat 1080×1920 d'EXACTEMENT
    `duration_s` secondes (bouclé s'il est trop court)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(1.0, float(duration_s))
    vfilter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,fps=30,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(src),
        "-filter_complex", f"[0:v]{vfilter}[v]", "-map", "[v]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-r", "30", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"render.video: normalisation b-roll {src.name} échouée "
            f"(exit {proc.returncode}): {stderr.decode(errors='replace')[-400:]}"
        )
    return out_path


async def _still_as_video(
    frame_path: Path, duration_s: float, out_path: Path,
) -> Path:
    """Render a frame as a ken-burns still video at 1080×1920.

    Used as the fallback when Veo generation fails. The scale + crop
    chain produces canvas-size output even from a 720×1280 first frame,
    and a slow 1.06× zoompan adds enough motion to not feel like a
    frozen image.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur_int = max(1, int(round(duration_s)))
    fps = 30
    n_frames = dur_int * fps
    # zoompan: slowly zoom in from 1.0 to 1.06× over the clip.
    zp = (
        f"zoompan=z='min(zoom+0.0008,1.06)':"
        f"d={n_frames}:s={_VEO_W}x{_VEO_H}:fps={fps}"
    )
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", str(dur_int),
        "-i", str(frame_path),
        "-vf", zp,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        str(out_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"_still_as_video: ffmpeg failed ({proc.returncode}): "
            f"{stderr.decode(errors='replace')[-400:]}"
        )
    return out_path


async def _gen_veo_clip(
    provider: OpenRouterProvider,
    visual: BeatVisual,
    beat: Beat,
    frame_path: Path,
    out_path: Path,
) -> Path:
    """Call Veo i2v with the first frame + motion prompt.

    Sized to ``beat.veo_duration``. The caller wraps this in a try/except
    so a single Veo failure doesn't crash the reel.
    """
    prompt = f"{visual.image_prompt}. {_motion_clause(visual.motion_hint)}."
    first_frame_url = _image_to_data_url(frame_path)
    result = await provider.generate_video(  # type: ignore[attr-defined]
        prompt=prompt,
        model=VIDEO_MODEL,
        image_url=first_frame_url,
        duration=int(beat.veo_duration),
    )
    videos = getattr(result, "videos", None) or []
    if not videos or not videos[0].data:
        raise RuntimeError(
            f"_gen_veo_clip: video provider returned no video for beat {beat.idx}"
        )
    video_bytes = base64.b64decode(videos[0].data)
    raw = getattr(result, "raw_response", None) or {}
    cost_track.add("video", raw.get("cost"), model=VIDEO_MODEL, beat_idx=beat.idx)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(video_bytes)
    return out_path


async def _gen_one(
    provider: OpenRouterProvider,
    beat: Beat,
    visual: BeatVisual,
    out_dir: Path,
    content_mode: str,
    art_style: str = "",
) -> BeatArtifact:
    """Pipeline for one beat: first frame → Veo i2v → BeatArtifact.

    Two-tier fallback. Logged via stdout so a failed beat is visible in
    the run output but doesn't abort.
    """
    frame_path: Optional[Path] = None
    broll: Optional[Path] = None
    try:
        frame_path = await generate_first_frame(
            provider=provider,
            image_prompt=visual.image_prompt,
            idx=beat.idx,
            out_dir=out_dir,
            content_mode=content_mode,
            art_style=art_style,
        )
    except Exception as e:
        # Repli 1 : un clip Envato de b-roll comme visuel du beat (mieux qu'une
        # carte). Repli 2 : la carte de secours sobre, si aucun b-roll dispo.
        broll = _broll_clip()
        if broll is not None:
            print(f"[render.video] beat {beat.idx} image gen failed ({e}); b-roll Envato.")
        else:
            print(f"[render.video] beat {beat.idx} image gen failed ({e}); placeholder.")
            frame_path = _placeholder_frame(
                out_dir / f"frame-{beat.idx:02d}-placeholder.jpg", beat.idx,
            )

    video_path = out_dir / f"clip-{beat.idx:02d}.mp4"
    if broll is not None:
        # Le clip Envato EST le visuel du beat (pas de Veo ni de ken-burns).
        await _clip_as_beat_video(broll, float(beat.veo_duration) + 0.5, video_path)
        return BeatArtifact(idx=beat.idx, first_frame_path=None, video_path=video_path)

    if USE_VEO:
        try:
            await _gen_veo_clip(
                provider=provider,
                visual=visual,
                beat=beat,
                frame_path=frame_path,
                out_path=video_path,
            )
        except Exception as e:
            print(f"[render.video] beat {beat.idx} Veo failed ({e}); ken-burns still.")
            await _still_as_video(
                frame_path, float(beat.veo_duration) + 0.5, video_path,
            )
    else:
        # Cheap default — ken-burns motion from the generated still.
        await _still_as_video(
            frame_path, float(beat.veo_duration) + 0.5, video_path,
        )

    return BeatArtifact(
        idx=beat.idx,
        first_frame_path=frame_path,
        video_path=video_path,
    )


async def generate_beat_videos(
    beats: list[Beat],
    visuals: list[BeatVisual],
    out_dir: Path,
    content_mode: str = "general",
    art_style: str = "",
) -> list[BeatArtifact]:
    """Generate one Veo clip per beat in parallel via asyncio.gather.

    Beats and visuals must be aligned by list index. Returns one
    ``BeatArtifact`` per beat with the final video_path populated.
    """
    if len(beats) != len(visuals):
        raise ValueError(
            f"generate_beat_videos: beats ({len(beats)}) and visuals "
            f"({len(visuals)}) must align"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = OpenRouterProvider()
    artifacts = await asyncio.gather(
        *(
            _gen_one(provider, beat, visual, out_dir, content_mode, art_style)
            for beat, visual in zip(beats, visuals)
        )
    )
    return list(artifacts)
