"""First-frame image generation per beat — Gemini 2.5 Flash Image.

Each beat needs a single still image that Veo will animate into a clip.
The image generator returns a square frame; we center-crop to 9:16 720x1280
which is Veo's native vertical resolution.

Style notes vary by content mode so scientific reels don't end up looking
like a perfume ad.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agentfield.media_providers import OpenRouterProvider
from PIL import Image

import reel_af.sdk_patches  # noqa: F401
from reel_af.render import cost as cost_track

IMAGE_MODEL = os.getenv(
    "REEL_AF_IMAGE_MODEL", "openrouter/google/gemini-2.5-flash-image"
)

# Style notes appended to every image prompt. Picked by content_mode.
_GENERAL_STYLE_NOTE = (
    "cinematic documentary still, warm natural light, shallow depth of field, "
    "35mm film grain, VERTICAL portrait composition (taller than wide, the "
    "subject occupies the upper-middle two-thirds), fills the frame, no text "
    "or letters"
)

_SCIENTIFIC_STYLE_NOTE = (
    "documentary photograph from a working research lab, sharp focus throughout, "
    "neutral white-balanced lighting (overhead fluorescent or a single bright "
    "desk lamp, no warm filters), realistic colors, no shallow depth-of-field "
    "blur, no film grain, no lens flares; VERTICAL portrait composition with "
    "the artifact (plot / paper / interface / instrument) occupying the upper "
    "two-thirds; the frame should look like a phone snapshot of an actual "
    "research workspace, not a movie still; no text or letters in frame"
)


def _style_note(content_mode: str) -> str:
    return (
        _SCIENTIFIC_STYLE_NOTE
        if content_mode == "scientific"
        else _GENERAL_STYLE_NOTE
    )


def _augment(prompt: str, content_mode: str = "general") -> str:
    """Append the style block (mode-aware) to an image prompt."""
    base = prompt.strip().rstrip(".")
    return f"{base}. {_style_note(content_mode)}."


def _crop_to_9x16(src: Path, dest: Path, target_w: int = 720) -> Path:
    """Center-crop the still to 9:16 vertical for Veo i2v input.

    Gemini returns roughly square (1024x1024); Veo expects vertical 9:16.
    Take a centered 9:16 strip and resize to 720x1280 (Veo's native res).

    We DO NOT pass image_config={"aspect_ratio": "9:16"} to the SDK — no
    upstream OpenRouter provider exposes the param, so any request with
    it 404s. We crop locally.
    """
    target_h = target_w * 16 // 9
    img = Image.open(src).convert("RGB")
    w, h = img.size
    desired_ratio = 9 / 16
    cur_ratio = w / h
    if cur_ratio > desired_ratio:
        new_w = int(h * desired_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    elif cur_ratio < desired_ratio:
        new_h = int(w / desired_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    img = img.resize((target_w, target_h), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), format="JPEG", quality=92)
    return dest


async def generate_first_frame(
    provider: OpenRouterProvider,
    image_prompt: str,
    idx: int,
    out_dir: Path,
    content_mode: str = "general",
) -> Path:
    """Generate one 720×1280 first frame for a beat.

    Calls Gemini Image, saves the raw output, then center-crops to 9:16.
    Raises on hard failure — callers catch and fall back to a placeholder
    + ken-burns when an individual frame fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"frame-{idx:02d}-raw.png"
    final_path = out_dir / f"frame-{idx:02d}.jpg"

    augmented = _augment(image_prompt, content_mode)

    # Réessais : la génération d'image (Gemini) rate parfois de façon
    # transitoire (vide, timeout, hoquet réseau). Un seul essai laissait alors
    # un vilain placeholder dans le reel. On tente jusqu'à 3 fois avant de
    # laisser l'appelant retomber sur le placeholder.
    tentatives = int(os.getenv("REEL_AF_IMAGE_RETRIES") or "3")
    derniere_err: Exception | None = None
    for essai in range(max(1, tentatives)):
        try:
            result = await provider.generate_image(
                prompt=augmented, model=IMAGE_MODEL, n=1,
            )
            # Le SDK renvoie un MultimodalResponse dont les images sont dans
            # `.images` (pas une liste directe — d'où l'ancien bug
            # "'MultimodalResponse' object is not subscriptable"). On tolère
            # aussi le cas où une autre version renverrait déjà une liste.
            images = getattr(result, "images", result)
            if images:
                raw = getattr(result, "raw_response", None) or {}
                usage = raw.get("usage") or {}
                cost_track.add(
                    "image", usage.get("cost"), model=IMAGE_MODEL, beat_idx=idx,
                )
                images[0].save(str(raw_path))
                return _crop_to_9x16(raw_path, final_path)
            derniere_err = RuntimeError("image gen returned no images")
        except Exception as e:  # noqa: BLE001
            derniere_err = e
        if essai < tentatives - 1:
            await asyncio.sleep(1.5 * (essai + 1))

    raise RuntimeError(
        f"generate_first_frame: échec après {tentatives} tentative(s) "
        f"pour beat {idx} : {derniere_err}"
    )
