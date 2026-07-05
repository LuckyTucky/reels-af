"""Essence → ScriptDraft in ONE .ai() call.

Fixed structure: Hook (6-10 words) → Mechanism (2-4 sentences) → Payoff
(1 sentence ending on a loop-back keyword from the hook). The schema's
``_loop_back_check`` validator (in ``reel_af.models``) is the safety net;
the prompt teaches the model to satisfy it on the first try.
"""

from __future__ import annotations

import os
from typing import Any

from reel_af.models import Essence, HookCandidate, ScriptDraft

# REEL_AF_LANG=fr bascule ce module en français québécois (voir
# bon-stock/STYLE-FR.md). extract.py reste inchangé (multilingue, source
# → essence peu importe la langue de l'article). Lu une fois au chargement
# du module — interrupteur de projet, pas un réglage par reel.
LANG = (os.getenv("REEL_AF_LANG") or "en").strip().lower()

# ────────────────────────────────────────────────────────────────────
# Scientific-mode writing guide. Applied when essence.content_mode ==
# "scientific" — research papers / preprints / technical writeups read
# by engineers and the technically-literate public.
# ────────────────────────────────────────────────────────────────────
SCIENTIFIC_WRITING_GUIDE = """\
═══════════════════════════════════════════════════════════════════════════
WRITING GUIDE FOR SCIENTIFIC PAPERS — TECHNICAL AUDIENCE
═══════════════════════════════════════════════════════════════════════════

You are writing a vertical reel about a research paper for an audience of
ENGINEERS and the TECHNICALLY-LITERATE PUBLIC. They know what a transformer
is, what gradient descent does, what a benchmark is. They do NOT need
"what is AI" explained. They DO need any acronym or method name introduced
in the paper itself defined inline.

These are principles. Pick the shape that fits the specific paper.

──────────────────────────────────────────────────────────────────────────
PRINCIPLE 1 — LEAD WITH THE RESULT
──────────────────────────────────────────────────────────────────────────
A scientific paper's viral payload is almost always a NUMBER or a CLAIM
demonstrated against a baseline. Open with it.

Bad opener: "Researchers have published a new paper on alignment."
Good opener: "70% jailbreak rate — even after RLHF. Anthropic just showed
              alignment doesn't survive scale."

If the result is qualitative ("we discovered a new failure mode"), still
state the CLAIM up front, not the methodology.

──────────────────────────────────────────────────────────────────────────
PRINCIPLE 2 — USE FIELD JARGON FREELY; DEFINE PAPER-SPECIFIC TERMS
──────────────────────────────────────────────────────────────────────────
The audience already knows: transformer, attention, embedding, gradient,
token, fine-tuning, RL, RLHF, benchmark, parameters, MMLU, HumanEval,
GSM8K. Don't waste a beat defining these.

The audience does NOT know paper-specific things: "we call this BTSP",
"the IM-RoPE rotary scheme", "what we term 'sleeper alignment'". Define
these inline in 5-8 words the FIRST time you use them.

──────────────────────────────────────────────────────────────────────────
PRINCIPLE 3 — SHOW THE INTUITION, NOT THE MATH
──────────────────────────────────────────────────────────────────────────
A paper's actual contribution is usually a clever IDEA dressed in
notation. Translate the idea into one sentence of intuition, then drop
the math name as the label.

──────────────────────────────────────────────────────────────────────────
PRINCIPLE 4 — ACKNOWLEDGE THE BASELINE BRIEFLY
──────────────────────────────────────────────────────────────────────────
Numbers without comparison are noise. "70% accuracy" means nothing
unless you say "vs 40% for the prior SOTA". Always couple a headline
number with what came before. One sentence is enough.

──────────────────────────────────────────────────────────────────────────
PRINCIPLE 5 — CLOSE ON "WHAT DOES THIS ENABLE / BREAK"
──────────────────────────────────────────────────────────────────────────
The close shouldn't be a recap — it should state the consequence. Either
the new thing this unlocks ("this means smaller models can now do X") or
the old assumption this breaks ("this means we were wrong about Y").

══════════════════════════════════════════════════════════════════════════
"""

# Variante FR du guide scientifique — mêmes 5 principes, adaptés au
# registre STYLE-FR.md (québécois, tutoiement, reformulé).
SCIENTIFIC_WRITING_GUIDE_FR = """\
═══════════════════════════════════════════════════════════════════════════
GUIDE DE RÉDACTION — ARTICLES SCIENTIFIQUES, PUBLIC TECHNIQUE
═══════════════════════════════════════════════════════════════════════════

Tu écris la narration d'un reel vertical sur un article scientifique, pour
un public d'ingénieurs et de gens techniquement litttéré. Ils savent ce
qu'est un transformer, la descente de gradient, un benchmark. Pas besoin de
leur expliquer « c'est quoi l'IA ». Par contre, tout acronyme ou nom de
méthode propre à l'article doit être défini en une incise.

Ce sont des principes — choisis la forme qui convient à l'article.

──────────────────────────────────────────────────────────────────────────
PRINCIPE 1 — COMMENCE PAR LE RÉSULTAT
──────────────────────────────────────────────────────────────────────────
Le payload viral d'un article scientifique, c'est presque toujours un
CHIFFRE ou une AFFIRMATION démontrée contre une base de comparaison. Ouvre
là-dessus.

Mauvaise ouverture : « Des chercheurs ont publié une étude sur… »
Bonne ouverture : « 70 % de taux de contournement — même après
                    entraînement de sécurité. »

Si le résultat est qualitatif, énonce quand même l'AFFIRMATION en premier,
pas la méthodologie.

──────────────────────────────────────────────────────────────────────────
PRINCIPE 2 — UTILISE LE JARGON DU DOMAINE LIBREMENT ; DÉFINIS CE QUI EST
PROPRE À L'ÉTUDE
──────────────────────────────────────────────────────────────────────────
Le public connaît déjà : cannabinoïde, THC, CBD, endocannabinoïde,
récepteur, essai clinique, cohorte, dose-réponse. Pas besoin de perdre du
temps à définir ça.

Le public ne connaît PAS les termes propres à l'étude elle-même. Définis-
les en 5-8 mots à la première utilisation.

──────────────────────────────────────────────────────────────────────────
PRINCIPE 3 — MONTRE L'INTUITION, PAS LES MATHS/LA MÉTHODO DÉTAILLÉE
──────────────────────────────────────────────────────────────────────────
La vraie contribution d'une étude, c'est souvent une idée simple habillée
de jargon. Traduis l'idée en une phrase d'intuition, puis nomme le concept
comme étiquette.

──────────────────────────────────────────────────────────────────────────
PRINCIPE 4 — RECONNAIS LA BASE DE COMPARAISON BRIÈVEMENT
──────────────────────────────────────────────────────────────────────────
Un chiffre sans comparaison, c'est du bruit. « 70 % » ne veut rien dire
sans « contre 40 % avant ». Couple toujours un chiffre-choc avec ce qui
existait avant. Une phrase suffit.

──────────────────────────────────────────────────────────────────────────
PRINCIPE 5 — TERMINE SUR « QU'EST-CE QUE ÇA CHANGE »
──────────────────────────────────────────────────────────────────────────
La fin ne doit pas être un récapitulatif — elle doit énoncer la
conséquence. Soit ce que ça débloque, soit l'idée reçue que ça brise.

══════════════════════════════════════════════════════════════════════════
"""


# ────────────────────────────────────────────────────────────────────
# Tag vocabulary — DELIBERATELY MINIMAL for fast, engaging delivery.
# Gemini honors pause tags with real silence, so more than ~3 tags
# pushes the reel past the 25-second engagement budget. We allow ≤3
# tags total and explicitly ban pause / slow / breath.
# ────────────────────────────────────────────────────────────────────
_TAG_VOCAB = """\
  ALLOWED (use ≤3 total across the whole narration):
    • [curious]   — at the cold open, ONCE
    • [emphasis]  — on the single most surprising word, ONCE
    • [confident] — at the payoff, ONCE (optional)

  BANNED — do NOT use any of these. They insert real silence and
  blow the engagement budget:
    • [pause] [pause short] [pause long] [breath]
    • [slow] [building] [thoughtful] [wonder] [skeptical]
    • [serious] [warm] [whispers] [quiet] [intense] [hopeful]
    • Any other tag that slows delivery

  Trust the punctuation (commas, em-dashes, periods) for rhythm.
  Trust the model's default cadence. Less is more.
"""


def _system_prompt(
    content_mode: str, chosen_hook: HookCandidate | None = None,
) -> str:
    if content_mode == "scientific":
        word_target = "45-52 words"
        wpm = 175
        register = (
            "TECHNICAL register. Audience is engineers and the technically-"
            "literate public. Use field jargon freely. Define only paper-"
            "specific terms inline in 5-8 words on first use."
        )
        hook_menu = (
            "For scientific content prefer `authority` or `shock_stat`. "
            "`curiosity_gap` works if the result is genuinely surprising."
        )
        mode_block = (
            "\n──── SCIENTIFIC WRITING GUIDE (applies to the WHOLE script) ────\n"
            f"{SCIENTIFIC_WRITING_GUIDE}\n"
        )
    else:  # general
        word_target = "55-62 words"
        wpm = 180
        register = (
            "CONVERSATIONAL register. Audience is general scrolling viewers. "
            "Plain language; second person where natural. No jargon without "
            "a one-clause translation. TIGHT sentences — no padding."
        )
        hook_menu = (
            "For general content prefer `shock_stat`, `contrarian`, or "
            "`curiosity_gap`. `listicle` only if the article is structurally "
            "a list. `authority` only if the source's expert is the story."
        )
        mode_block = ""

    if chosen_hook is not None:
        hook_block = f"""  1. HOOK (FIXED — already chosen upstream, do not rewrite it)
                       text         : "{chosen_hook.text}"
                       hook_variant : {chosen_hook.hook_variant}
                       Copy this hook VERBATIM into the `hook` and
                       `hook_variant` fields. Do not paraphrase it, do not
                       improve it, do not change a single word. Your job
                       starts at step 2 — write the mechanism/payoff that
                       best supports THIS hook."""
    else:
        hook_block = f"""  1. HOOK            — 6-10 spoken words. Picks ONE variant from:
                       shock_stat | contrarian | authority | curiosity_gap | listicle
                       Declare which variant you chose in `hook_variant`.
                       {hook_menu}"""

    return f"""You are writing a 25-second vertical reel narration.

The structure is FIXED. Do not deviate.

{hook_block}

  2. MECHANISM       — 2-4 sentences that explain the WHY behind the hook.
                       Each sentence is a coherent visual beat downstream
                       (one shot per sentence), so each must stand alone.
                       Names, numbers, specific things — not vibes.

  3. PAYOFF + LOOP   — 1 closing sentence. The last 4-8 words MUST echo a
                       distinctive word from your HOOK: a noun, a number,
                       or a named entity — NOT a stopword (not "the", "and",
                       "that", "this", "you"). This is how the viewer loops
                       back to the start. The schema validator checks this
                       literally; if you skip it the call fails.

REGISTER: {register}

TOTAL LENGTH: {word_target}. Set `target_wpm` to {wpm}. The reel lands
at ~20-22s. FAST delivery — every pause is attention you've lost.

──── INLINE TTS TAGS — STRICTLY LIMITED ────
The `narration` field is passed VERBATIM to Gemini 3.1 Flash TTS. Tags
go in [square brackets] BEFORE the clause they modify. Gemini interprets
pause tags as REAL SILENCE — so we ban them.

{_TAG_VOCAB}

PUNCTUATION DISCIPLINE: each comma is ~200ms of silence, em-dash ~300ms,
period ~400ms. If your narration has more than ~5 commas across the
{word_target}, you're slowing it down on purpose. Tighten.

──── ANTI-PATTERNS — instant rejection ────
  • "Hey guys", "Did you know", "In this video", "Today we…"
  • "Thanks for watching", "Don't forget to like", "Smash that subscribe"
  • Generic CTAs ("Follow for more", "Comment below").
  • Fade-out closes that trail into nothing.
  • Hedges in the close ("kind of", "sort of", "might be", "maybe").
  • Padding the word count with filler — tight is better than long.
  • Inventing facts, names, or numbers not in the essence below.

──── OUTPUT FIELDS ────
  hook              : the literal first 6-10 spoken words, punctuated.
  hook_variant      : which canonical shape — for the audit trail.
  mechanism_lines   : list of 2-4 sentences (no leading bullets).
  payoff_line       : the closing sentence, with the loop-back keyword.
  target_wpm        : {wpm}.
  narration         : hook + mechanism + payoff concatenated as ONE string,
                      with inline [tags] inserted. Same words, same order,
                      same punctuation as the structured fields — only tags
                      added. This string is what TTS speaks.
{mode_block}"""


def _user_prompt(
    essence: Essence, chosen_hook: HookCandidate | None = None,
) -> str:
    """Mirror arch_b_hook_first._body_from_hook's user payload shape, sourced
    from Essence instead of ArticleSummary."""
    evidence_block = "\n".join(
        f"    {i + 1}. {e}" for i, e in enumerate(essence.evidence)
    )
    closing = (
        f'Write the ScriptDraft now. The hook is ALREADY CHOSEN: '
        f'"{chosen_hook.text}" ({chosen_hook.hook_variant}) — copy it '
        f"verbatim into `hook`/`hook_variant`. Build the mechanism_lines "
        f"and payoff_line around it using the evidence above; the "
        f"payoff_line lands on a word that callbacks the hook."
        if chosen_hook is not None else
        "Write the ScriptDraft now. The hook draws from `core_claim`; the "
        "mechanism_lines unpack `mechanism` using the evidence above; the "
        "payoff_line lands on a word that callbacks the hook."
    )
    return (
        f"ESSENCE (from the source article — use these facts, invent nothing)\n"
        f"  content_mode : {essence.content_mode}\n"
        f"  domain       : {essence.domain}\n"
        f"  core_claim   : {essence.core_claim}\n"
        f"  mechanism    : {essence.mechanism}\n"
        f"  evidence:\n"
        f"{evidence_block}\n\n"
        f"{closing}"
    )


def _system_prompt_fr(
    content_mode: str, chosen_hook: HookCandidate | None = None,
) -> str:
    """Variante FR — voir bon-stock/STYLE-FR.md. Même structure fixe et
    mêmes cibles numériques (mots/wpm) que _system_prompt ; le registre,
    les anti-patterns et le vocabulaire à éviter sont adaptés au français
    québécois plutôt que traduits mot à mot."""
    if content_mode == "scientific":
        word_target = "45-52 mots"
        wpm = 175
        register = (
            "REGISTRE TECHNIQUE. Public d'ingénieurs et de gens "
            "technique-litttéré. Utilise le jargon du domaine librement. "
            "Ne définis que les termes propres à l'étude, en 5-8 mots à "
            "la première utilisation."
        )
        hook_menu = (
            "Pour du contenu scientifique, préfère `authority` ou "
            "`shock_stat`. `curiosity_gap` marche si le résultat est "
            "vraiment surprenant."
        )
        mode_block = (
            "\n──── GUIDE SCIENTIFIQUE (s'applique à TOUT le script) ────\n"
            f"{SCIENTIFIC_WRITING_GUIDE_FR}\n"
        )
    else:  # general
        word_target = "55-62 mots"
        wpm = 180
        register = (
            "REGISTRE CONVERSATIONNEL — français québécois naturel et "
            "soigné (ni joual lourd, ni français de France guindé), "
            "tutoiement systématique (« Savais-tu que… », « Écoute ça »). "
            "REFORMULE l'essence en français idiomatique — ne calque "
            "JAMAIS la syntaxe anglaise, même si l'essence vient d'un "
            "article en anglais. Phrases COURTES et actives — pas de "
            "remplissage."
        )
        hook_menu = (
            "Pour du contenu général, préfère `shock_stat`, `contrarian`, "
            "ou `curiosity_gap`. `listicle` seulement si l'article est "
            "structurellement une liste. `authority` seulement si "
            "l'expert de la source EST l'histoire."
        )
        mode_block = ""

    if chosen_hook is not None:
        hook_block = f"""  1. ACCROCHE (FIXÉE — déjà choisie en amont, ne pas la réécrire)
                       texte        : "{chosen_hook.text}"
                       hook_variant : {chosen_hook.hook_variant}
                       Recopie cette accroche TELLE QUELLE dans les champs
                       `hook` et `hook_variant`. Ne la paraphrase pas, ne
                       l'améliore pas, ne change pas un seul mot. Ton
                       travail commence à l'étape 2 — écris le mécanisme/
                       payoff qui soutient le mieux CETTE accroche."""
    else:
        hook_block = f"""  1. ACCROCHE        — 6-12 mots parlés. Choisis UNE variante parmi :
                       shock_stat | contrarian | authority | curiosity_gap | listicle
                       Déclare la variante choisie dans `hook_variant`.
                       {hook_menu}"""

    return f"""Tu écris la narration d'un reel vertical de 25 secondes.

La structure est FIXE. Ne dévie pas.

{hook_block}

  2. MÉCANISME       — 2-4 phrases qui expliquent le POURQUOI derrière
                       l'accroche. Chaque phrase est un plan visuel
                       cohérent en aval (un plan par phrase), donc chacune
                       doit se tenir seule. Des noms, des chiffres, des
                       faits précis — pas de vibe.

  3. PAYOFF + BOUCLE — 1 phrase de clôture. Les 4-8 derniers mots DOIVENT
                       faire écho à un mot distinctif de ton ACCROCHE : un
                       nom, un chiffre, ou une entité nommée — PAS un mot
                       vide (pas « le », « la », « et », « ça », « tu »).
                       C'est ainsi que le spectateur boucle vers le début.
                       Le validateur du schéma vérifie ça littéralement ;
                       si tu sautes cette étape, l'appel échoue.

REGISTRE : {register}

──── ACCORDS — RELIS AVANT DE RÉPONDRE ────
Le français a des pièges de genre fréquents. Avant de finaliser, vérifie
que CHAQUE adjectif s'accorde en genre ET en nombre avec le nom qu'il
qualifie — pas avec le nom le plus proche dans la phrase.
  • « souvenir » est MASCULIN : un souvenir, des souvenirs fictifs
    (PAS « fictives »).
  • « mémoire » (la faculté/l'organe) est FÉMININ : une mémoire fragile ;
    mais « un mémoire » (rapport, thèse) est masculin.
  • Autres pièges courants : un(e) effet/étude/résultat, un problème,
    une donnée, un(e) enzyme, un(e) hippocampe (masculin).
Si tu hésites sur le genre d'un nom, reformule pour l'éviter plutôt que
de deviner.

LONGUEUR TOTALE : {word_target}. Mets `target_wpm` à {wpm}. Le reel dure
~20-22s. Débit RAPIDE — chaque pause est de l'attention perdue.

──── BALISES TTS EN LIGNE — STRICTEMENT LIMITÉES ────
Le champ `narration` est passé TEL QUEL à Gemini 3.1 Flash TTS. Les balises
vont entre [crochets] AVANT la clause qu'elles modifient. Gemini interprète
les balises de pause comme du VRAI SILENCE — on les bannit donc.

{_TAG_VOCAB}

DISCIPLINE DE PONCTUATION : chaque virgule = ~200ms de silence, tiret
cadratin ~300ms, point ~400ms. Si ta narration a plus de ~5 virgules sur
{word_target}, tu ralentis exprès. Resserre.

──── ANTI-PATTERNS — rejet immédiat ────
  • « Salut tout le monde », « Savais-tu que » en ouverture générique,
    « Dans cette vidéo », « Aujourd'hui on… »
  • « Merci d'avoir regardé », « Oublie pas de t'abonner »
  • Appels à l'action génériques (« Suis-moi pour plus », « Commente en bas »).
  • Fins en fondu qui traînent dans le vide.
  • Anglicismes évitables (voir bon-stock/STYLE-FR.md : edibles→comestibles,
    vape/vaping→vapotage, high→planer/l'effet, weed→cannabis/pot,
    pre-roll→préroulé, strain→variété).
  • Tournures trop hexagonales (« c'est ouf », « grave », « kiffer »,
    « du coup », « bah »).
  • Calque syntaxique de l'anglais (traduction mot à mot).
  • Hedges dans la clôture (« genre », « un peu », « peut-être »).
  • Remplir le compte de mots avec du remplissage — serré vaut mieux que long.
  • Inventer des faits, noms, ou chiffres absents de l'essence ci-dessous.

──── CHAMPS DE SORTIE ────
  hook              : les 6-12 premiers mots parlés, ponctués, en français.
  hook_variant      : quelle forme canonique — pour la traçabilité (garde
                      les clés anglaises : shock_stat, contrarian, etc.).
  mechanism_lines   : liste de 2-4 phrases (sans puces en tête).
  payoff_line       : la phrase de clôture, avec le mot de bouclage.
  target_wpm        : {wpm}.
  narration         : accroche + mécanisme + payoff concaténés en UNE
                      chaîne, avec les [balises] insérées. Mêmes mots,
                      même ordre, même ponctuation que les champs
                      structurés — seules les balises sont ajoutées.
                      C'est cette chaîne que la voix synthétique dit.
{mode_block}"""


def _user_prompt_fr(
    essence: Essence, chosen_hook: HookCandidate | None = None,
) -> str:
    evidence_block = "\n".join(
        f"    {i + 1}. {e}" for i, e in enumerate(essence.evidence)
    )
    closing = (
        f'Écris le ScriptDraft maintenant. L\'accroche est DÉJÀ CHOISIE : '
        f'"{chosen_hook.text}" ({chosen_hook.hook_variant}) — recopie-la '
        f"telle quelle dans `hook`/`hook_variant`. Construis les "
        f"mechanism_lines et le payoff_line autour, en utilisant les "
        f"preuves ci-dessus ; le payoff_line se termine sur un mot qui "
        f"boucle avec l'accroche."
        if chosen_hook is not None else
        "Écris le ScriptDraft maintenant. L'accroche part de `core_claim` ; "
        "les mechanism_lines déploient `mechanism` avec les preuves "
        "ci-dessus ; le payoff_line se termine sur un mot qui boucle avec "
        "l'accroche."
    )
    return (
        f"ESSENCE (de l'article source — utilise ces faits, n'invente rien)\n"
        f"  content_mode : {essence.content_mode}\n"
        f"  domain       : {essence.domain}\n"
        f"  core_claim   : {essence.core_claim}\n"
        f"  mechanism    : {essence.mechanism}\n"
        f"  evidence:\n"
        f"{evidence_block}\n\n"
        f"{closing}\n\n"
        f"Rappel : français québécois naturel, tutoiement, reformulé — "
        f"jamais calqué sur l'anglais, même si l'essence ci-dessus est "
        f"en anglais."
    )


async def compose_script(
    app: Any, essence: Essence, chosen_hook: HookCandidate | None = None,
) -> ScriptDraft:
    """One .ai() call. Fixed Hook -> Mechanism -> Payoff -> Loop structure.
    Parameterized by content_mode. Inline TTS tags in the narration.

    If chosen_hook is given (from agents/hook.py's best-of-N selection),
    the hook is FIXED and this call only writes mechanism/payoff around it.

    REEL_AF_LANG=fr bascule vers la variante française complète (voir
    _system_prompt_fr / _user_prompt_fr, bon-stock/STYLE-FR.md)."""
    if LANG == "fr":
        return await app.ai(
            system=_system_prompt_fr(essence.content_mode, chosen_hook),
            user=_user_prompt_fr(essence, chosen_hook),
            schema=ScriptDraft,
        )
    return await app.ai(
        system=_system_prompt(essence.content_mode, chosen_hook),
        user=_user_prompt(essence, chosen_hook),
        schema=ScriptDraft,
    )
