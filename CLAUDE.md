# CLAUDE.md — brief du projet reels-af / Bon Stock

*Contexte pour toute session d'assistant. Tenu à jour au fil du travail. Dernière révision : 2026-07-05.*

## Préférences de collaboration (Luc)

- **C'est Luc qui surveille la création des reels.** Ne PAS scruter `output/` en
  boucle pendant un rendu — attendre que Luc signale que le `reel.mp4` est sorti
  (ou qu'un `PROBLEME.txt` est apparu), PUIS vérifier côté fichiers.
- Après une modif de `src/`, préparer les commandes (build/run/git) pour que Luc
  les lance dans SON Terminal (voir « pièges durs » : git dans dossier monté).
- **Proposer proactivement de meilleurs outils/workflows** aux points de bascule
  naturels — sans attendre qu'on le demande. Ex. : passer le développement de
  reels-af dans **Claude Code** (accès direct Docker/git/localhost), connecteurs
  MCP pertinents, skills utiles. Zoomer périodiquement pour suggérer, pas juste
  exécuter la tâche du moment.

## Ce que c'est

**reels-af** : producteur de reels verticaux (1080×1920) « AI-native », bâti sur **AgentField**.
**Bon Stock** : média québécois sur le cannabis légal (science, industrie, consommation).
Entrée = URL d'article **ou** sujet → sortie = reel vertical avec sous-titres karaoké, **intro/outro vidéo** (logo + indicatif), **transitions xfade aléatoires** entre plans, et **signature vocale**. Chaque rendu se termine par une **auto-vérification**.

## Comment ça tourne (crucial)

- Tourne dans **Docker** : `docker compose up -d`. Deux conteneurs :
  - `control-plane` (moteur AgentField) → port **8090**
  - `reel-af` (l'agent, `python main.py`) → port **8092**
- **Le code est INCLUS dans l'image** (`COPY . /app` dans le Dockerfile). En prod, **toute modif dans `src/` exige une reconstruction** :
  `docker compose build reel-af && docker compose up -d reel-af` (~70 s).
- **MODE DEV (actif) :** `docker-compose.override.yml` monte `src/` **et `.env`**
  en direct (`./src:/app/src:ro`, `./.env:/app/.env:ro`). Une modif de `src/`
  **ou de `.env`** prend alors effet avec `docker compose restart reel-af`
  (~3 s), **sans reconstruire**. Reconstruire seulement si on change
  `pyproject.toml` (dépendances) ou le `Dockerfile`.
- `./output` et `bon-stock/` sont aussi montés en direct (persiste entre
  reconstructions). Le reste (code applicatif) est cuit dans l'image →
  reconstruire pour le prendre.
- **Docker Desktop doit tourner** (`open -a Docker`). Si des reels « se lancent » mais que rien n'apparaît dans `output/`, c'est presque toujours que Docker est éteint.

## Lancer un reel

- `bash reel.sh <url>` (mode article) ou `bash reel.sh "un sujet"` (mode sujet). POST async vers :8090.
- **Le moteur sérialise : UN seul reel rendu à la fois** (un `asyncio.Semaphore(1)` global dans `app.py`). Lancer plusieurs reels = ils font la file automatiquement. Plus de ralentissement parallèle, quelle que soit la méthode (terminal, bouton 🎬, script).
- Sortie : `output/article-<id>/reel.mp4` (ou `topic-<id>`).

## Le pipeline (`src/reel_af/`)

- `agents/extract.py` — URL → « essence ». Téléchargement HTTP + readability ; **repli navigateur headless (Playwright/Chromium)** pour les pages verrouillées par JavaScript **et** les blocages 403 ; **résout les liens Google News RSS**. Échec → `ERREUR.txt` dans le dossier du reel (jamais de dossier vide muet).
- `agents/hook.py` — **mode article seulement** : génère 2-3 accroches candidates (variantes différentes), auto-notées sur hookability/spécificité, choisit mécaniquement la meilleure (pas d'appel juge séparé). Passée telle quelle à `compose.py`, qui écrit le mécanisme/payoff *autour* du hook déjà fixé.
- `agents/compose.py` — Essence (+ hook déjà choisi) → ScriptDraft, un appel `.ai()`.
- `agents/` (suite) — hunters/critic/narrator/judge (mode sujet — a déjà son propre mécanisme de sélection d'accroche, non touché), visual, accent.
- `render/tts.py` — TTS Gemini (phrase par phrase, timings karaoké). Voix par ton.
- `render/images.py` — génération d'images ; **presets de style visuel** (`_ART_STYLE_PRESETS`, 10 styles, voir `bon-stock/STYLES.md`) sélectionnables par reel via `bash reel.sh <url> style3` (pas de redémarrage requis).
- `render/video.py` — ken-burns / Veo.
- `render/stitch.py` — assemblage final : intro vidéo optionnelle → **fondu dédié** (0,5 s, "fade") vers le premier plan ken-burns → plans enchaînés par **fondus xfade** (transition piochée au hasard dans un pool, désactivable) ou coupes franches → sous-titres (libass, décalés si intro) + mux audio (indicatif au début/à la fin, narration au milieu, signature vocale sur l'outro) → **outro vidéo/logo** (durée alignée sur l'intro) ; puis **auto-vérification**. Départ aléatoire piochée dans les vidéos source (intro/outro), pas toujours 00:00. Ne coupe jamais un plan à moitié en fin de reel (gèle la dernière image plutôt que tronquer).
- `render/verify.py` — auto-vérification post-rendu (voir plus bas).
- `render/cost.py` — écrit `cost.json` par reel (raisonnement + images + vidéo en dollars réels).
- `planning/beats.py` — découpe les plans les plus longs (8 s → 2×4s, 6 s → 2×3s) pour plus de dynamisme (chacun sa propre image) ; désactivable via `REEL_AF_SPLIT_LONG_PLANS=0`.
- `planning/` — beats, cards, safe_zone, font_metrics.
- `app.py` — reasoners + points d'entrée (`article_to_reel`, `topic_to_reel`) + **le verrou de sérialisation**.

## Marque Bon Stock (`bon-stock/`)

- `logo.png` → carte d'outro de fin. Le fond de l'outro s'**auto-adapte** : logo opaque → couleur de son coin ; logo transparent → noir.
- `intro/`, `outro/` → vidéos de fond optionnelles piochées **au hasard** dans chaque dossier (sinon fond logo par défaut). Désactivables via `REEL_AF_INTRO=0` / `REEL_AF_OUTRO_VIDEO=0`.
- Signature vocale **« Bon Stock loves cannabis! »** → TTS (voix **Aoede**), générée une fois et mise en cache dans `output/.bonstock-signature.wav`. Remplaçable par un fichier `bon-stock/signature.*` (prioritaire).
- `Indicatif.wav` (jingle) → joue **sous** la voix à l'intro **et** à l'outro (recherche de fichier **insensible à la casse**).
- `MARQUE.md` — référence de marque + tous les knobs `.env`.

## Config (`.env`, lue par docker-compose ; ces réglages ne nécessitent PAS de reconstruction)

- `REEL_AF_SIGNATURE` / `_TEXT` / `_VOICE` / `_BG_VOLUME` — réglage de la signature. Après changement :
  `rm -f output/.bonstock-signature.wav && docker compose up -d reel-af`.
- `REEL_AF_OUTRO_S` / `_BG` / `_LOGO`.
- `REEL_AF_INTRO` / `_INTRO_MAX_S` / `_INTRO_BG_VOLUME`, `REEL_AF_OUTRO_VIDEO` — intro/outro vidéo (0/1 pour désactiver, volume de l'indicatif en fond).
- `REEL_AF_TRANSITIONS` (pool de transitions xfade, `none` pour désactiver) / `_TRANSITION_S` (durée du fondu).
- `REEL_AF_SPLIT_LONG_PLANS` (`0` pour désactiver le découpage des plans de 8 s en 2×4 s).
- `REEL_AF_USE_VEO` (`false` = ken-burns ~0,10 $/reel ; `true` = Veo ~1,20 $).
- `.env` contient la clé OpenRouter → **ignoré par git** (ne jamais committer).

## PIÈGES DURS (à lire avant d'éditer)

1. **Code cuit dans l'image** en prod → reconstruire après modif de `src/`. **MAIS en mode dev** (`docker-compose.override.yml` monte `src/` en direct) → un simple `docker compose restart reel-af` suffit. `output/` et `bon-stock/` sont montés en direct dans tous les cas.
2. **Linux est sensible à la casse** : les recherches de fichiers `bon-stock/` doivent l'ignorer (`Indicatif.wav` ≠ `indicatif.wav`).
3. **ffmpeg `-shortest` + `apad`** = audio « infini », ne coupe jamais. Forcer la durée exacte avec `-t <total>` (somme des plans).
4. **Variable d'env vide écrase le défaut** : utiliser `os.getenv(X) or "def"`, pas `os.getenv(X, "def")` (docker-compose passe `""` quand non défini).
5. **Ne PAS lancer git dans le dépôt monté depuis le sandbox/Cowork** : le décalage de permissions laisse des `.git/*.lock` que l'utilisateur doit `rm`. → **Préparer les commandes git pour que Luc les lance dans SON Terminal.**
6. **Sérialisation** : un reel à la fois (verrou moteur). Ne pas se fier à la méthode de lancement.
7. **Remotes git** : `Agent-Field/reels-af` (le repo template d'origine) est un dépôt tiers — Luc n'y a **pas** les droits d'écriture. Depuis 2026-07-03, `origin` pointe vers son fork **`LuckyTucky/reels-af`** (créé via `gh repo fork --remote`) ; `upstream` = `Agent-Field/reels-af` en lecture seule. `git push` pousse donc vers le fork. Auth GitHub gérée par `gh auth login` (déjà fait, pas de mot de passe à ressaisir).

## Auto-vérification post-rendu (`render/verify.py`)

À la fin de chaque rendu, vérifie : format 1080×1920, **piste audio présente et non silencieuse** (TTS raté), **pas d'écran noir** prolongé, durée plausible. Écrit `verification.json` dans le dossier du reel, et un **`PROBLEME.txt`** lisible **seulement si** un défaut est détecté. **Non bloquant.**

## Versions (tags git)

- **v1.3.0-stable** — extraction headless (JS + 403), outro logo, sérialisation moteur.
- **v1.4.0** — signature vocale + indicatif sonore.
- **v1.8.0** (dernier tag ; les jalons v1.5–v1.7 n'ont pas été tagués séparément) — auto-vérification post-rendu (`verify.py`), intro/outro **vidéo** (en plus du logo statique) avec indicatif au début et à la fin, **transitions xfade aléatoires** entre plans, **découpage des plans longs** (8 s → 2×4 s) pour plus de dynamisme, **mode dev** (`docker-compose.override.yml`, montage `src/` en direct + `restart` au lieu de `build`).
Retour arrière : `git checkout <tag>` puis reconstruire. Voir `ROLLBACK.md`.

## Docs compagnons

- `MARQUE.md` (marque + knobs), `ROLLBACK.md` (versions/rollback), `backup-v1-sans-headless/` (code pré-headless), `DEMARRER-CLAUDE-CODE.md` (guide d'ouverture du projet dans Claude Code).
- `OPERER_AU_QUOTIDIEN.md` (dans **phase1-veille**) — le geste quotidien veille → reel.

## Projets liés (hors de ce dépôt)

- **Veille** (`phase1-veille`, agent launchd séparé, port **8080**) — nouvelles cannabis du jour → page HTML avec cases **🎬** → file `veille.faire_reels` (traitement un par un). Source : non-lus Feedbin (dossier « Cannabis »).
- **Agent Critique** (port **8002**) — vérification des faits (backlog).

## Backlog

- 👉 **PROCHAINE SESSION (2026-07-06)** : **narration en français** — version FR du pipeline (system prompts de `compose.py`/`hunters.py`/`narrator.py` actuellement tout en anglais ; voix Gemini TTS FR à choisir ; vérifier le rendu du karaoké/accents avec du texte français).
- **Ton** de la signature vocale (ajustable via `.env`, en cours).
- **Vérif des faits** via l'agent Critique.
- **Pipeline en deux étapes (option)** : séparer `article_to_reel` en `article_to_script(url)` (extrait + compose, écrit `output/<id>/script.txt`, s'arrête là) puis `script_to_reel(dossier)` (reprend le texte — édité ou non — et termine audio/images/montage). Permettrait de relire/corriger la narration avant de dépenser images+vidéo. Idée de Luc (2026-07-05), approuvée en principe mais pas prioritaire — à faire en option, pas par défaut (ne pas casser le geste actuel en un clic).
- ~~Cadre d'accroche viral~~ — fait (2026-07-05) : `agents/hook.py`, nouveau reasoner `pick_hook` en mode article (avant `compose_script`) — génère 2-3 accroches candidates auto-notées (hookability/spécificité, vocabulaire repris de `critic.py`), choisit mécaniquement la meilleure, la fixe pour `compose_script`. ~+0,02 $/reel. Le plugin `brand-voice` a été écarté (sert la cohérence de ton, pas la viralité — mauvais outil pour ce problème). Mode sujet non touché (a déjà son propre juge).
- ~~10 presets de style visuel~~ — fait (2026-07-04/05) : `_ART_STYLE_PRESETS` dans `render/images.py`, sélectionnables par reel (`bash reel.sh <url> styleN`, aucun redémarrage requis). Liste et descriptions : [`bon-stock/STYLES.md`](bon-stock/STYLES.md).
- ~~Correctifs de montage intro/outro~~ — fait (2026-07-04/05) : fondu dédié intro→premier plan, segment aléatoire dans les clips intro/outro (pas toujours 00:00), plus aucun plan coupé à moitié en fin de reel, sync audio/vidéo/outro corrigée. Voir commit `76566d3`.
- ~~Suivi du coût par reel~~ — fait (2026-07-03) : `render/cost.py` écrit `cost.json` dans chaque dossier de reel (raisonnement + images + vidéo captés en dollars réels ; TTS non exposé par l'API OpenRouter, seulement le nombre de caractères).
- ~~Tester un reel en mode Veo~~ — fait (2026-07-03), comparé sur le même article : Ken Burns ≈ 0,47 $/reel vs Veo ≈ 2,07 $/reel (~×4-5, jusqu'à 8 plans à 0,32 $ chacun si tous réussissent). **Décision de Luc : la qualité vidéo ne justifie pas le surcoût — Ken Burns reste le mode par défaut** (`REEL_AF_USE_VEO=false`). Veo reste disponible au besoin pour un reel exceptionnel (basculer `.env` + `docker compose restart reel-af`, sans oublier de repasser à `false` après).
- ~~Éventuel logo sonore `CrazyTunes_Vocal-Logo_main.mp3`~~ — retiré du dépôt en v1.8.0 (remplacé par l'indicatif intro/outro).
- ~~Ouvrir reels-af dans Claude Code~~ — fait, c'est l'environnement de travail courant.

**Note process** : garder ce fichier à jour à chaque version taguée — il avait pris deux versions de retard (resté à v1.5.0 alors que le code était en v1.8.0) avant cette révision du 2026-07-03.
