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
import random
import shlex
import shutil
import subprocess
from pathlib import Path

_VIDEO_EXTS = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}
INTRO_MAX_S = float(os.getenv("REEL_AF_INTRO_MAX_S") or "6")

# Transitions entre beats : fondus xfade courts, piochés AU HASARD dans un
# petit ensemble soigné. Durée réglable. Pour désactiver (coupes franches) :
# REEL_AF_TRANSITIONS=none.
TRANSITION_S = float(os.getenv("REEL_AF_TRANSITION_S") or "0.3")
_TRANS_RAW = (os.getenv("REEL_AF_TRANSITIONS") or "").strip().lower()
TRANSITION_POOL: list[str] = (
    [] if _TRANS_RAW in ("", "none", "off", "0")
    else [t.strip() for t in _TRANS_RAW.split(",") if t.strip()]
)

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


def _random_clip(subdir: str) -> Path | None:
    """Choisit AU HASARD une vidéo dans bon-stock/<subdir>/ (ex. intro, outro).
    None si le dossier est absent ou vide."""
    root = Path(__file__).resolve().parents[3] / "bon-stock" / subdir
    if not root.is_dir():
        return None
    vids = [
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower().lstrip(".") in _VIDEO_EXTS
    ]
    return random.choice(vids) if vids else None


def _has_audio(path: Path) -> bool:
    """Vrai si le fichier possède au moins une piste audio."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def _off(flag: str, default: str = "1") -> bool:
    """Un knob .env est-il désactivé ? (0/false/no/off)."""
    return (os.getenv(flag) or default).strip().lower() in ("0", "false", "no", "off")


async def _render_source_clip(src: Path, out_path: Path, max_dur: float) -> float:
    """Rend une vidéo quelconque en clip SILENCIEUX 1080×1920 (mêmes réglages
    codec que les beats, pour se concaténer proprement), plafonné à max_dur.
    Renvoie la durée effective."""
    dur = min(_probe_duration(src), max_dur)
    vfilter = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1,fps={FPS},format=yuv420p,"
        f"trim=end={dur:.3f},setpts=PTS-STARTPTS"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-filter_complex", f"[0:v]{vfilter}[v]", "-map", "[v]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-r", str(FPS), "-movflags", "+faststart", "-t", f"{dur:.3f}", str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"stitch: rendu du clip {src.name} échoué (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[-500:]}"
        )
    return dur


async def _trim_clip(src: Path, out_path: Path, dur: float) -> None:
    """Coupe un clip déjà au format (1080×1920, silencieux) à `dur` secondes."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-t", f"{dur:.3f}", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-r", str(FPS), "-movflags", "+faststart", str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"stitch: coupe du clip {src.name} échouée (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[-400:]}"
        )


async def _xfade_beats(
    clips: list[Path], out_path: Path, T: float, pool: list[str],
) -> None:
    """Enchaîne les plans par fondus xfade — une transition piochée AU HASARD
    dans `pool` à chaque frontière. Les plans doivent avoir un rab >= T (rendu
    avec tail_s) pour ne pas rogner leur temps « solo ». Sortie silencieuse."""
    n = len(clips)
    if n < 2:
        raise RuntimeError("xfade: il faut au moins 2 plans.")
    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c)]
    parts: list[str] = []
    cur = "[0:v]"
    cur_len = _probe_duration(clips[0])
    for k in range(1, n):
        offset = max(0.0, cur_len - T)
        trans = random.choice(pool)
        out_lab = f"[vx{k}]"
        parts.append(
            f"{cur}[{k}:v]xfade=transition={trans}:"
            f"duration={T:.3f}:offset={offset:.3f}{out_lab}"
        )
        cur = out_lab
        cur_len = cur_len + _probe_duration(clips[k]) - T
    cmd += [
        "-filter_complex", ";".join(parts), "-map", cur, "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-r", str(FPS), "-movflags", "+faststart", str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"stitch: xfade beats échoué (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[-600:]}"
        )


def _shift_ass(ass_path: Path, delta_s: float) -> None:
    """Décale tous les événements du fichier ASS de delta_s secondes. Sert
    quand un intro est ajouté devant : les sous-titres karaoké doivent glisser
    d'autant pour rester alignés sur la narration."""
    if delta_s <= 0:
        return

    def _t2s(t: str) -> float:
        h, m, s = t.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    def _s2t(x: float) -> str:
        h = int(x // 3600); x -= h * 3600
        m = int(x // 60); x -= m * 60
        return f"{h}:{m:02d}:{x:05.2f}"

    lignes = ass_path.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lignes:
        if ln.startswith("Dialogue:"):
            head, rest = ln.split(":", 1)
            f = rest.split(",", 9)  # Layer,Start,End,Style,Name,ML,MR,MV,Effect,Text
            if len(f) >= 3:
                f[1] = _s2t(_t2s(f[1]) + delta_s)
                f[2] = _s2t(_t2s(f[2]) + delta_s)
                ln = head + ":" + ",".join(f)
        out.append(ln)
    ass_path.write_text("\n".join(out) + "\n", encoding="utf-8")


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
    tail_s: float = 0.0,
) -> None:
    """Render one beat as a SILENT 1080×1920 clip.

    ``tail_s`` ajoute un court rab en fin de plan (footage de recouvrement)
    pour permettre un fondu enchaîné xfade avec le plan suivant sans rogner
    le temps « solo » du beat.

    Scale + crop the Veo source to the canvas, trim to beat.veo_duration,
    emit at final codec settings so all clips concat cleanly. No
    subtitles, no accents, no audio at this stage — they all happen in
    the single-pass final encode.
    """
    if artifact.video_path is None:
        raise RuntimeError(
            f"stitch: beat {beat.idx} has no video_path on artifact."
        )

    dur = float(beat.veo_duration) + max(0.0, tail_s)
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
    bg_video: Path | None = None,
) -> None:
    """Rend un plan de fin SILENCIEUX 1080×1920 : logo centré, léger fondu.
    Si bg_video est fourni, le fond est CETTE vidéo (recadrée plein cadre,
    bouclée pour remplir la durée) ; sinon un fond de couleur qui épouse le
    logo. Mêmes réglages codec que les beats pour se concaténer proprement."""
    box_w = int(TARGET_W * 0.62)
    box_h = int(TARGET_H * 0.42)
    if bg_video is not None:
        filter_complex = (
            f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1,fps={FPS},format=yuv420p[bg];"
            f"[1:v]scale={box_w}:{box_h}:force_original_aspect_ratio=decrease[lg];"
            f"[bg][lg]overlay=(W-w)/2:(H-h)/2:format=auto,"
            f"fade=t=in:st=0:d=0.4,setsar=1,format=yuv420p[v]"
        )
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(bg_video),
            "-i", str(logo),
        ]
    else:
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
        ]
    cmd += [
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
    audio_overlays: list[dict],
    ass_path: Path,
    font_path: str,
    out_path: Path,
) -> None:
    """One ffmpeg call: concat filter + libass burn + AAC mux.

    ``audio_overlays`` : liste de pistes à mixer, chacune un dict
    ``{path, delay_ms, volume, trim_s}``. Pour chaque piste : coupe optionnelle
    (``trim_s``), retard optionnel (``delay_ms``), atténuation optionnelle
    (``volume``). Sert à placer indicatif-début, narration, voix, indicatif-fin
    au bon moment. La durée de sortie est FORCÉE à la durée vidéo totale avec
    ``-t`` (déterministe)."""
    n = len(clip_paths)
    if n == 0:
        raise RuntimeError("stitch: no clips to assemble.")
    if not audio_overlays:
        raise RuntimeError("stitch: no audio overlays to mix.")

    ass_arg = _ffmpeg_path_arg(ass_path)
    font_dir_arg = _ffmpeg_path_arg(Path(font_path).parent)
    concat_inputs = "".join(f"[{i}:v]" for i in range(n))
    total_v = sum(_probe_duration(c) for c in clip_paths)

    # Un maillon par overlay : (atrim) -> (adelay) -> (volume).
    parts: list[str] = []
    labels: list[str] = []
    for i, ov in enumerate(audio_overlays):
        idx = n + i
        chain: list[str] = []
        trim_s = ov.get("trim_s")
        if trim_s:
            chain.append(f"atrim=0:{float(trim_s):.3f}")
        delay = int(ov.get("delay_ms", 0) or 0)
        if delay > 0:
            chain.append(f"adelay={delay}|{delay}")
        vol = float(ov.get("volume", 1.0))
        if abs(vol - 1.0) > 0.001:
            chain.append(f"volume={vol}")
        if chain:
            lab = f"[oa{i}]"
            parts.append(f"[{idx}:a]{','.join(chain)}{lab}")
            labels.append(lab)
        else:
            labels.append(f"[{idx}:a]")

    if len(labels) == 1:
        audio_graph = (
            parts[0][: -len(labels[0])] + "[aout]" if parts
            else f"{labels[0]}anull[aout]"
        )
    else:
        audio_graph = ";".join(parts)
        if audio_graph:
            audio_graph += ";"
        audio_graph += (
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:normalize=0[aout]"
        )

    filter_complex = (
        f"{concat_inputs}concat=n={n}:v=1:a=0[concat];"
        f"[concat]subtitles={ass_arg}:fontsdir={font_dir_arg}[v];"
        f"{audio_graph}"
    )

    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    for clip in clip_paths:
        cmd += ["-i", str(clip)]
    for ov in audio_overlays:
        cmd += ["-i", str(ov["path"])]
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

    # Step 2 — INTRO (vidéo Envato aléatoire, muette) puis beats.
    clip_paths: list[Path] = []
    intro_dur = 0.0
    intro_src = None if _off("REEL_AF_INTRO") else _random_clip("intro")
    if intro_src is not None:
        intro_clip = out_dir / "intro.mp4"
        intro_dur = await _render_source_clip(intro_src, intro_clip, INTRO_MAX_S)
        clip_paths.append(intro_clip)

    transitions_on = bool(TRANSITION_POOL) and len(beats) >= 2
    tail = TRANSITION_S if transitions_on else 0.0

    beat_clips: list[Path] = []
    render_jobs: list[asyncio.Task[None]] = []
    for beat in beats:
        artifact = artifacts_by_idx.get(beat.idx)
        if artifact is None:
            raise RuntimeError(f"stitch: no artifact found for beat idx={beat.idx}")
        out_clip = out_dir / f"beat-{beat.idx:02d}-silent.mp4"
        beat_clips.append(out_clip)
        render_jobs.append(
            asyncio.create_task(
                _render_beat(beat=beat, artifact=artifact, out_path=out_clip,
                             tail_s=tail)
            )
        )
    await asyncio.gather(*render_jobs)

    narration_dur = _probe_duration(full_audio_path)

    # Les plans : soit enchaînés par fondus xfade aléatoires, soit concaténés en
    # coupes franches. Dans les deux cas on borne à la longueur de la narration
    # (pas de temps mort après la voix → reel punchy).
    beats_video: Path | None = None
    if transitions_on:
        try:
            xf = out_dir / "beats-xfade.mp4"
            await _xfade_beats(beat_clips, xf, TRANSITION_S, TRANSITION_POOL)
            if _probe_duration(xf) > narration_dur + 0.1:
                trimmed = out_dir / "beats.mp4"
                await _trim_clip(xf, trimmed, narration_dur)
                xf = trimmed
            beats_video = xf
        except Exception as e:  # noqa: BLE001
            print(f"[stitch] transitions xfade échouées ({e}); coupes franches.")
            transitions_on = False

    if beats_video is not None:
        clip_paths.append(beats_video)
        beats_total = _probe_duration(beats_video)
    else:
        # Coupes franches : retirer un éventuel rab (pour garder les bonnes
        # frontières), puis borner à la narration plan par plan.
        gardes: list[Path] = []
        acc = 0.0
        EPS = 0.15
        for bc, beat in zip(beat_clips, beats):
            solo = float(beat.veo_duration)
            src = bc
            if tail > 0:
                notail = bc.with_name(bc.stem + "-notail.mp4")
                await _trim_clip(bc, notail, solo)
                src = notail
            if acc >= narration_dur - EPS:
                break
            if acc + solo > narration_dur + EPS:
                coupe = src.with_name(src.stem + "-trim.mp4")
                await _trim_clip(src, coupe, narration_dur - acc)
                gardes.append(coupe)
                acc = narration_dur
                break
            gardes.append(src)
            acc += solo
        if gardes:
            beat_clips = gardes
        clip_paths.extend(beat_clips)
        beats_total = sum(_probe_duration(c) for c in beat_clips)

    # Les sous-titres sont calés sur la narration (départ 0). Un intro devant
    # décale les beats dans le temps → on décale l'ASS d'autant.
    if intro_dur > 0:
        _shift_ass(reel_ass, intro_dur)

    # Step 2 bis — OUTRO : logo (+ voix + indicatif) par-dessus une vidéo Envato.
    logo = _logo_path()
    signature: Path | None = None
    outro_start: float | None = None
    outro_dur = 0.0
    if logo is not None:
        signature = await _signature_audio(out_dir.parent)
        sig_dur = _probe_duration(signature) if signature else 0.0
        outro_dur = (
            max(OUTRO_DURATION_S, sig_dur + 0.3) if sig_dur else OUTRO_DURATION_S
        )
        outro_video = None if _off("REEL_AF_OUTRO_VIDEO") else _random_clip("outro")
        outro_clip = out_dir / "outro-logo.mp4"
        await _render_outro(logo, outro_clip, duration=outro_dur, bg_video=outro_video)
        clip_paths.append(outro_clip)
        outro_start = intro_dur + beats_total

    # Bande-son : indicatif au DÉBUT (sur l'intro) et à la FIN (sur l'outro),
    # narration au milieu, signature vocale à l'arrivée de l'outro.
    jingle = _background_audio()
    intro_bg_vol = float(os.getenv("REEL_AF_INTRO_BG_VOLUME") or "0.8")
    outro_bg_vol = float(os.getenv("REEL_AF_SIGNATURE_BG_VOLUME") or "0.35")
    overlays: list[dict] = []
    if jingle is not None and intro_dur > 0:
        overlays.append({"path": jingle, "delay_ms": 0,
                         "trim_s": intro_dur, "volume": intro_bg_vol})
    overlays.append({"path": full_audio_path,
                     "delay_ms": int(intro_dur * 1000), "volume": 1.0})
    if outro_start is not None:
        # Voix (si activée) ET/OU indicatif de fin — indépendants l'un de
        # l'autre : l'indicatif joue à l'outro même si la voix est désactivée.
        if signature is not None:
            overlays.append({"path": signature,
                             "delay_ms": int(outro_start * 1000), "volume": 1.0})
        if jingle is not None:
            overlays.append({"path": jingle, "delay_ms": int(outro_start * 1000),
                             "trim_s": outro_dur, "volume": outro_bg_vol})

    # Step 3 — single ffmpeg invocation.
    final = out_dir / "reel.mp4"
    await _single_pass_assemble(
        clip_paths=clip_paths,
        audio_overlays=overlays,
        ass_path=reel_ass,
        font_path=font_path,
        out_path=final,
    )

    # Step 4 — auto-vérification post-rendu (non bloquante) : prouve que le
    # reel est sain (format, audio non silencieux, pas d'écran noir). Écrit
    # verification.json, et PROBLEME.txt si un défaut est détecté.
    try:
        from reel_af.render.verify import verify_reel
        await asyncio.to_thread(verify_reel, final, out_dir)
    except Exception:  # noqa: BLE001
        pass

    _ = run_id  # accepted for forward-compat / log correlation
    return final


__all__ = ["stitch_reel"]
