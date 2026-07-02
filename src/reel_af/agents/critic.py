"""Critic — picks the top 3 EssenceCandidates from the 12 hunters produced.

Runs at lower temperature (0.5) so judgment is consistent. Scores each
candidate on four dimensions and picks a DIVERSE top-3 (not just three
flavors of the same angle).
"""

from __future__ import annotations

from typing import Any

from reel_af.models import CriticOutput, EssenceCandidate


_SYSTEM = """You are a viral-content editor. You're picking the 3 most
viral candidate claims from a list. Score each on these four dimensions:

  • novelty       (1-10) — how many viewers have heard this? 10 = almost
                          nobody. 1 = it's all over Reddit.
  • specificity   (1-10) — does it name a person, year, number, place?
                          10 = "Lynn Margulis, 1967, mitochondria as
                          captured bacteria"; 1 = "philosophers argue".
  • hookability   (1-10) — would a scrolling thumb stop in 1 second
                          if you said this aloud? 10 = visceral wait-
                          what; 1 = headline drone.
  • narratability (1-10) — does it work as a 25-30s spoken story?
                          10 = clear hook + mechanism + payoff; 1 =
                          requires diagrams or jargon.

composite = a 1-10 number reflecting OVERALL viral pick — not a literal
average. A claim that's 10/10 novel but 4/10 narratable scores 6-7,
not 9. You're picking what will WORK on screen.

═══ SUBJECT-CENTRALITY GATE — CHECK THIS FIRST, BEFORE SCORING ═══
The TOPIC's subject must be the PROTAGONIST of the claim: it must own
the hook AND land in the payoff. A claim where the subject is only a
TRIGGER or a doorway to a DIFFERENT subject FAILS this gate.

  Example — topic "cannabis and sleep":
    • PASSES: "cannabis suppresses REM in the first half of the night"
      (cannabis is the actor; the claim is about what cannabis DOES).
    • FAILS: a claim whose real subject is REM cycles, dreams, jazz
      pianists, or muscle memory, with cannabis as a mere footnote.

Any candidate that fails the gate: force its composite to ≤ 3 and DO
NOT put it in chosen_indices, no matter how novel or hookable. Off-
subject virality is worse than useless — it produces a reel that never
mentions what the viewer came for.

Then pick the top 3 indices FROM THE CANDIDATES THAT PASS THE GATE.
Among those, prefer DIVERSITY across hunter angles: if specific_figure
had the top 2, the third pick should be a different angle even if its
composite is slightly lower. Three same-flavored claims make a boring
reel run — but NEVER reach for an off-subject candidate to get variety.

If you genuinely think only 1-2 candidates are worth narrating, return
just those. Quality over quantity.
"""


def _format_candidates(candidates: list[EssenceCandidate]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"[{i}] angle={c.angle}\n"
            f"    claim     : {c.core_claim}\n"
            f"    mechanism : {c.mechanism}\n"
            f"    evidence  : {c.evidence}\n"
            f"    domain    : {c.domain}\n"
            f"    novelty   : {c.novelty_pitch}\n"
        )
    return "\n".join(lines)


async def pick_top_essences(
    app: Any,
    topic: str,
    candidates: list[EssenceCandidate],
    n: int = 3,
) -> CriticOutput:
    """Rank all candidates; return top N indices in chosen_indices."""
    user = (
        f"TOPIC: {topic}\n\n"
        f"CANDIDATES (n={len(candidates)}):\n\n"
        f"{_format_candidates(candidates)}\n\n"
        f"Score every candidate. Then return the top {n} indices in "
        f"chosen_indices. Prefer angle DIVERSITY when scores are close."
    )
    return await app.ai(
        system=_SYSTEM,
        user=user,
        schema=CriticOutput,
        temperature=0.5,
    )
