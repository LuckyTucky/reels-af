"""Single-pass stitch — concat filter + libass + audio mux in one ffmpeg call.

Each beat is rendered as a SILENT 1080×1920 clip in parallel, then ONE
final ffmpeg call concats them with a sample-accurate ``concat`` filter,
burns the global ASS file (word-burst + optional accents) via libass,
and muxes the full TTS WAV — all in a single encode.

Why single-pass:
  • The concat FILTER is sample-accurate at the re-encoded boundary, so
    there's no sub-frame drift between beats.
  • Audio is muxed in the same pass so the AAC encoder primes once for
    the whole reel — no per-shot priming drift.
  • Subtitles are burned once with libass at canvas resolution.

Accent decision: accents are wired directly into the global ASS via
``build_reel_ass_with_accents``. Accent timing uses cumulative
``beat.target_duration_s`` as the source of truth — small estimate-vs-
reality drift is acceptable since viewers can't perceive ±200ms accent
timing and it avoids a second ffmpeg pass.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from reel_af.models import AccentOverlay, Beat, BeatArtifact, Card
from reel_af.planning.safe_zone import CANVAS_H, CANVAS_W
from reel_af.render.subtitles import (
    write_reel_ass,
    write_reel_ass_with_accents,
)

TARGET_W = CANVAS_W
TARGET_H = CANVAS_H
FPS = 30  # match Veo's native 24-30 fps to skip interpolation.

# ───── Bon Stock outro (logo end card) ───────────────────────────────
# Plan de fin : logo Bon Stock centré ~2 s. Ne se déclenche que si un
# fichier logo existe (sinon le reel se produit exactement comme avant).
OUTRO_DURATION_S = float(os.getenv("REEL_AF_OUTRO_S", "2.0"))
# Fond de l'outro : None = automatique (épouse le fond du logo). Une valeur
# explicite (ex. "white", "black", "0x0b3d2e") force ce fond.
_OUTRO_BG_ENV = os.getenv("REEL_AF_OUTRO_BG") or None


def _outro_background(logo: Path) -> str:
    """Couleur de fond de l'outro. Choix explicite (REEL_AF_OUTRO_BG) sinon
    on épouse le fond du logo : logo à fond plein → couleur de son coin (rendu
    sans bord visible) ; logo détouré (transparent) → noir (il flotte)."""
    if _OUTRO_BG_ENV:
        return _OUTRO_BG_ENV
    try:
        from PIL import Image
        im = Image.open(logo).convert("RGBA")
        r, g, b, a = im.getpixel((1, 1))
        if a >= 128:  # coin opaque → c'est le fond du logo
            return f"0x{r:02x}{g:02x}{b:02x}"
    except Exception:  # noqa: BLE001
        pass
    return "black"


# ───── Signature vocale de fin (voix off sur le logo) ────────────────
# Le texte inclut une indication de jeu entre crochets : la voix Gemini
# l'interprète mais NE la prononce PAS. Ton visé : complice et souriant,
# comme une amie qui te glisse ça à l'oreille — pas une annonce claironnée.
SIGNATURE_TEXT = (
    os.getenv("REEL_AF_SIGNATURE_TEXT")
    or "[warm, playful, with a smile in the voice, like sharing a happy little "
    "secret with a close friend] Bon Stock loves cannabis!"
)
# Voix Gemini féminine chaleureuse et amicale, constante d'un reel à l'autre.
SIGNATURE_VOICE = os.getenv("REEL_AF_SIGNATURE_VOICE") or "Aoede"


def _bonstock_file(basenames: tuple[str, ...]) -> Path | None:
    """Cherche un fichier bon-stock/<nom>.<ext>, INSENSIBLE À LA CASSE
    (Linux distingue « Indicatif.wav » de « indicatif.wav » ; pas nous)."""
    root = Path(__file__).resolve().parents[3] / "bon-stock"
    if not root.is_dir():
        return None
    wanted = {b.lower() for b in basenames}
    exts = {"wav", "mp3", "m4a", "aac", "ogg"}
    for p in sorted(root.iterdir()):
        if (
            p.is_file()
            and p.stem.lower() in wanted
            and p.suffix.lower().lstrip(".") in exts
        ):
            return p
    return None


def _signature_provided() -> Path | None:
    """Fichier de signature vocale fourni par l'utilisateur (prioritaire)."""
    return _bonstock_file(("signature",))


def _background_audio() -> Path | None:
    """Indicatif sonore de fond (jingle) fourni par l'utilisateur, joué sous
    la voix pendant l'outro. Optionnel : None si absent."""
    return _bonstock_file(("indicatif", "jingle"))


async def _signature_audio(cache_dir: Path) -> Path | None:
    """Audio de « Bon Stock loves cannabis! ».

    1) Fichier fourni (bon-stock/signature.*) prioritaire ;
    2) sinon génération UNE FOIS via le TTS (voix féminine fixe), mise en
       cache et réutilisée pour tous les reels suivants ;
    Désactivable avec REEL_AF_SIGNATURE=0. Renvoie None si indisponible —
    l'outro reste alors silencieux (jamais d'échec du reel)."""
    prov = _signature_provided()
    if prov is not None:
        return prov
    if os.getenv("REEL_AF_SIGNATURE", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    cache = cache_dir / ".bonstock-signature.wav"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache
    try:
        from reel_af.render.tts import synthesize_audio_single
        path, _dur = await synthesize_audio_single(
            narration=SIGNATURE_TEXT,
            voice=SIGNATURE_VOICE,
            out_dir=cache_dir / ".sig-tmp",
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(Path(path).read_bytes())
        return cache
    except Exception:  # noqa: BLE001
        return None


def _logo_path() -> Path | None:
    """Chemin du logo Bon Stock, ou None si absent.

    Priorité à la variable d'env REEL_AF_LOGO ; sinon bon-stock/logo.png
    à la racine du dépôt."""
    env = os.getenv("REEL_AF_LOGO", "").strip()
    if env:
        p = Path(env)
        return p if p.exists() else None
    # stitch.py = <repo>/src/reel_af/render/stitch.py → parents[3] = <repo>
    default = Path(__file__).resolve().parents[3] / "bon-stock" / "logo.png"
    return default if default.exists() else None


# ───── Font discovery ────────────────────────────────────────────────


_FONT_CANDIDATES: tuple[str, ...] = (
    # Prefer Montserrat — that's what safe_zone metrics assume.
    "/Library/Fonts/Montserrat-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    # Fallbacks — close-enough bold sans-serifs.
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def _find_font() -> str:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    raise RuntimeError("stitch: no usable font found on this system.")


def _ass_font_name(font_path: str) -> str:
    """Best-effort family name from the font filename."""
    stem = Path(font_path).stem.lower()
    if "montserrat" in stem: return "Montserrat"
    if "arial" in stem:      return "Arial"
    if "helvetica" in stem:  return "Helvetica"
    if "dejavu" in stem:     return "DejaVu Sans"
    if "liberation" in stem: return "Liberation Sans"
    return "sans-serif"


# ───── ffmpeg path escaping ──────────────────────────────────────────


def _ffmpeg_path_arg(path: Path | str) -> str:
    """Escape a filesystem path for use as a filter argument value.

    Filter-graph parsing treats ``:`` as kv separator and ``\\`` as escape,
    so paths with colons need both escaped.
    """
    return str(path).replace("\\", "\\\\").replace(":", r"\:")


def _probe_duration(path: Path) -> float:
    """Duration of a media file via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ───── Per-beat SILENT render ────────────────────────────────────────


async def _render_beat(
    beat: Beat,
    artifact: BeatArtifact,
    out_path: Path,
) -> None:
    """Render one beat as a SILENT 1080×1920 clip.

    Scale + crop the Veo source to the canvas, trim to beat.veo_duration,
    emit at final codec settings so all clips concat cleanly. No
    subtitles, no accents, no audio at this stage — they all happen in
    the single-pass final encode.
    """
    if artifact.video_path is None:
        raise RuntimeError(
            f"stitch: beat {beat.idx} has no video_path on artifact."
        )

    dur = float(beat.veo_duration)
    # setsar=1 normalizes pixel aspect ratio. Veo occasionally emits
    # clips with SAR 0:1 (undefined) or slightly non-square SAR that
    # the concat filter rejects later. Forcing 1:1 here makes every
    # silent clip compatible with concat regardless of Veo's metadata.
    vfilter = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},"
        f"setsar=1,"
        f"fps={FPS},"
        f"format=yuv420p,"
        f"trim=end={dur:.3f},setpts=PTS-STARTPTS"
    )

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(artifact.video_path),
        "-filter_complex", f"[0:v]{vfilter}[v]",
        "-map", "[v]",
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "18",
        "-r", str(FPS),
        "-movflags", "+faststart",
        "-t", f"{dur:.3f}",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"stitch: beat {beat.idx} silent render failed "
            f"(exit {proc.returncode}):\n"
            f"  cmd: {' '.join(shlex.quote(c) for c in cmd)}\n"
            f"  stderr: {stderr.decode(errors='replace')[-800:]}"
        )


# ───── Outro logo (Bon Stock end card) ───────────────────────────────


async def _render_outro(
    logo: Path,
    out_path: Path,
    duration: float = OUTRO_DURATION_S,
) -> None:
    """Rend un plan de fin SILENCIEUX 1080×1920 : logo centré sur fond,
    avec un léger fondu d'entrée. Mêmes réglages codec que les plans de
    beat pour se concaténer proprement."""
    # Boîte de sécurité pour le logo : ~62% de largeur, ~42% de hauteur,
    # ratio préservé (le logo n'est jamais déformé).
    box_w = int(TARGET_W * 0.62)
    box_h = int(TARGET_H * 0.42)
    bg = _outro_background(logo)
    filter_complex = (
        f"[1:v]scale={box_w}:{box_h}:force_original_aspect_ratio=decrease[lg];"
        f"[0:v][lg]overlay=(W-w)/2:(H-h)/2:format=auto,"
        f"fade=t=in:st=0:d=0.4,setsar=1,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c={bg}:s={TARGET_W}x{TARGET_H}:d={duration:.3f}:r={FPS}",
        "-i", str(logo),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "18",
        "-r", str(FPS),
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"stitch: outro logo render failed (exit {proc.returncode}):\n"
            f"  cmd: {' '.join(shlex.quote(c) for c in cmd)}\n"
            f"  stderr: {stderr.decode(errors='replace')[-800:]}"
        )


# ───── Single-pass final assembly ────────────────────────────────────


async def _single_pass_assemble(
    clip_paths: list[Path],
    audio_path: Path,
    ass_path: Path,
    font_path: str,
    out_path: Path,
    signature_audio: Path | None = None,
    outro_start_s: float | None = None,
    background_audio: Path | None = None,
) -> None:
    """One ffmpeg call: concat filter + libass burn + AAC mux.

    Si signature_audio + outro_start_s sont fournis, la signature vocale est
    mixée dans la bande-son À PARTIR de outro_start_s (l'instant où le logo
    apparaît). Si background_audio est fourni, un indicatif sonore joue SOUS
    la voix (volume réduit) sur la même fenêtre."""
    n = len(clip_paths)
    if n == 0:
        raise RuntimeError("stitch: no clips to assemble.")

    ass_arg = _ffmpeg_path_arg(ass_path)
    font_dir_arg = _ffmpeg_path_arg(Path(font_path).parent)

    concat_inputs = "".join(f"[{i}:v]" for i in range(n))
    audio_idx = n

    # Durée totale de la vidéo = somme des plans (beats + éventuel outro).
    # On la calcule pour FORCER la longueur de sortie avec -t : c'est
    # déterministe. (Le vieux réflexe -shortest ne fonctionne pas ici : avec
    # apad, l'audio devient "infini" et -shortest ne coupe pas.)
    total_v = sum(_probe_duration(c) for c in clip_paths)

    use_sig = signature_audio is not None and outro_start_s is not None
    use_bg = use_sig and background_audio is not None
    if use_sig:
        # Narration + signature vocale (+ éventuel indicatif) retardées jusqu'à
        # l'apparition du logo, puis mixées.
        delay_ms = max(0, int(outro_start_s * 1000))
        sig_idx = n + 1
        parts = [f"[{sig_idx}:a]adelay={delay_ms}|{delay_ms}[sig]"]
        mix_labels = [f"[{audio_idx}:a]", "[sig]"]
        if use_bg:
            bg_idx = n + 2
            bg_vol = os.getenv("REEL_AF_SIGNATURE_BG_VOLUME") or "0.35"
            parts.append(
                f"[{bg_idx}:a]adelay={delay_ms}|{delay_ms},volume={bg_vol}[jin]"
            )
            mix_labels.append("[jin]")
        audio_graph = (
            ";".join(parts) + ";"
            + "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:duration=longest:normalize=0[aout]"
        )
    else:
        # apad garde une piste audio continue (silence après la narration)
        # jusqu'à la fin du plan d'outro ; -t fixe la durée exacte du reel.
        audio_graph = f"[{audio_idx}:a]apad[aout]"

    filter_complex = (
        f"{concat_inputs}concat=n={n}:v=1:a=0[concat];"
        f"[concat]subtitles={ass_arg}:fontsdir={font_dir_arg}[v];"
        f"{audio_graph}"
    )

    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    for clip in clip_paths:
        cmd += ["-i", str(clip)]
    cmd += ["-i", str(audio_path)]
    if use_sig:
        cmd += ["-i", str(signature_audio)]
    if use_bg:
        cmd += ["-i", str(background_audio)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[aout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "18",
        "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-t", f"{total_v:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"stitch: single-pass assemble failed (exit {proc.returncode}):\n"
            f"  cmd: {' '.join(shlex.quote(c) for c in cmd)}\n"
            f"  stderr: {stderr.decode(errors='replace')[-1200:]}"
        )


# ───── Public entry point ────────────────────────────────────────────


async def stitch_reel(
    beats: list[Beat],
    artifacts: list[BeatArtifact],
    cards: list[Card],
    accents: list[AccentOverlay | None],
    full_audio_path: Path,
    out_dir: Path,
    run_id: str,
) -> Path:
    """Single-pass reel stitch.

    1. Write the global ASS (word-burst + per-beat accents).
    2. Render each beat's silent 1080×1920 clip in parallel.
    3. ONE final ffmpeg invocation: concat filter (sample-accurate) +
       subtitles filter (libass) + AAC mux of the full TTS WAV.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError(
            "stitch: ffmpeg / ffprobe not found on PATH. "
            "`brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux)."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    font_path = _find_font()
    font_family = _ass_font_name(font_path)

    n = len(beats)
    if len(artifacts) != n:
        raise RuntimeError(
            f"stitch: beats ({n}) and artifacts ({len(artifacts)}) length mismatch"
        )
    if len(accents) != n:
        raise RuntimeError(
            f"stitch: beats ({n}) and accents ({len(accents)}) length mismatch"
        )

    artifacts_by_idx: dict[int, BeatArtifact] = {a.idx: a for a in artifacts}

    # Step 1 — write ONE global ASS file.
    reel_ass = out_dir / "reel.ass"
    if any(a is not None for a in accents):
        write_reel_ass_with_accents(
            cards=cards,
            beats=beats,
            accents=accents,
            out_path=reel_ass,
            font_name=font_family,
        )
    else:
        write_reel_ass(cards, reel_ass, font_name=font_family)

    # Step 2 — render each beat's SILENT clip in parallel.
    clip_paths: list[Path] = []
    render_jobs: list[asyncio.Task[None]] = []
    for beat in beats:
        artifact = artifacts_by_idx.get(beat.idx)
        if artifact is None:
            raise RuntimeError(
                f"stitch: no artifact found for beat idx={beat.idx}"
            )
        out_clip = out_dir / f"beat-{beat.idx:02d}-silent.mp4"
        clip_paths.append(out_clip)
        render_jobs.append(
            asyncio.create_task(
                _render_beat(beat=beat, artifact=artifact, out_path=out_clip)
            )
        )
    await asyncio.gather(*render_jobs)

    # Durée cumulée des plans de narration = instant où le logo apparaîtra.
    # La signature vocale démarrera pile à cet instant.
    beats_total = sum(_probe_duration(c) for c in clip_paths)

    # Step 2 bis — plan de fin (outro) : logo Bon Stock + signature vocale.
    logo = _logo_path()
    signature: Path | None = None
    background: Path | None = None
    outro_start: float | None = None
    if logo is not None:
        signature = await _signature_audio(out_dir.parent)
        background = _background_audio() if signature else None
        sig_dur = _probe_duration(signature) if signature else 0.0
        # L'outro dure au moins OUTRO_DURATION_S, et assez pour ne pas couper
        # la voix (durée de la signature + petite marge).
        outro_dur = max(OUTRO_DURATION_S, sig_dur + 0.3) if sig_dur else OUTRO_DURATION_S
        outro_clip = out_dir / "outro-logo.mp4"
        await _render_outro(logo, outro_clip, duration=outro_dur)
        clip_paths.append(outro_clip)
        outro_start = beats_total

    # Step 3 — single ffmpeg invocation.
    final = out_dir / "reel.mp4"
    await _single_pass_assemble(
        clip_paths=clip_paths,
        audio_path=full_audio_path,
        ass_path=reel_ass,
        font_path=font_path,
        out_path=final,
        signature_audio=signature,
        outro_start_s=outro_start,
        background_audio=background,
    )
    _ = run_id  # accepted for forward-compat / log correlation
    return final


__all__ = ["stitch_reel"]
