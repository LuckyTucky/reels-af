"""Suivi du coût réel par reel — écrit `cost.json` dans le dossier du reel.

Le moteur sérialise à un reel par processus à la fois (`_REEL_RENDER_LOCK`
dans `app.py`), donc un accumulateur global suffit : pas besoin de threader
un objet à travers tout le pipeline. `reset()` au début de chaque run,
`add()` à chaque appel payant, `write()` à la fin — même schéma que
`render/verify.py` pour `verification.json`.

Couverture :
  - raisonnement (`.ai()`)  → coût réel via le CostTracker du SDK (litellm)
  - images (Gemini Image)   → coût réel via `usage.cost` d'OpenRouter
    (demandé explicitement par `sdk_patches._patch_openrouter_image_usage`)
  - vidéo (Veo)              → coût réel via `usage.cost` du job OpenRouter
  - TTS (Gemini Flash TTS)   → l'endpoint OpenRouter `/audio/speech` ne
    renvoie AUCUNE info de coût (juste des octets audio) ; on ne peut pas
    l'inventer, donc c'est loggé avec `cost_usd=None` + le nombre de
    caractères, et signalé dans `categories_sans_cout_reel`.
"""

from __future__ import annotations

import json
from pathlib import Path

_entries: list[dict] = []


def reset() -> None:
    """À appeler au début de chaque run (article_to_reel / topic_to_reel)."""
    _entries.clear()


def add(category: str, cost_usd: float | None, **extra) -> None:
    """Enregistre un appel payant. `cost_usd=None` si l'API ne l'expose pas."""
    _entries.append({"category": category, "cost_usd": cost_usd, **extra})


def write(out_dir, reasoning_summary: dict | None = None) -> dict:
    """Combine coût médias + coût raisonnement, écrit cost.json. Non bloquant."""
    media_cost = sum(
        e["cost_usd"] for e in _entries if e.get("cost_usd") is not None
    )
    reasoning_cost = (reasoning_summary or {}).get("total_cost_usd", 0.0)
    missing = sorted({e["category"] for e in _entries if e.get("cost_usd") is None})

    report = {
        "total_cost_usd": round(media_cost + reasoning_cost, 4),
        "reasoning": reasoning_summary,
        "media": list(_entries),
        "categories_sans_cout_reel": missing or None,
    }
    try:
        Path(out_dir).joinpath("cost.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass
    return report


__all__ = ["reset", "add", "write"]
