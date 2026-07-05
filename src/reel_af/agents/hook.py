"""Hook reasoner — Essence → best-of-N HookCandidate (mode article).

compose_script écrit tout le ScriptDraft en UN appel .ai() non audité —
le premier hook que le modèle écrit part en prod. Ce module comble l'écart
SANS dupliquer la cascade hunters/critic/judge du mode sujet : il n'y a
qu'UNE essence (un seul angle), donc pas de recherche d'angle à faire, juste
une recherche de FORMULATION. On génère 2-3 candidats auto-notés (même
vocabulaire que critic.py), puis on choisit mécaniquement le mieux noté —
pas de 2e appel LLM juge, les candidats se notent eux-mêmes.
"""

from __future__ import annotations

from typing import Any

from reel_af.models import Essence, HookBatch, HookCandidate, HookPick

_SYSTEM = """You are a viral-hook specialist. Given the essence of an
article, write {n} DIFFERENT candidate opening hooks — the literal first
6-10 spoken words that must stop a scrolling thumb in 1-2 seconds.

Each candidate must use a DIFFERENT hook_variant from:
  shock_stat | contrarian | authority | curiosity_gap | listicle
{hook_menu}

Score each candidate yourself, using this rubric (same scale a downstream
editor uses — be honest and self-critical, not generous):

  • hookability  (1-10) — would a scrolling thumb stop in 1 second if you
                         said this aloud? 10 = visceral wait-what; 1 =
                         headline drone.
  • specificity  (1-10) — does it name a number, named entity, or concrete
                         claim from the essence? 10 = sharp and concrete;
                         1 = vague generality.

Do NOT invent facts not in the essence below."""


def _hook_menu(content_mode: str) -> str:
    return (
        "Prefer authority/shock_stat for scientific content; curiosity_gap "
        "works if the result is genuinely surprising."
        if content_mode == "scientific" else
        "Prefer shock_stat/contrarian/curiosity_gap for general content; "
        "listicle only if the article is structurally a list."
    )


def _user_prompt(essence: Essence, n: int) -> str:
    evidence_block = "\n".join(
        f"    {i + 1}. {e}" for i, e in enumerate(essence.evidence)
    )
    return (
        f"ESSENCE\n"
        f"  content_mode : {essence.content_mode}\n"
        f"  domain       : {essence.domain}\n"
        f"  core_claim   : {essence.core_claim}\n"
        f"  mechanism    : {essence.mechanism}\n"
        f"  evidence:\n"
        f"{evidence_block}\n\n"
        f"Write {n} candidate hooks, each a different variant, each self-scored."
    )


async def pick_hook(app: Any, essence: Essence, n: int = 3) -> HookPick:
    """Un appel .ai() → n HookCandidates ; choisit mécaniquement le meilleur
    score composite (hookability pondérée plus fort que specificity, même
    intuition que le composite de critic.py — pas une moyenne littérale)."""
    result = await app.ai(
        system=_SYSTEM.format(n=n, hook_menu=_hook_menu(essence.content_mode)),
        user=_user_prompt(essence, n),
        schema=HookBatch,
        temperature=0.9,
    )
    ranked = sorted(
        result.candidates,
        key=lambda c: (0.7 * c.hookability + 0.3 * c.specificity),
        reverse=True,
    )
    return HookPick(chosen=ranked[0], all_candidates=result.candidates)
