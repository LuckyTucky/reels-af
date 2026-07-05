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

# Named art-style presets for fast A/B testing of visual treatment. Set
# REEL_AF_ART_STYLE=<name> to override the content-mode style note above for
# EVERY beat, regardless of content_mode. Describe the visual traits directly
# rather than naming an artist — image models often refuse or water down
# prompts that name a specific (especially living/estate-protected) artist.
# Add more presets here to test another look; no other code changes needed.
_ART_STYLE_PRESETS: dict[str, str] = {
    "style1": (
        "bold pop-art comic illustration, thick black ink outlines around "
        "every shape and figure, flat unshaded colors filled with visible "
        "printed Ben-Day dot halftone patterns (especially in shadows, skin "
        "tones, and backgrounds), a limited bright primary palette of red, "
        "yellow, blue, black and white, high-contrast graphic panel framing "
        "like a vintage comic book page, no photorealism, no gradients, no "
        "soft shading, no film grain; VERTICAL portrait composition (taller "
        "than wide, subject occupies the upper-middle two-thirds), fills the "
        "frame, no text or letters"
    ),
    "style2": (
        "mid-century modern graphic poster illustration, the subject reduced "
        "to a bold flat silhouette or abstract symbolic shape (as if "
        "scissor-cut from colored paper and collaged) rather than rendered "
        "in literal detail, clean hard-edged shapes with no outlines, a "
        "high-contrast limited palette dominated by burnt orange, mustard "
        "yellow, black and cream white with an occasional teal or red "
        "accent, dramatic uncluttered negative space, subtle vintage "
        "screen-print paper grain and slight color-registration offset, no "
        "photorealism, no gradients, no soft shading, no fine detail "
        "rendering, no photographic texture; VERTICAL portrait composition "
        "(taller than wide, subject occupies the upper-middle two-thirds), "
        "fills the frame, no text or letters"
    ),
    "style3": (
        "minimalist modern vector illustration built entirely from clean "
        "flat silhouette shapes, extremely economical — only 2 or 3 flat "
        "solid colors per image, no gradients, no texture, no grain, no "
        "outlines, crisp sharp-edged digital vector shapes; clever use of "
        "negative space so that the empty space between or inside a "
        "silhouette reads as a second hidden image related to the subject, "
        "a witty visual double-meaning; bold saturated flat color fields "
        "(one dominant bright color plus black plus white), graphic-design "
        "poster clarity, extreme reduction to the essential iconic shape, "
        "no photorealism, no shading, no fine detail; VERTICAL portrait "
        "composition (taller than wide, subject occupies the upper-middle "
        "two-thirds), fills the frame, no text or letters"
    ),
    "style4": (
        "dramatic pulp crime-movie poster illustration, painted brushwork "
        "(not photographic, not flat vector), hard directional side-lighting "
        "that cuts faces and scenes half into light and half into deep "
        "shadow, saturated palette of blood red, burnt orange and black with "
        "cream highlights, tilted dramatic angles, trench coats / fedoras / "
        "long cast shadows implying danger and mystery, visible vintage "
        "print grain and slightly aged paper texture, painterly rendering "
        "with soft brush edges rather than crisp vector lines; VERTICAL "
        "portrait composition (taller than wide, subject occupies the "
        "upper-middle two-thirds), fills the frame, no text or letters"
    ),
    "style5": (
        "true black-and-white photographic still, no color whatsoever, "
        "extreme high-contrast chiaroscuro lighting with inky-deep blacks "
        "and blown-out whites, a single hard key light casting dramatic "
        "hard-edged shadow patterns (venetian blinds, staircase railings, "
        "window bars) across faces and walls, thick atmospheric fog or "
        "haze, low-key moody nighttime mood, sharp photographic realism "
        "with visible silver-halide film grain, no illustration, no flat "
        "color, no painterly texture; VERTICAL portrait composition (taller "
        "than wide, subject occupies the upper-middle two-thirds), fills "
        "the frame, no text or letters"
    ),
    "style6": (
        "soft dreamlike gouache-and-watercolor illustration, whimsical "
        "poetic surreal mood, a simplified rounded human silhouette figure "
        "with a blank or minimal featureless face, smooth airbrushed color "
        "gradients (skies blending blue into warm amber or rose), a small "
        "solitary figure set against a vast empty sky or landscape to evoke "
        "quiet wonder and solitude, soft rounded edges with no hard black "
        "outlines, gentle painterly softness, muted-to-saturated pastel "
        "palette dominated by blues; VERTICAL portrait composition (taller "
        "than wide, subject occupies the upper-middle two-thirds), fills "
        "the frame, no text or letters"
    ),
    "style7": (
        "warm realistic narrative oil-painting illustration in the style of "
        "a classic mid-century magazine cover, finely rendered lifelike "
        "detail on people, faces, and everyday American settings, warm "
        "nostalgic palette of ambers, soft reds and muted greens, gentle "
        "storytelling composition that captures one genuine human moment or "
        "expression, soft naturalistic lighting, fully painted texture and "
        "fine brush detail — not flat, not graphic, not vector; VERTICAL "
        "portrait composition (taller than wide, subject occupies the "
        "upper-middle two-thirds), fills the frame, no text or letters"
    ),
    "style8": (
        "bold expressive protest-poster illustration, thick rough hand-"
        "inked outlines with visible brushstroke texture, flat saturated "
        "palette dominated by fire orange, red and yellow plus black and "
        "cream, raw urgent graphic energy, simplified and slightly "
        "exaggerated figures with a satirical edge, high-contrast screen-"
        "print poster texture, bold graphic symbolism, deliberately raw "
        "hand-drawn quality — no photorealism, no smooth digital cleanliness, "
        "no soft shading; VERTICAL portrait composition (taller than wide, "
        "subject occupies the upper-middle two-thirds), fills the frame, no "
        "text or letters"
    ),
    "style9": (
        "stencil-print propaganda-poster illustration, bold high-contrast "
        "layered stencil and halftone-dot texture, a signature limited "
        "palette of deep red, cream/off-white and muted teal-blue plus "
        "black, strong graphic silhouette-based portraiture with monumental "
        "heroic framing, flat stenciled color blocking with hard cut edges, "
        "poster-of-the-people political-art energy, no photorealism, no "
        "soft gradients, no fine painterly detail; VERTICAL portrait "
        "composition (taller than wide, subject occupies the upper-middle "
        "two-thirds), fills the frame, no text or letters"
    ),
    "style10": (
        "playful 1960s-70s psychedelic flat illustration, a bold flat black "
        "silhouette profile or shape anchoring the image, combined with "
        "swirling ribbon-like flat bands of saturated rainbow-adjacent "
        "color (orange, pink, purple, green, yellow) radiating outward, "
        "each band a single flat color fill with no gradient or shading, "
        "whimsical groovy energetic flowing linework, joyful vibrant color "
        "harmony, purely flat 2D graphic poster illustration with no "
        "photorealism and no depth shading; VERTICAL portrait composition "
        "(taller than wide, subject occupies the upper-middle two-thirds), "
        "fills the frame, no text or letters"
    ),
}

# Fallback default when a reel doesn't specify art_style: still configurable
# via .env for anyone who wants every reel on one style without passing it
# each time, but the per-call `art_style` argument (threaded down from
# article_to_reel/topic_to_reel) always takes priority — no restart needed
# to switch styles between reels.
_ART_STYLE_DEFAULT = (os.getenv("REEL_AF_ART_STYLE") or "").strip().lower()


def _style_note(content_mode: str, art_style: str = "") -> str:
    style = (art_style or _ART_STYLE_DEFAULT or "").strip().lower()
    if style and style in _ART_STYLE_PRESETS:
        return _ART_STYLE_PRESETS[style]
    return (
        _SCIENTIFIC_STYLE_NOTE
        if content_mode == "scientific"
        else _GENERAL_STYLE_NOTE
    )


def _augment(prompt: str, content_mode: str = "general", art_style: str = "") -> str:
    """Append the style block (mode-aware, or a named art_style override)."""
    base = prompt.strip().rstrip(".")
    return f"{base}. {_style_note(content_mode, art_style)}."


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
    art_style: str = "",
) -> Path:
    """Generate one 720×1280 first frame for a beat.

    Calls Gemini Image, saves the raw output, then center-crops to 9:16.
    Raises on hard failure — callers catch and fall back to a placeholder
    + ken-burns when an individual frame fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"frame-{idx:02d}-raw.png"
    final_path = out_dir / f"frame-{idx:02d}.jpg"

    augmented = _augment(image_prompt, content_mode, art_style)

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
