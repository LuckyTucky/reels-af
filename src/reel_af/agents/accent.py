"""Per-beat editorial accent overlay — one `.ai()` call, biased to None."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from reel_af.models import AccentOverlay, Beat, Essence

# REEL_AF_LANG=fr — même bascule que hook.py/compose.py/tts.py. Ces
# surcouches (chiffres, entités nommées, traductions de jargon…) sont du
# texte brûlé à l'écran comme les sous-titres — sans variante FR, elles
# ressortaient en anglais même par-dessus une narration française. Repli
# par défaut si `lang` n'est pas passé par appel (paramètre par reel).
LANG_DEFAULT = (os.getenv("REEL_AF_LANG") or "en").strip().lower()

# The default MUST be None. Every part of the prompt and schema is engineered
# to make the model commit to a yes/no BEFORE constructing the overlay so it
# can't be carried by overlay-construction momentum into emitting one.


class _AccentDecision(BaseModel):
    """Internal wrapper: forces the model to commit yes/no before designing."""

    model_config = ConfigDict(extra="forbid")

    emit_overlay: bool = Field(
        ...,
        description=(
            "Decide FIRST. Default is false. Only set true if one of the 6 "
            "canonical patterns unambiguously applies to this beat."
        ),
    )
    overlay: Optional[AccentOverlay] = Field(
        default=None,
        description=(
            "ONLY set when emit_overlay is true. Must be null otherwise. "
            "When set, text is 2-6 words; the renderer uppercases it."
        ),
    )
    reasoning: str = Field(
        ...,
        description=(
            "1-2 sentences: which of the 6 patterns this matches and why — "
            "OR why no pattern applies and the beat stays clean. Audit trail."
        ),
    )


_SYSTEM_PROMPT = (
    "You decide whether ONE beat of a vertical reel gets an editorial accent "
    "overlay on top of the verbatim word-by-word subtitles already burned at "
    "the upper-center of the frame.\n\n"
    "THE DEFAULT IS emit_overlay=false. Most beats will not emit. Repeat: "
    "most beats will not emit. Over-cluttering the frame is worse than not "
    "adding accent. If no pattern unambiguously applies, emit_overlay MUST "
    "be false. Do not manufacture overlays to fill a quota.\n\n"
    "Only six canonical patterns are allowed. Concrete examples:\n"
    "  • number — narration mentions a specific number worth locking in for a "
    "muted viewer (\"$47,000\", \"85%\", \"3 STEPS\"). The number must actually "
    "appear in this beat's narration.\n"
    "  • named_entity — a person, place, organization, or product whose "
    "spelling matters (\"DR. CHEN, STANFORD\", \"THE HIPPOCAMPUS\"). Not "
    "generic nouns.\n"
    "  • jargon_translation — the narration uses a domain term and a plain-"
    "English gloss would help muted viewers (\"ENTANGLEMENT = SPOOKY LINK\").\n"
    "  • hook_title_card — ONLY allowed when beat.role == 'hook'. A bold "
    "question or claim, 5-8 words, that becomes the title card.\n"
    "  • reaction — comedic punctuation on a spoken beat (\"WAIT WHAT\", "
    "\"NO WAY\", \"BIG IF TRUE\"). Only when the script clearly has that beat.\n"
    "  • list_marker — only when the script is structured as a numbered "
    "listicle (\"STEP 2 OF 3\", \"1 OF 3\"). Not for generic enumeration.\n\n"
    "Hard rules:\n"
    "  1. If this beat's narration doesn't contain a number to call out, a "
    "named entity that needs spelling, a jargon term being defined, or a "
    "clear emotional / structural beat — emit_overlay MUST be false.\n"
    "  2. hook_title_card is ONLY valid when beat.role == 'hook'. For any "
    "non-hook beat, never use this pattern.\n"
    "  3. Overlay text must be 2-6 words. The renderer uppercases it; you can "
    "write any case.\n"
    "  4. position: hook_title_card → 'upper_third'. Everything else → "
    "'lower_third' (opposite of the subtitles).\n"
    "  5. The overlay must surface information the voiceover does not "
    "explicitly say but the viewer needs to lock in (the number's exact "
    "value, the name's spelling, the comedic beat the audio can't show).\n\n"
    "Output a structured decision: pick emit_overlay first, then either set "
    "overlay to a valid AccentOverlay or leave it null. reasoning explains "
    "which pattern matched, or why none did."
)


# Variante FR — mêmes 6 patrons, exemples traduits/adaptés (pas de calque),
# texte final toujours en français québécois (bon-stock/STYLE-FR.md).
_SYSTEM_PROMPT_FR = (
    "Tu décides si UN plan d'un reel vertical reçoit une surcouche éditoriale "
    "par-dessus les sous-titres mot-à-mot déjà brûlés en haut-centre du cadre.\n\n"
    "LE DÉFAUT EST emit_overlay=false. La plupart des plans n'en émettent pas. "
    "Répète : la plupart des plans n'en émettent pas. Surcharger le cadre est "
    "pire que ne rien ajouter. Si aucun patron ne s'applique sans ambiguïté, "
    "emit_overlay DOIT être false. Ne fabrique pas de surcouches pour remplir "
    "un quota.\n\n"
    "Seuls six patrons canoniques sont permis. Exemples concrets :\n"
    "  • number — la narration mentionne un chiffre précis à fixer pour un "
    "spectateur en sourdine (« 47 000 $ », « 85 % », « 3 ÉTAPES »). Le chiffre "
    "doit vraiment apparaître dans la narration de ce plan.\n"
    "  • named_entity — une personne, un lieu, une organisation ou un produit "
    "dont l'orthographe compte (« DRE CHEN, STANFORD », « L'HIPPOCAMPE »). Pas "
    "un nom commun générique.\n"
    "  • jargon_translation — la narration utilise un terme technique et une "
    "traduction simple aiderait les spectateurs en sourdine (« INTRICATION = "
    "LIEN FANTÔME »).\n"
    "  • hook_title_card — SEULEMENT permis quand beat.role == 'hook'. Une "
    "question ou affirmation percutante, 5-8 mots, qui devient la carte-titre.\n"
    "  • reaction — ponctuation comique sur un plan parlé (« ATTENDS QUOI », "
    "« PAS VRAI », « SI C'EST VRAI, WOW »). Seulement quand le script a "
    "clairement ce moment.\n"
    "  • list_marker — seulement quand le script est structuré en liste "
    "numérotée (« ÉTAPE 2 DE 3 », « 1 SUR 3 »). Pas pour une énumération "
    "générique.\n\n"
    "Règles strictes :\n"
    "  1. Si la narration de ce plan ne contient pas de chiffre à souligner, "
    "d'entité nommée dont l'orthographe compte, de terme technique à "
    "traduire, ou de moment émotionnel/structurel clair — emit_overlay DOIT "
    "être false.\n"
    "  2. hook_title_card est SEULEMENT valide quand beat.role == 'hook'. "
    "Jamais pour un autre plan.\n"
    "  3. Le texte de la surcouche fait 2-6 mots, EN FRANÇAIS QUÉBÉCOIS "
    "(tutoiement si applicable, jamais de calque anglais). Le moteur de rendu "
    "le met en majuscules — écris-le dans la casse que tu veux.\n"
    "  4. position : hook_title_card → 'upper_third'. Tout le reste → "
    "'lower_third' (à l'opposé des sous-titres).\n"
    "  5. La surcouche doit apporter une information que la voix ne dit pas "
    "explicitement mais dont le spectateur a besoin (la valeur exacte du "
    "chiffre, l'orthographe du nom, le moment comique que l'audio ne peut "
    "pas montrer).\n\n"
    "Retourne une décision structurée : choisis emit_overlay en premier, puis "
    "soit tu fixes overlay à un AccentOverlay valide, soit tu le laisses nul. "
    "reasoning explique quel patron correspond, ou pourquoi aucun ne "
    "s'applique (en français ou en anglais, peu importe — c'est un champ "
    "de traçabilité interne, jamais montré au spectateur)."
)


def _build_user_prompt(beat: Beat, essence: Essence, lang: str = "en") -> str:
    evidence = "\n".join(f"  - {e}" for e in essence.evidence)
    if lang == "fr":
        return (
            f"INDEX DU PLAN : {beat.idx}\n"
            f"RÔLE DU PLAN : {beat.role}\n"
            f"DURÉE CIBLE DU PLAN : {beat.target_duration_s:.2f}s "
            f"(clip Veo : {beat.veo_duration}s)\n"
            f"NARRATION DU PLAN (texte parlé, verbatim) :\n"
            f"  {beat.text!r}\n\n"
            f"MODE DE CONTENU : {essence.content_mode}\n"
            f"AFFIRMATION CENTRALE : {essence.core_claim}\n"
            f"PREUVES :\n{evidence}\n\n"
            f"Décide : ce plan mérite-t-il une surcouche éditoriale de "
            f"niveau 2 ?\n"
            f"Rappel : la plupart des plans doivent retourner "
            f"emit_overlay=false."
        )
    return (
        f"BEAT INDEX: {beat.idx}\n"
        f"BEAT ROLE: {beat.role}\n"
        f"BEAT TARGET DURATION: {beat.target_duration_s:.2f}s "
        f"(Veo clip: {beat.veo_duration}s)\n"
        f"BEAT NARRATION (verbatim of what's spoken):\n"
        f"  {beat.text!r}\n\n"
        f"CONTENT MODE: {essence.content_mode}\n"
        f"CORE CLAIM: {essence.core_claim}\n"
        f"EVIDENCE:\n{evidence}\n\n"
        f"Decide: does this beat warrant a Layer 2 editorial accent overlay?\n"
        f"Reminder: most beats should return emit_overlay=false."
    )


async def accent_for_beat(
    app: Any,
    beat: Beat,
    essence: Essence,
    lang: str = "",
) -> AccentOverlay | None:
    """Single `.ai()` call. Returns None by default — only emits an overlay
    when one of the 6 canonical patterns is genuinely warranted.

    `lang` ("fr"/"en") bascule la surcouche en français ; vide = repli sur
    REEL_AF_LANG (LANG_DEFAULT)."""
    resolved_lang = (lang or LANG_DEFAULT or "en").strip().lower()
    decision = await app.ai(
        system=_SYSTEM_PROMPT_FR if resolved_lang == "fr" else _SYSTEM_PROMPT,
        user=_build_user_prompt(beat, essence, resolved_lang),
        schema=_AccentDecision,
    )

    if not decision.emit_overlay or decision.overlay is None:
        return None

    overlay = decision.overlay

    # Enforce the hook_title_card → role=='hook' restriction defensively.
    # If the model selected hook_title_card on a non-hook beat, drop the
    # overlay rather than ship a frame-stealing title card mid-mechanism.
    if overlay.pattern == "hook_title_card" and beat.role != "hook":
        return None

    # Enforce position rule: hook_title_card lives upper_third, everything
    # else opposite the subtitles (lower_third). The schema already defaults
    # to lower_third; correct the upper-third case so it's consistent.
    if overlay.pattern == "hook_title_card":
        overlay = overlay.model_copy(update={"position": "upper_third"})
    elif overlay.position == "upper_third":
        overlay = overlay.model_copy(update={"position": "lower_third"})

    return overlay


async def plan_beat_accents(
    app: Any,
    beats: list[Beat],
    essence: Essence,
    lang: str = "",
) -> list[AccentOverlay | None]:
    """Fan-out via `asyncio.gather`. Returns list aligned to `beats` by index."""
    if not beats:
        return []
    return list(
        await asyncio.gather(
            *(accent_for_beat(app, beat, essence, lang) for beat in beats)
        )
    )
