# Consigne Claude Code — styles depuis un mood board (distillation)

*À coller dans Claude Code (accès Docker/localhost). Objectif : dans `/texte`, Luc téléverse une série d'images → elles deviennent automatiquement une nouvelle variation de style dans la grille.*

## Idée directrice

Un « style » dans reels-af n'est pas une image, c'est une **description de traits visuels** (le prompt anglais de `_ART_STYLE_PRESETS`, ajouté à chaque plan par `_augment`) + sa méta FR (`STYLE_UI_META`) + une vignette. Un mood board = **une façon de générer cette description à partir d'images** au lieu de l'écrire à la main. Un modèle de vision distille les images en un preset au format exact du pipeline. (La **référence visuelle directe** — passer les images au modèle d'image à chaque rendu — est explicitement remise à une **v2**.)

## Contrainte d'architecture (importante)

`_ART_STYLE_PRESETS`, `STYLE_UI_META` (dans `render/images.py`) et le dossier `styles/` sont **cuits dans l'image Docker**. Un style ajouté au runtime doit donc vivre dans un dossier **monté en direct et inscriptible** pour persister sans reconstruction. On utilise **`bon-stock/`** (déjà monté live).

Nouveau store : **`bon-stock/styles-custom/<id>/`** contenant
- `refs/` — les images téléversées (brutes),
- `thumb.jpg` — vignette (collage des refs),
- `preset.json` — `{ "id", "english_prompt", "nom", "bon", "pal": [...], "desc" }`.

`<id>` = `mb-<slug-court>` (préfixe `mb-` pour ne jamais entrer en collision avec `style1..N` built-in ni les futurs).

## 1. Fusion built-in + custom (le cœur)

Deux points de lecture doivent fusionner les presets custom :

**a) Génération** — `render/images.py`, `_style_note()` : si `art_style` n'est pas dans `_ART_STYLE_PRESETS`, chercher `bon-stock/styles-custom/<art_style>/preset.json` et retourner son `english_prompt`. (Ajouter un petit helper `_custom_preset(id) -> dict | None` avec lecture tolérante + cache léger optionnel.)

**b) Interface** — `app.py`, `_presets()` : après les styles built-in, parcourir `bon-stock/styles-custom/*/preset.json` et ajouter chaque entrée à la liste `styles`, en incluant un champ **`thumb`** = URL servie (voir §3). Les built-in gardent `thumb` absent (l'UI retombe sur `styles/<id>.jpg`).

## 2. Route d'upload + distillation

Nouvelle route sur CET agent (même origine que `/texte`, donc **aucun CORS**) :

`POST /api/reel-af/moodboard` (multipart) — champs : `nom` (texte, optionnel), `images` (1..N fichiers).

Traitement :
1. Générer `<id>`, créer `bon-stock/styles-custom/<id>/refs/`, y sauver les images (valider type image, limiter taille/nombre — ex. max 8, 10 Mo chacune).
2. **Distillation** : appeler un modèle de **vision** (le modèle de raisonnement courant `REEL_AF_MODEL` = `openrouter/anthropic/claude-sonnet-5.5` supporte la vision) avec les images en entrée + le system prompt du §4. ⚠️ Vérifier le chemin multimodal **entrée image** du `OpenRouterProvider` (il a déjà `generate_image` pour la SORTIE ; pour l'ENTRÉE image, c'est l'appel chat/vision — inspecter le provider et utiliser le bon format de `messages` avec `image_url`/base64). Parser le JSON strict renvoyé.
3. **Palette** : ne pas se fier au modèle pour les hex. Extraire 3-5 couleurs dominantes des images avec **PIL** (ex. `Image.quantize(colors=5)` sur une mosaïque réduite des refs) → liste `pal` de hex. Plus fiable et déterministe.
4. **Vignette** : collage des refs avec **PIL** (déjà une dépendance), recadré vertical ~440 px de large (cohérent avec les vignettes existantes), écrit en `thumb.jpg`.
5. Écrire `preset.json`. Répondre `{ "id": "...", "nom": "...", ... }` (200) ou une erreur lisible (422/500) que l'UI affiche.

Sérialisation : la distillation est un appel court, pas un rendu de reel — **ne pas** prendre le verrou `_REEL_RENDER_LOCK` (sinon elle attendrait derrière un reel en cours). C'est indépendant.

## 3. Servir les vignettes custom

`styles/` est monté sur `/styles`. Pour les refs/thumbs custom, ajouter un **second mount statique** sur le dossier custom, p. ex. :

```python
_CUSTOM_DIR = _PROJECT_ROOT / "bon-stock" / "styles-custom"
_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/styles-custom", StaticFiles(directory=str(_CUSTOM_DIR)), name="styles-custom")
```

Dans `preset.json` / `_presets()`, `thumb` = `"/styles-custom/<id>/thumb.jpg"`.

## 4. System prompt de distillation (le cœur créatif — à utiliser tel quel)

> Tu es directeur artistique pour **Bon Stock**, un média québécois sur le cannabis légal. On te donne un **mood board** : plusieurs images de référence. Distille-les en **UN seul preset de style visuel réutilisable**.
>
> Observe ce que les images ont en **COMMUN** : technique (photo, peinture à l'huile, aquarelle, vecteur plat, collage, sérigraphie…), traitement des contours, texture et grain, palette, éclairage, niveau d'abstraction, ambiance. **Ignore le sujet précis** de chaque image — on appliquera ce style à d'autres sujets. Ne capture que le **LOOK**.
>
> Réponds en **JSON strict**, rien d'autre :
> ```json
> {
>   "english_prompt": "<60-90 mots, EN ANGLAIS, décrivant les traits visuels : technique, contours, texture, palette, éclairage, ambiance, PLUS les exclusions pertinentes (no photorealism / no gradients / no outlines / etc. selon le cas). NE NOMME JAMAIS un artiste, studio, marque ou œuvre — décris les traits, car les modèles d'image édulcorent ou refusent les noms propres. Termine OBLIGATOIREMENT par : VERTICAL portrait composition (taller than wide, subject occupies the upper-middle two-thirds), fills the frame, no text or letters>",
>   "nom": "<nom court FR du style, 2-4 mots>",
>   "bon": "<\"bon pour…\" : 3-5 mots sur l'usage ou l'émotion>",
>   "desc": "<1 phrase FR décrivant le style>"
> }
> ```
>
> Exemple du format attendu pour `english_prompt` (style existant, à titre de gabarit, ne pas copier) : « bold pop-art comic illustration, thick black ink outlines around every shape, flat unshaded colors filled with visible Ben-Day dot halftone, a limited bright primary palette of red, yellow, blue, black and white, high-contrast comic-book framing, no photorealism, no gradients, no soft shading; VERTICAL portrait composition (taller than wide, subject occupies the upper-middle two-thirds), fills the frame, no text or letters ».

Note : le `english_prompt` doit rester **cohérent avec le reste du pipeline** — c'est lui qui est ajouté à chaque prompt de plan. La clause verticale/no-text finale est **obligatoire** (contrainte technique de tout preset).

## 5. Interface `texte-vers-reel.html` (ajout minimal)

Sous la grille de styles, ajouter un bloc **« + Nouveau style depuis un mood board »** :
- `<input type="file" multiple accept="image/*">` + un champ nom (optionnel) + bouton **« Distiller le style »**.
- Au clic : `FormData` → `POST /api/reel-af/moodboard` (même origine). Pendant le traitement, afficher un état « Distillation en cours… » (c'est un appel vision de quelques secondes).
- Au succès : re-`fetch('/api/reel-af/presets')` et re-render la grille → le nouveau style apparaît (vignette = collage), **sélectionnable immédiatement** comme les autres.

Adapter le rendu d'une carte de style pour les customs : le badge numéroté actuel fait `s.id.replace('style','')` — pour un id `mb-...`, afficher plutôt une petite icône/🎨 ou rien, et utiliser `s.thumb` si présent, sinon le repli `styles/<id>.jpg`. (Rappel **piège dur #8** : `texte-vers-reel.html` est monté en **fichier unique** → après modif, `docker compose restart reel-af` pour resynchroniser ; vérifier `curl -sSI http://localhost:8092/texte`.)

## 6. Test de bout en bout

1. `docker compose restart reel-af` (modifs `src/` en mode dev ; pas de rebuild sauf nouvelle dépendance).
2. Ouvrir `http://localhost:8092/texte`.
3. Téléverser 3-5 images cohérentes (ex. un mood board « néon nocturne »), nommer, distiller.
4. Vérifier : nouvelle carte dans la grille (vignette collage), `bon-stock/styles-custom/<id>/preset.json` bien formé, `english_prompt` finissant par la clause verticale et **sans nom d'artiste**.
5. Lancer un reel avec ce style (mode texte, cocher la nouvelle variation) → confirmer que `output/text-<id>/` applique bien le look.
6. `restart` → la variation **persiste** (store monté), preuve que rien n'était cuit dans l'image.

## Pièges / rappels

- **Ne pas** committer d'images lourdes : `bon-stock/styles-custom/` peut grossir — l'ajouter à `.gitignore` (ou au moins `refs/`).
- Pas de nom d'artiste dans `english_prompt` (le modèle de vision doit décrire les traits — c'est dans le system prompt, mais revérifier au test).
- Validation upload : type image réel, taille/nombre bornés (éviter qu'un PDF ou un énorme fichier passe).
- git : préparer les commandes pour le Terminal de Luc (ne pas lancer git dans le dépôt monté).
- v2 éventuelle (si le rendu manque de fidélité) : passer 1-2 refs au modèle d'**image** comme référence de look à chaque plan — à évaluer selon le support d'`image_url` en entrée du modèle Gemini Image.
