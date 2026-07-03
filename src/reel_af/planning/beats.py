"""Deterministic beat planner — carves a ScriptDraft into narrative Beats.

One Beat per spoken section (hook + mechanism_lines + payoff). Each beat
gets a fixed Veo bucket (4 / 6 / 8 s) picked from the proportional audio
share with role-aware bias (hook floors at 6s; payoff caps at 4s for the
snappy loop-back close).
"""

from __future__ import annotations

import math
import os

from reel_af.models import Beat, ScriptDraft

# Veo i2v fixed clip-length buckets.
_VEO_BUCKETS: tuple[int, int, int] = (4, 6, 8)

# Safety margin (seconds) added before bucket selection.
_SAFETY_S: float = 0.3


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def _bucket_for(seconds: float) -> int:
    """Smallest Veo bucket ≥ ceil(seconds + safety)."""
    target = math.ceil(seconds + _SAFETY_S)
    for b in _VEO_BUCKETS:
        if b >= target:
            return b
    return _VEO_BUCKETS[-1]


def plan_beats(script: ScriptDraft, audio_duration_s: float) -> list[Beat]:
    """Carve a ScriptDraft into Beats aligned to the audio timeline.

    One Beat per:
      - ``script.hook``                 → role="hook",      idx=0
      - ``script.mechanism_lines[i]``   → role="mechanism", idx=1..N
      - ``script.payoff_line``          → role="payoff",    idx=N+1

    ``target_duration_s`` is proportional to the beat's share of total
    script words. ``veo_duration`` is the smallest bucket from {4,6,8}
    that covers the estimated audio share + a small safety margin, with
    role-aware bias:
      - Hook    : floor at 6s   (short hook clips can't stop a scroll)
      - Payoff  : cap at 4s     (snappy close engineers the loop-back)
      - Mechanism: pure bucket lookup
    """
    beat_texts: list[tuple[str, str]] = []
    beat_texts.append(("hook", script.hook))
    for line in script.mechanism_lines:
        beat_texts.append(("mechanism", line))
    if script.payoff_line and script.payoff_line.strip():
        beat_texts.append(("payoff", script.payoff_line))

    word_counts = [_word_count(text) for _, text in beat_texts]
    total_words = sum(word_counts) or 1

    beats: list[Beat] = []
    for idx, ((role, text), wc) in enumerate(zip(beat_texts, word_counts)):
        target = (wc / total_words) * audio_duration_s

        if role == "hook":
            bucket = max(6, _bucket_for(target))
        elif role == "payoff":
            bucket = 4
        else:
            bucket = _bucket_for(target)

        beats.append(
            Beat(
                idx=idx,
                role=role,  # type: ignore[arg-type]
                text=text,
                target_duration_s=target,
                veo_duration=bucket,  # type: ignore[arg-type]
            )
        )

    # Découpe des plans les plus longs (8 s) en deux plans de 4 s : plus
    # d'images, coupes plus fréquentes, plus de dynamisme. Les sous-titres ne
    # sont PAS touchés (ils sont calés sur la narration, pas sur les plans).
    # Chaque sous-plan génère sa propre image. Désactivable : REEL_AF_SPLIT_LONG_PLANS=0.
    if (os.getenv("REEL_AF_SPLIT_LONG_PLANS") or "1").strip().lower() not in (
        "0", "false", "no", "off"
    ):
        reindexed: list[Beat] = []
        for b in beats:
            if b.veo_duration == 8:
                for _ in range(2):
                    reindexed.append(
                        Beat(
                            idx=len(reindexed),
                            role=b.role,  # type: ignore[arg-type]
                            text=b.text,
                            target_duration_s=b.target_duration_s / 2,
                            veo_duration=4,  # type: ignore[arg-type]
                        )
                    )
            else:
                reindexed.append(
                    Beat(
                        idx=len(reindexed),
                        role=b.role,  # type: ignore[arg-type]
                        text=b.text,
                        target_duration_s=b.target_duration_s,
                        veo_duration=b.veo_duration,  # type: ignore[arg-type]
                    )
                )
        beats = reindexed

    return beats
