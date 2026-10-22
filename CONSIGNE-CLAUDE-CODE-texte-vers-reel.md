# Consigne pour Claude Code — point d'entrée `text_to_reel` + interface

*À coller dans Claude Code (onglet Code), qui a l'accès direct à Docker/localhost.*
*L'interface `texte-vers-reel.html` existe déjà à la racine du dépôt — cette consigne ajoute la moitié moteur qui la rend fonctionnelle.*

## Objectif

Permettre de produire un reel à partir d'un **texte collé** (pas d'une URL), avec deux modes et un choix de style — via une page servie par le moteur.

## 1. Nouveau point d'entrée `text_to_reel` (dans `app.py`)

Ajouter un reasoner exposé sous `reel-af.reel_text_to_reel`, sur le modèle de `reel_article_to_reel`, prenant :

```json
{ "input": { "text": "...", "art_style": "style3", "mode": "brute", "lang": "fr" } }
```

- `text` — le texte collé par Luc (obligatoire).
- `art_style` — `"styleN"` ou `""` (comportement par défaut). Même sémantique que le 2e argument de `reel.sh`.
- `mode` — `"brute"` (défaut) ou `"verbatim"`.
- `lang` — `"fr"` (défaut Bon Stock) ou `"en"`. ✅ **Réglé (2026-07-05)** : `lang` est maintenant un paramètre PAR REEL transmis à travers tout le pipeline (`hook.py`/`compose.py`/`accent.py`/`tts.py`/`app.py`), avec repli sur `REEL_AF_LANG` (`.env`) si absent — même mécanique qu'`art_style`. Testé : un reel `lang="en"` explicite pendant que `.env` a `REEL_AF_LANG=fr`, sans redémarrer Docker.

**Comportement selon `mode` :**

- `mode == "brute"` → le `text` remplace l'« essence » : on **saute l'extraction** (pas d'URL), puis on fait tourner **`hook.py` (pick_hook)** et **`compose.py`** normalement à partir de ce texte. C'est le pipeline actuel privé de l'étape extract.
- `mode == "verbatim"` → on **saute `hook.py` et `compose.py`**. Le `text` devient directement le script parlé (le `ScriptDraft`/narration), qui part tel quel au **TTS**. Aucune réécriture. (Prévoir un léger nettoyage : découpe en phrases pour les timings karaoké, rien de plus.)

Le reste du pipeline (TTS → images selon `art_style` → montage `stitch.py` → auto-vérif) est **identique** dans les deux cas. Passer le verrou de sérialisation existant (`_REEL_RENDER_LOCK`) comme pour les autres entrées. Sortie dans `output/text-<id>/`.

## 2. Servir l'interface — via un PROXY sur l'agent reel-af (pas le control-plane)

**Mise à jour 2026-07-05, après vérification directe :** servir la page depuis le
control-plane lui-même (port 8090) n'est **pas réalisable**. Testé et confirmé :
le control-plane (`agentfield/control-plane:latest`) **refuse toute requête dont
l'en-tête `Origin` ne correspond pas exactement à `http://localhost:8090`** (403
sur tout le reste, y compris `Origin: null` comme une page `file://`) — une
politique stricte, pas du CORS configurable. C'est une image Docker verrouillée
(distroless : pas de shell, pas de `find`/`env`/`cat` ; `af server --help`
confirme une UI intégrée mais **aucune option pour y monter des fichiers
statiques personnalisés**). Donc pas de piste de configuration à creuser ici —
c'est fermé par conception.

**Solution retenue : un petit proxy côté agent reel-af** (port 8092 — notre
code, pas verrouillé). Le SDK `Agent` expose déjà `.mount()` / `.get()` /
`.post()` / `.add_route()` (vérifié via introspection : mêmes méthodes qu'un
framework web standard type FastAPI/Starlette).

Dans `app.py` :

1. **Servir les fichiers statiques** — `app.mount("/styles", StaticFiles(directory="styles"), name="styles")` et une route `GET /texte` qui renvoie `texte-vers-reel.html`.
2. **Route proxy** — `POST /api/reel-af/execute/{reasoner}` (ou nom similaire) sur l'agent lui-même : reçoit la requête du navigateur (même origine que la page, donc **aucune restriction CORS** — il n'y a jamais de requête cross-origin côté navigateur), puis **relaie côté serveur** (`httpx`/`aiohttp`, PAS `fetch()` du navigateur) vers `http://localhost:8090/api/v1/execute/async/reel-af.{reasoner}`. Un appel serveur-à-serveur n'est **jamais soumis au CORS** (c'est une règle du navigateur, pas du serveur) — d'où l'absence totale de blocage. Renvoie la réponse JSON du control-plane telle quelle au navigateur.
3. **Adapter `texte-vers-reel.html`** pour appeler ce nouveau chemin proxy (même origine que la page, ex. `fetch('/api/reel-af/execute/text_to_reel', …)`) au lieu de l'URL directe du control-plane.

Avantage sur l'idée d'origine : ne dépend d'aucune modification de l'image
verrouillée du control-plane, et garde toute la fonctionnalité (lire
l'`execution_id`, afficher la progression dans la page) — pas de compromis
*fire-and-forget*.

- Vérifier que le POST async (relayé par le proxy) accepte bien ce nouveau reasoner comme les autres (`reel_article_to_reel`, `reel_topic_to_reel`).

## 3. Vignettes d'exemple par style (pour l'interface)

L'interface cherche une image `styles/styleN.jpg` par style (servie à côté de la page) ; si absente, elle retombe sur un aplat de palette.

- **Déjà fait** : 9 vignettes réelles sont déjà dans `styles/` (`style1.jpg`…`style6.jpg`, `style8.jpg`, `style9.jpg`, `style10.jpg`), extraites de vrais reels produits (une frame représentative par style). **Il faut donc servir le dossier `styles/` à côté de la page** (même origine, chemin relatif `styles/styleN.jpg`).
- **Manque `style7.jpg`** (réalisme peint chaleureux, façon couverture de magazine mi-siècle — *confirmé par Luc : la référence est l'Americana peinte type Rockwell, décrite par ses traits dans le preset, jamais par le nom de l'artiste*). Aucun reel produit ne l'illustrait (le rendu ressemble à une photo, donc pas repérable dans le lot). **À faire : générer une frame témoin** en passant `art_style=style7` sur un sujet Bon Stock chaleureux et humain — suggestion : **« deux amis qui partagent un préroulé sur un perron en fin d'après-midi, lumière dorée, sourires complices »**. Extraire une belle frame et la déposer en `styles/style7.jpg`. (Le fallback actuel de l'interface = aplat de palette ambre/rouge/vert, correct en attendant.)
- Optionnel : une petite commande `make-style-thumbs` qui régénère une vignette par preset (utile si un preset change).

## 4. Test de bout en bout

1. `docker compose restart reel-af` suffit — mode dev, `app.py` fait partie de `src/` monté en direct, pas de reconstruction nécessaire même pour la nouvelle route.
2. Ouvrir **`http://localhost:8092/texte`** (agent reel-af, pas le control-plane — voir point 2 mis à jour).
3. Coller un court texte, **mode brute**, cocher `style3` → vérifier `output/text-<id>/reel.mp4`.
4. Même texte, **mode verbatim** → vérifier que la narration **lit le texte tel quel** (pas de réécriture d'accroche).
5. Cocher 2 styles → 2 reels à la file.

## Notes / pièges (rappel)

- Ne PAS lancer git dans le dépôt monté depuis Cowork — Luc committe depuis SON Terminal.
- `mode verbatim` : bien court-circuiter `pick_hook` **et** `compose_script`, sinon le texte sera réécrit.
- `art_style` vide = comportement par défaut (ne pas forcer un preset).
- Garder `REEL_AF_LANG` cohérent : `lang` du POST peut surcharger le défaut `.env` pour ce reel précis.
