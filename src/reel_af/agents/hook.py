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

import os
from typing import Any

from reel_af.models import Essence, HookBatch, HookCandidate, HookPick

# REEL_AF_LANG=fr bascule hook.py + compose.py en français québécois (voir
# bon-stock/STYLE-FR.md). extract.py reste inchangé (multilingue). Sert de
# REPLI par défaut si aucun `lang` n'est passé par appel — comme
# REEL_AF_ART_STYLE, `lang` est un paramètre PAR REEL (text_to_reel doit
# pouvoir choisir fr/en par requête), pas juste un interrupteur figé au
# démarrage du conteneur.
LANG_DEFAULT = (os.getenv("REEL_AF_LANG") or "en").strip().lower()

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

# Variante FR — voir bon-stock/STYLE-FR.md (registre, tutoiement, anglicismes
# à éviter). Le hook reste ≤12 mots (STYLE-FR : « courte, concrète, une
# seule idée surprenante ») ; les hook_variant restent les mêmes 5 clés
# anglaises (taxonomie interne, jamais montrée au spectateur).
_SYSTEM_FR = """Tu es spécialiste de l'accroche virale. À partir de
l'essence d'un article, écris {n} accroches candidates DIFFÉRENTES — les
6 à 12 premiers mots parlés qui doivent arrêter un pouce qui scrolle en
1-2 secondes.

REGISTRE : français québécois naturel et soigné (ni joual lourd, ni
français de France guindé), tutoiement systématique. REFORMULE l'essence
en français idiomatique — ne calque JAMAIS la syntaxe anglaise, même si
l'essence vient d'un article en anglais. Garde THC, CBD, SQDC et les noms
propres inchangés. Évite les anglicismes (edibles→comestibles,
vape/vaping→vapotage, high→planer/l'effet, weed→cannabis/pot,
pre-roll→préroulé, strain→variété) et les tournures trop hexagonales
(« c'est ouf », « grave », « kiffer », « du coup », « bah »).

Chaque candidate doit utiliser une variante DIFFÉRENTE parmi :
  shock_stat | contrarian | authority | curiosity_gap | listicle
{hook_menu}

Note chaque candidate toi-même, avec cette grille (même échelle qu'un
éditeur en aval — sois honnête et critique, pas généreux) :

  • hookability  (1-10) — un pouce qui scrolle s'arrêterait-il en 1 seconde
                         si tu disais ça à voix haute ? 10 = effet whoa
                         viscéral ; 1 = ton de manchette plate.
  • specificity  (1-10) — nomme-t-elle un chiffre, une entité précise, ou
                         un fait concret de l'essence ? 10 = net et
                         concret ; 1 = généralité vague.

N'invente AUCUN fait qui n'est pas dans l'essence ci-dessous."""


def _hook_menu(content_mode: str, lang: str = "en") -> str:
    if lang == "fr":
        return (
            "Pour du contenu scientifique, préfère authority/shock_stat ; "
            "curiosity_gap si le résultat est vraiment surprenant."
            if content_mode == "scientific" else
            "Pour du contenu général, préfère shock_stat/contrarian/"
            "curiosity_gap ; listicle seulement si l'article est "
            "structurellement une liste."
        )
    return (
        "Prefer authority/shock_stat for scientific content; curiosity_gap "
        "works if the result is genuinely surprising."
        if content_mode == "scientific" else
        "Prefer shock_stat/contrarian/curiosity_gap for general content; "
        "listicle only if the article is structurally a list."
    )


def _user_prompt(essence: Essence, n: int, lang: str = "en") -> str:
    evidence_block = "\n".join(
        f"    {i + 1}. {e}" for i, e in enumerate(essence.evidence)
    )
    if lang == "fr":
        return (
            f"ESSENCE\n"
            f"  content_mode : {essence.content_mode}\n"
            f"  domain       : {essence.domain}\n"
            f"  core_claim   : {essence.core_claim}\n"
            f"  mechanism    : {essence.mechanism}\n"
            f"  evidence:\n"
            f"{evidence_block}\n\n"
            f"Écris {n} accroches candidates, chacune une variante "
            f"différente, chacune auto-notée. Français québécois, "
            f"tutoiement, reformulé — jamais calqué sur l'anglais."
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


async def pick_hook(
    app: Any, essence: Essence, n: int = 3, lang: str = "",
) -> HookPick:
    """Un appel .ai() → n HookCandidates ; choisit mécaniquement le meilleur
    score composite (hookability pondérée plus fort que specificity, même
    intuition que le composite de critic.py — pas une moyenne littérale).

    `lang` ("fr"/"en") bascule le prompt complet en français (voir
    _SYSTEM_FR) ; vide = repli sur REEL_AF_LANG (LANG_DEFAULT). La
    structure de sélection (score composite, HookBatch/HookPick) est
    identique dans les deux langues."""
    resolved_lang = (lang or LANG_DEFAULT or "en").strip().lower()
    system = _SYSTEM_FR if resolved_lang == "fr" else _SYSTEM
    result = await app.ai(
        system=system.format(
            n=n, hook_menu=_hook_menu(essence.content_mode, resolved_lang),
        ),
        user=_user_prompt(essence, n, resolved_lang),
        schema=HookBatch,
        temperature=0.9,
    )
    ranked = sorted(
        result.candidates,
        key=lambda c: (0.7 * c.hookability + 0.3 * c.specificity),
        reverse=True,
    )
    return HookPick(chosen=ranked[0], all_candidates=result.candidates)
