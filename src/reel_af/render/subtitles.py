"""Global ASS subtitle builder — word-burst + optional accent overlays.

Why ASS instead of per-word ffmpeg drawtext:
  • libass uses real font metrics — no alignment bugs between layers.
  • libass renders the same way as VLC, mpv, every karaoke tool and
    fansub player. The visual matches what people expect.
  • One small .ass file replaces N drawtext filter chains. Easier to
    debug, easier to extend (fades, glow effects are one-liners).

Visual model — word-burst (one word at a time, big, bottom-center):
  • Each word is displayed alone for exactly its own [start_s, end_s]
    audio window. As the audio advances, the next word replaces the
    previous one. Feels like a fast teleprompter pulse.
  • Optional accent overlay (Layer 2) — UPPERCASE editorial card sitting
    in the opposite third of the frame, timed to its beat's window.
"""

from __future__ import annotations

from pathlib import Path

import pysubs2

from reel_af.models import AccentOverlay, Beat, Card
from reel_af.planning.font_metrics import MAX_CHARS_PER_LINE, measured_width
from reel_af.planning.safe_zone import (
    ACCENT_FILL,
    ACCENT_FONT_PX,
    ACCENT_LOWER_Y_PCT,
    ACCENT_STROKE,
    ACCENT_STROKE_PX,
    ACCENT_UPPER_Y_PCT,
    CANVAS_H,
    CANVAS_W,
    SAFE_W,
    SUBTITLE_FILL,
    SUBTITLE_FONT_PX,
    SUBTITLE_STROKE,
)

# Map our safe_zone color names to ASS BGR hex (ASS uses BGR, not RGB).
_NAMED_BGR: dict[str, str] = {
    "white":   "FFFFFF",
    "black":   "000000",
    "yellow":  "00FFFF",
    "green":   "00FF00",
    "red":     "0000FF",
    "blue":    "FF0000",
}


def _to_pysubs2_color(name: str) -> pysubs2.Color:
    """Resolve a safe_zone color name to a pysubs2.Color (RGB internally)."""
    bgr = _NAMED_BGR.get(name.lower(), "FFFFFF")
    b, g, r = int(bgr[0:2], 16), int(bgr[2:4], 16), int(bgr[4:6], 16)
    return pysubs2.Color(r, g, b)


# Word-burst rendering — ONE word at a time, bottom of the canvas, big.
_BURST_FONT_PX = 170                  # single word — give it room
_BURST_Y_PCT = 0.74                   # well into bottom-third, separated
                                      # from accent overlays at 0.62
_BURST_STROKE_PX = 10                 # thick stroke for any background

# ── Auto-fit : empêche un mot/accent long de déborder des bords du cadre ──
# Les tailles ci-dessus sont fixes ; un mot long (ex. « Saint-Lin-Laurentides »)
# dépasse alors les 1080 px et se fait couper des deux côtés. On réduit la
# police juste assez pour que le plus large « jeton » insécable tienne dans
# la largeur visée (centrée), en s'appuyant sur la calibration de font_metrics :
# MAX_CHARS_PER_LINE unités de largeur moyenne remplissent SAFE_W à SUBTITLE_FONT_PX.
_PX_PER_UNIT_REF = SAFE_W / MAX_CHARS_PER_LINE   # px par unité-caractère à 80 px
_BURST_MARGIN_PX = 60                 # marge latérale visée pour le mot karaoké
_ACCENT_MARGIN_PX = 40                # marge latérale visée pour l'accent
_BURST_MIN_PX = 56                    # plancher de lisibilité
_ACCENT_MIN_PX = 46


def _fit_fontsize(text: str, base_px: int, margin_px: int, min_px: int) -> int:
    """Plus grande taille ≤ base_px à laquelle le jeton le plus large de
    `text` tient dans (CANVAS_W - 2*margin_px), centré. libass ne coupe
    jamais À L'INTÉRIEUR d'un mot : c'est donc le mot le plus long qui
    contraint la taille. Évite le débordement latéral hors écran."""
    widest = max((measured_width(tok) for tok in text.split()), default=0.0)
    if widest <= 0:
        return base_px
    target_w = CANVAS_W - 2 * margin_px
    needed_px = widest * _PX_PER_UNIT_REF * (base_px / SUBTITLE_FONT_PX)
    if needed_px <= target_w:
        return base_px
    return max(min_px, int(base_px * target_w / needed_px))


def _fs_prefix(text: str, base_px: int, margin_px: int, min_px: int) -> str:
    """Préfixe ASS `{\\fsN}` si le texte doit être rétréci, sinon ''."""
    fs = _fit_fontsize(text, base_px, margin_px, min_px)
    return "" if fs >= base_px else "{\\fs%d}" % fs


def _make_sub_style(font_name: str) -> pysubs2.SSAStyle:
    """Single-word burst style: bold sans, big, bottom-center.

    Position is anchored BOTTOM_CENTER (``\\an2``) and ``marginv`` is
    measured from the bottom of the canvas.
    """
    margin_bottom = int((1.0 - _BURST_Y_PCT) * CANVAS_H)
    return pysubs2.SSAStyle(
        fontname=font_name,
        fontsize=_BURST_FONT_PX,
        primarycolor=_to_pysubs2_color(SUBTITLE_FILL),
        outlinecolor=_to_pysubs2_color(SUBTITLE_STROKE),
        backcolor=_to_pysubs2_color("black"),
        bold=True,
        outline=_BURST_STROKE_PX,
        shadow=0,
        alignment=pysubs2.Alignment.BOTTOM_CENTER,  # \an2
        marginl=40,
        marginr=40,
        marginv=margin_bottom,
    )


def _make_accent_style(font_name: str, position: str) -> pysubs2.SSAStyle:
    """Accent style: louder, opposite third of frame from the burst layer.

    `position` is "upper_third" or "lower_third"; we anchor BOTTOM_CENTER
    (\\an2) for lower_third so MarginV is measured from the bottom, and
    TOP_CENTER (\\an8) for upper_third.
    """
    if position == "upper_third":
        margin_v = int(ACCENT_UPPER_Y_PCT * CANVAS_H)
        alignment = pysubs2.Alignment.TOP_CENTER
    else:
        margin_v = int((1.0 - ACCENT_LOWER_Y_PCT) * CANVAS_H)
        alignment = pysubs2.Alignment.BOTTOM_CENTER
    return pysubs2.SSAStyle(
        fontname=font_name,
        fontsize=ACCENT_FONT_PX,
        primarycolor=_to_pysubs2_color(ACCENT_FILL),
        outlinecolor=_to_pysubs2_color(ACCENT_STROKE),
        backcolor=_to_pysubs2_color("black"),
        bold=True,
        outline=ACCENT_STROKE_PX,
        shadow=0,
        alignment=alignment,
        marginl=20,
        marginr=20,
        marginv=margin_v,
    )


def _emit_card_events(ssa: pysubs2.SSAFile, cards: list[Card]) -> None:
    """Emit ONE event per WORD across all cards — word-burst style.

    Each word is displayed alone at bottom-center for exactly its
    [start_s, end_s] audio window. As the audio advances, the next word
    replaces the previous one. Feels like a fast teleprompter pulse.
    """
    for card in cards:
        for word in card.words:
            w_start_ms = int(max(0.0, word.start_s) * 1000)
            w_end_ms = int(max(word.start_s, word.end_s) * 1000)
            if w_end_ms <= w_start_ms:
                continue
            # Strip trailing terminal punctuation from the burst text —
            # punctuation in a one-word display reads as noise.
            txt = word.word
            while txt and txt[-1] in ".!?":
                txt = txt[:-1]
            if not txt:
                continue
            # Rétrécit la police si le mot est trop large pour le cadre.
            txt = _fs_prefix(
                txt, _BURST_FONT_PX, _BURST_MARGIN_PX, _BURST_MIN_PX
            ) + txt
            ssa.events.append(
                pysubs2.SSAEvent(
                    start=w_start_ms,
                    end=w_end_ms,
                    style="Sub",
                    text=txt,
                    layer=0,
                )
            )


def build_reel_ass(
    cards: list[Card],
    font_name: str = "Montserrat",
) -> pysubs2.SSAFile:
    """Build the global ASS file directly from cards.

    Card timings are in REEL coordinates. One word-burst event per
    spoken word, anchored bottom-center.
    """
    ssa = pysubs2.SSAFile()
    ssa.info["PlayResX"] = str(CANVAS_W)
    ssa.info["PlayResY"] = str(CANVAS_H)
    # WrapStyle=0: libass auto-wraps when a card exceeds the safe stage.
    ssa.info["WrapStyle"] = "0"
    ssa.styles["Sub"] = _make_sub_style(font_name)
    _emit_card_events(ssa, cards)
    return ssa


def build_reel_ass_with_accents(
    cards: list[Card],
    beats: list[Beat],
    accents: list[AccentOverlay | None],
    font_name: str = "Montserrat",
) -> pysubs2.SSAFile:
    """Like build_reel_ass but ALSO embeds Layer 2 accent events.

    Each accent spans the beat's cumulative window on the audio
    timeline — beat_starts = cumsum of beat.target_duration_s. The
    target durations are estimates; accent timing is best-effort but
    visually fine since viewers can't perceive ±200ms drift.
    """
    if len(beats) != len(accents):
        raise ValueError(
            f"build_reel_ass_with_accents: beats ({len(beats)}) and "
            f"accents ({len(accents)}) length mismatch"
        )

    ssa = build_reel_ass(cards, font_name=font_name)
    ssa.styles["AccentLower"] = _make_accent_style(font_name, "lower_third")
    ssa.styles["AccentUpper"] = _make_accent_style(font_name, "upper_third")

    cursor = 0.0
    beat_starts: list[float] = []
    for beat in beats:
        beat_starts.append(cursor)
        cursor += beat.target_duration_s

    for beat, accent, start_s in zip(beats, accents, beat_starts):
        if accent is None:
            continue
        end_s = start_s + beat.target_duration_s
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        if end_ms <= start_ms:
            continue
        style_name = (
            "AccentUpper" if accent.position == "upper_third" else "AccentLower"
        )
        accent_txt = accent.text.upper()
        accent_txt = _fs_prefix(
            accent_txt, ACCENT_FONT_PX, _ACCENT_MARGIN_PX, _ACCENT_MIN_PX
        ) + accent_txt
        ssa.events.append(
            pysubs2.SSAEvent(
                start=start_ms,
                end=end_ms,
                style=style_name,
                text=accent_txt,
                layer=2,
            )
        )

    return ssa


def write_reel_ass(
    cards: list[Card],
    out_path: Path,
    font_name: str = "Montserrat",
) -> Path:
    """Write the global ASS to disk and return its path."""
    ssa = build_reel_ass(cards, font_name=font_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ssa.save(str(out_path), format_="ass")
    return out_path


def write_reel_ass_with_accents(
    cards: list[Card],
    beats: list[Beat],
    accents: list[AccentOverlay | None],
    out_path: Path,
    font_name: str = "Montserrat",
) -> Path:
    """Write the global ASS (with accents) to disk and return its path."""
    ssa = build_reel_ass_with_accents(
        cards, beats, accents, font_name=font_name,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ssa.save(str(out_path), format_="ass")
    return out_path


__all__ = [
    "build_reel_ass",
    "build_reel_ass_with_accents",
    "write_reel_ass",
    "write_reel_ass_with_accents",
]
