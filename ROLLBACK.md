# Reels-af — versions & retour arrière

## Où on en est

- **v1.0.0 (backup)** — extraction par téléchargement HTTP + readability.
  Sauvegardée dans `backup-v1-sans-headless/`.
- **v1.1.0 (actuelle)** — ajoute un **navigateur headless (Chromium/Playwright)**
  en repli automatique quand une page est verrouillée par JavaScript, en plus
  des correctifs déjà en place (User-Agent navigateur, résolution Google News,
  fichier `ERREUR.txt` en cas d'échec).

## Ce que fait la v1.1.0

Extraction d'un article en deux temps :

1. **Chemin rapide** — téléchargement HTTP + readability (comme avant).
2. **Repli headless** — si la page est vide ou affiche « activez JavaScript »
   (sites protégés, anti-robot, Google News), le moteur ouvre un vrai Chromium
   qui exécute le JavaScript, puis ré-extrait l'article.

Si même le headless échoue, tu obtiens un `ERREUR.txt` clair dans le dossier du
reel (jamais de dossier vide silencieux).

## Installer la v1.1.0 (reconstruire l'image)

Le navigateur est inclus dans l'image Docker → il faut la reconstruire. C'est
plus long que d'habitude (~5-10 min : téléchargement de Chromium + dépendances)
et l'image grossit d'environ 1 Go.

```bash
cd ~/Claude/Projects/reels-af
# 1) (recommandé) garder l'image actuelle comme filet de sécurité :
docker compose images reel-af          # note le REPOSITORY:TAG affiché
docker tag "$(docker compose images -q reel-af)" reel-af:v1-backup

# 2) construire et démarrer la v1.1.0 :
docker compose build reel-af && docker compose up -d reel-af
```

Tester ensuite sur une page JS (celle qui échouait) :

```bash
cd ~/Claude/Projects/reels-af && bash reel.sh "https://stupiddope.com/2026/07/seth-rogens-houseplant-turns-the-humble-planter-into-a-collectible-design-piece/"
```

## Revenir à la v1 (retour arrière)

### Option A — juste redémarrer l'ancienne image (le plus rapide)

Si tu as fait le `docker tag … reel-af:v1-backup` ci-dessus :

```bash
cd ~/Claude/Projects/reels-af
docker compose stop reel-af
docker run -d --name reel-af-v1 --network container:reels-af-control-plane-1 \
  -v "$PWD/output:/app/output" --env-file .env reel-af:v1-backup
```

(ou, plus simple, l'option B qui reconstruit proprement depuis le code v1.)

### Option B — restaurer le code v1 puis reconstruire

```bash
cd ~/Claude/Projects/reels-af
cp backup-v1-sans-headless/src/reel_af/agents/extract.py src/reel_af/agents/extract.py
cp backup-v1-sans-headless/src/reel_af/app.py            src/reel_af/app.py
cp backup-v1-sans-headless/Dockerfile                    Dockerfile
cp backup-v1-sans-headless/pyproject.toml                pyproject.toml
docker compose build reel-af && docker compose up -d reel-af
```

Tes reels déjà produits dans `output/` sont conservés dans tous les cas.
