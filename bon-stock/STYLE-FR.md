# Bon Stock — Style de narration française

*Direction créative pour la version FR du pipeline. Sert de référence aux consignes (system prompts) de `hook.py` et `compose.py` quand `REEL_AF_LANG=fr`. À citer/injecter dans ces consignes.*

## Registre

- **Français québécois naturel et soigné** : le ton d'un vulgarisateur québécois cultivé qui parle à son monde. Ni joual lourd, ni français de France guindé.
- **Tutoiement** systématique (« Savais-tu que… », « Imagine… », « Écoute ça »).
- **Oral, vivant, rythmé** — c'est de la **narration parlée** pour un reel de 25-30 s, pas un texte écrit. Une respiration = une phrase courte.

## Ton de marque (Bon Stock)

- Curieux, rigoureux, accessible. Vulgarisation de la science, l'industrie et la consommation du cannabis légal.
- **Accroche** qui arrête le pouce : *curiosity gap*, chiffre précis, fait contre-intuitif. En français, l'accroche reste **courte (≤ ~12 mots), concrète, une seule idée surprenante**.
- **Honnête** : pas de sensationnalisme trompeur ; le *payoff* tient la promesse de l'accroche et **boucle** avec elle.

## Ce qu'on FAIT

- Phrases **courtes et actives**.
- Chiffres et faits **concrets**, prononcés simplement (« 125 % », « trois fois moins », « 2,10 $ le gramme »).
- **Reformuler** en français idiomatique à partir de l'essence — même si l'article source est en anglais. On ne **calque jamais** la syntaxe anglaise.
- Vocabulaire cannabis en français clair (voir plus bas).

## Ce qu'on ÉVITE

- **Anglicismes inutiles** : *edibles* → **comestibles** · *vape/vaping* → **vapotage / vapoteuse** · *high* → **planer / l'effet** · *weed* → **cannabis / pot** (« pot » = familier québécois, OK) · *pre-roll* → **préroulé** · *strain* → **variété**.
- **Tournures trop hexagonales** : éviter « c'est ouf », « grave », « kiffer », « du coup » à répétition, « bah ». On veut du **québécois**, pas du parisien.
- Jargon lourd, phrases longues, ton **institutionnel / plate**.
- Traduction mot-à-mot depuis l'anglais.

## Micro-règles

- **Nombres/unités** en français (virgule décimale : « 2,10 $ », « 12,5 % »).
- **Noms propres, marques, sigles inchangés** : THC, CBD, SQDC, Santé Canada, INSPQ, noms de compagnies.
- **Accents** essentiels (é, è, à, ç, œ, …) — à vérifier au rendu karaoké.

## Exemples (avant ❌ → après ✅)

- ❌ « Savais-tu que les *edibles* peuvent te rendre *high* pendant 8 heures ? »
  ✅ « Savais-tu qu'un seul comestible peut te faire **planer 8 heures** ? »
- ❌ « Cette étude est vraiment ouf, du coup les chercheurs ont trouvé… »
  ✅ « **Écoute ça** : les chercheurs ont découvert quelque chose de surprenant. »
- ❌ (calque anglais) « Le cannabis a été montré pour réduire l'anxiété. »
  ✅ « Le cannabis **réduirait** l'anxiété — voici ce que dit l'étude. »

## Notes d'intégration (pour Claude Code)

- Seuls les *reasoners* qui produisent le **texte parlé** passent au français : **`hook.py` (pick_hook)** et **`compose.py`**. L'**extraction d'essence reste inchangée** (source multilingue → narration FR).
- Le **vocabulaire de scoring d'accroche** (hook.py / critic.py) doit rester **cohérent** une fois en français (hookability / spécificité).
- **Voix TTS** : les voix Gemini sont multilingues → même voix, texte français. Choisir/vérifier une voix qui **sonne naturelle en français** (accent, débit avec `atempo=1.35`).
- Mode **sujet** (hunters/narrator/judge) : plus tard. On commence par le **mode article**.
