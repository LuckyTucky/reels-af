# CLAUDE.md — brief du projet reels-af / Bon Stock

*Contexte pour toute session d'assistant. Tenu à jour au fil du travail. Dernière révision : 2026-07-02.*

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
Entrée = URL d'article **ou** sujet → sortie = reel vertical avec sous-titres karaoké, **outro logo**, et **signature vocale**.

## Comment ça tourne (crucial)

- Tourne dans **Docker** : `docker compose up -d`. Deux conteneurs :
  - `control-plane` (moteur AgentField) → port **8090**
  - `reel-af` (l'agent, `python main.py`) → port **8092**
- **Le code est INCLUS dans l'image** (`COPY . /app` dans le Dockerfile). En prod, **toute modif dans `src/` exige une reconstruction** :
  `docker compose build reel-af && docker compose up -d reel-af` (~70 s).
- **MODE DEV (actif) :** `docker-compose.override.yml` monte `src/` **en direct**
  (`./src:/app/src:ro`). Une modif de `src/` prend alors effet avec
  `docker compose restart reel-af` (~3 s), **sans reconstruire**. Reconstruire
  seulement si on change `pyproject.toml` (dépendances) ou le `Dockerfile`.
- Seul **`./output`** est monté (persiste entre reconstructions). Le reste (logo, code) est **cuit dans l'image** → reconstruire pour le prendre.
- **Docker Desktop doit tourner** (`open -a Docker`). Si des reels « se lancent » mais que rien n'apparaît dans `output/`, c'est presque toujours que Docker est éteint.

## Lancer un reel

- `bash reel.sh <url>` (mode article) ou `bash reel.sh "un sujet"` (mode sujet). POST async vers :8090.
- **Le moteur sérialise : UN seul reel rendu à la fois** (un `asyncio.Semaphore(1)` global dans `app.py`). Lancer plusieurs reels = ils font la file automatiquement. Plus de ralentissement parallèle, quelle que soit la méthode (terminal, bouton 🎬, script).
- Sortie : `output/article-<id>/reel.mp4` (ou `topic-<id>`).

## Le pipeline (`src/reel_af/`)

- `agents/extract.py` — URL → « essence ». Téléchargement HTTP + readability ; **repli navigateur headless (Playwright/Chromium)** pour les pages verrouillées par JavaScript **et** les blocages 403 ; **résout les liens Google News RSS**. Échec → `ERREUR.txt` dans le dossier du reel (jamais de dossier vide muet).
- `agents/` — compose (script), hunters/critic/narrator/judge (mode sujet), visual, accent.
- `render/tts.py` — TTS Gemini (phrase par phrase, timings karaoké). Voix par ton.
- `render/images.py`, `render/video.py` — génération d'images + ken-burns / Veo.
- `render/stitch.py` — assemblage final : clips de beats → concat + sous-titres (libass) + mux audio ; **outro logo** ; **signature vocale + indicatif** ; puis **auto-vérification**.
- `render/verify.py` — auto-vérification post-rendu (voir plus bas).
- `planning/` — beats, cards, safe_zone, font_metrics.
- `app.py` — reasoners + points d'entrée (`article_to_reel`, `topic_to_reel`) + **le verrou de sérialisation**.

## Marque Bon Stock (`bon-stock/`)

- `logo.png` → carte d'outro de fin. Le fond de l'outro s'**auto-adapte** : logo opaque → couleur de son coin ; logo transparent → noir.
- Signature vocale **« Bon Stock loves cannabis! »** → TTS (voix **Aoede**), générée une fois et mise en cache dans `output/.bonstock-signature.wav`. Remplaçable par un fichier `bon-stock/signature.*` (prioritaire).
- `Indicatif.wav` (jingle) → joue **sous** la voix pendant l'outro (recherche de fichier **insensible à la casse**).
- `MARQUE.md` — référence de marque + tous les knobs `.env`.

## Config (`.env`, lue par docker-compose ; ces réglages ne nécessitent PAS de reconstruction)

- `REEL_AF_SIGNATURE` / `_TEXT` / `_VOICE` / `_BG_VOLUME` — réglage de la signature. Après changement :
  `rm -f output/.bonstock-signature.wav && docker compose up -d reel-af`.
- `REEL_AF_OUTRO_S` / `_BG` / `_LOGO`.
- `REEL_AF_USE_VEO` (`false` = ken-burns ~0,10 $/reel ; `true` = Veo ~1,20 $).
- `.env` contient la clé OpenRouter → **ignoré par git** (ne jamais committer).

## PIÈGES DURS (à lire avant d'éditer)

1. **Code cuit dans l'image** en prod → reconstruire après modif de `src/`. **MAIS en mode dev** (`docker-compose.override.yml` monte `src/` en direct) → un simple `docker compose restart reel-af` suffit. `output/` et `bon-stock/` sont montés en direct dans tous les cas.
2. **Linux est sensible à la casse** : les recherches de fichiers `bon-stock/` doivent l'ignorer (`Indicatif.wav` ≠ `indicatif.wav`).
3. **ffmpeg `-shortest` + `apad`** = audio « infini », ne coupe jamais. Forcer la durée exacte avec `-t <total>` (somme des plans).
4. **Variable d'env vide écrase le défaut** : utiliser `os.getenv(X) or "def"`, pas `os.getenv(X, "def")` (docker-compose passe `""` quand non défini).
5. **Ne PAS lancer git dans le dépôt monté depuis le sandbox/Cowork** : le décalage de permissions laisse des `.git/*.lock` que l'utilisateur doit `rm`. → **Préparer les commandes git pour que Luc les lance dans SON Terminal.**
6. **Sérialisation** : un reel à la fois (verrou moteur). Ne pas se fier à la méthode de lancement.

## Auto-vérification post-rendu (`render/verify.py`, v1.5.0)

À la fin de chaque rendu, vérifie : format 1080×1920, **piste audio présente et non silencieuse** (TTS raté), **pas d'écran noir** prolongé, durée plausible. Écrit `verification.json` dans le dossier du reel, et un **`PROBLEME.txt`** lisible **seulement si** un défaut est détecté. **Non bloquant.**

## Versions (tags git)

- **v1.3.0-stable** — extraction headless (JS + 403), outro logo, sérialisation moteur.
- **v1.4.0** — signature vocale + indicatif sonore.
- **v1.5.0** — auto-vérification post-rendu.
Retour arrière : `git checkout <tag>` puis reconstruire. Voir `ROLLBACK.md`.

## Docs compagnons

- `MARQUE.md` (marque + knobs), `ROLLBACK.md` (versions/rollback), `backup-v1-sans-headless/` (code pré-headless).
- `OPERER_AU_QUOTIDIEN.md` (dans **phase1-veille**) — le geste quotidien veille → reel.

## Projets liés (hors de ce dépôt)

- **Veille** (`phase1-veille`, agent launchd séparé, port **8080**) — nouvelles cannabis du jour → page HTML avec cases **🎬** → file `veille.faire_reels` (traitement un par un). Source : non-lus Feedbin (dossier « Cannabis »).
- **Agent Critique** (port **8002**) — vérification des faits (backlog).

## Backlog

- Narration en **français**.
- **Ton** de la signature vocale (ajustable via `.env`, en cours).
- **Cadre d'accroche** viral (à adapter dans le reasoner de script ; utiliser le plugin `brand-voice`).
- **Vérif des faits** via l'agent Critique.
- **Suivi du coût par reel** (`cost.json`) : capter le coût réel remonté par OpenRouter à chaque appel (raisonnement + images + TTS + Veo) et l'écrire dans le dossier du reel, comme `verification.json`. Pour connaître le coût unitaire par reel.
- **Tester un reel en mode Veo** (`REEL_AF_USE_VEO=true`) pour juger la qualité vidéo (vraie animation i2v) sur du contenu Bon Stock (~1,20–1,50 $/reel) — idéalement une fois le suivi de coût en place.
- Éventuel **logo sonore** `CrazyTunes_Vocal-Logo_main.mp3` à intégrer (à confirmer avec Luc).
- **Guide de démarrage Claude Code** : rédigé → `DEMARRER-CLAUDE-CODE.md`.
  👉 **PREMIÈRE TÂCHE de la prochaine session** : accompagner Luc pour ouvrir
  reels-af dans Claude Code (installation + lancement).
