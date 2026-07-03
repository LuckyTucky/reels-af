"""Auto-vérification post-rendu d'un reel.

Prouve que le fichier final est sain plutôt que de faire confiance aveuglément :
bon format 1080×1920, piste audio présente ET non silencieuse (TTS raté),
absence d'écran noir prolongé (visuels cassés), durée plausible. Inspiré des
« quality gates » d'OpenMontage, taillé pour reels-af.

Non bloquant : écrit un rapport `verification.json` dans le dossier du reel, et
un `PROBLEME.txt` lisible SI un défaut est détecté. Ne lève jamais d'exception
qui casserait un rendu par ailleurs réussi.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

EXPECTED_W = 1080
EXPECTED_H = 1920
MIN_SIZE_BYTES = 50_000
SILENCE_DB = -50.0        # mean_volume en dessous = quasi silencieux
BLACK_FRAC_MAX = 0.25     # > 25% d'écran noir = visuels probablement cassés
DUR_MIN_S = 5.0
DUR_MAX_S = 120.0


def _run(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return f"__ERR__ {e}"


def _probe(path: Path) -> dict:
    out = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height:format=duration,size",
        "-of", "json", str(path),
    ])
    try:
        return json.loads(out)
    except Exception:  # noqa: BLE001
        return {}


def _mean_volume_db(path: Path) -> float | None:
    out = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-",
    ])
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", out)
    return float(m.group(1)) if m else None


def _black_fraction(path: Path, duration: float) -> float:
    if duration <= 0:
        return 0.0
    out = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-vf", "blackdetect=d=0.2:pic_th=0.98", "-an", "-f", "null", "-",
    ])
    total = sum(
        float(x) for x in re.findall(r"black_duration:\s*(\d+(?:\.\d+)?)", out)
    )
    return min(1.0, total / duration)


def _finish(out_dir, report: dict) -> dict:
    if out_dir is not None:
        try:
            d = Path(out_dir)
            (d / "verification.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if not report["ok"]:
                lignes = ["Auto-vérification — PROBLÈME(S) détecté(s) :", ""]
                lignes += [f"  • {pr}" for pr in report["problems"]]
                lignes += ["", "Mesures : " + json.dumps(
                    report["checks"], ensure_ascii=False)]
                (d / "PROBLEME.txt").write_text(
                    "\n".join(lignes) + "\n", encoding="utf-8"
                )
        except Exception:  # noqa: BLE001
            pass
    return report


def verify_reel(video_path, out_dir=None) -> dict:
    """Analyse le reel final. Renvoie {ok, checks, problems} et écrit le rapport."""
    p = Path(video_path)
    problems: list[str] = []
    checks: dict = {}

    if not p.exists() or p.stat().st_size < MIN_SIZE_BYTES:
        problems.append("fichier final absent ou trop petit")
        return _finish(out_dir, {"ok": False, "checks": checks, "problems": problems})

    info = _probe(p)
    streams = info.get("streams", []) or []
    vids = [s for s in streams if s.get("codec_type") == "video"]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    try:
        dur = float(info.get("format", {}).get("duration", 0) or 0)
    except Exception:  # noqa: BLE001
        dur = 0.0
    checks["duree_s"] = round(dur, 2)
    checks["taille_Mo"] = round(p.stat().st_size / 1e6, 2)

    if not vids:
        problems.append("aucune piste vidéo")
    else:
        w = int(vids[0].get("width") or 0)
        h = int(vids[0].get("height") or 0)
        checks["resolution"] = f"{w}x{h}"
        if (w, h) != (EXPECTED_W, EXPECTED_H):
            problems.append(
                f"résolution {w}x{h} (attendu {EXPECTED_W}x{EXPECTED_H})"
            )

    if not auds:
        problems.append("aucune piste audio (narration manquante ?)")
    else:
        mv = _mean_volume_db(p)
        checks["audio_moyen_dB"] = mv
        if mv is not None and mv < SILENCE_DB:
            problems.append(f"audio quasi silencieux ({mv:.0f} dB) — TTS raté ?")

    if dur and dur < DUR_MIN_S:
        problems.append(f"durée très courte ({dur:.1f}s)")
    if dur > DUR_MAX_S:
        problems.append(f"durée anormalement longue ({dur:.1f}s)")

    if vids:
        bf = _black_fraction(p, dur)
        checks["ecran_noir_pct"] = round(bf * 100)
        if bf > BLACK_FRAC_MAX:
            problems.append(f"{bf*100:.0f}% d'écran noir — visuels cassés ?")

    return _finish(out_dir, {"ok": not problems, "checks": checks, "problems": problems})


__all__ = ["verify_reel"]
