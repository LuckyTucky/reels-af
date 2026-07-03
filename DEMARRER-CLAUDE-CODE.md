# Démarrer avec Claude Code sur reels-af

*Guide pas-à-pas pour Luc (non-développeur). Objectif : m'ouvrir directement sur le projet reels-af, avec les mains sur Docker, git et le rendu — au lieu de te faire relayer chaque commande.*

---

## En bref

Claude Code = **la même Claude que dans Cowork**, mais qui tourne **dans ton projet**, sur ta machine. Tu me parles en français exactement pareil ; la différence, c'est que je peux lancer moi-même `docker compose`, `bash reel.sh`, `git`, et atteindre `localhost`. Notre boucle devient « je fais → je te montre » au lieu de « je te dicte → tu colles ».

---

## Étape 1 — Choisir ta porte

Deux options, choisis selon ton confort :

- **App Desktop (recommandée pour toi)** — la plus visuelle, sans Terminal. Revue des changements à l'écran, sessions côte à côte. C'est le plus proche de Cowork.
- **Terminal** — une fenêtre texte où on tape `claude`. Tu colles déjà des commandes sans souci, donc c'est jouable aussi.

*(Il existe aussi une extension VS Code et une version web, mais commence par l'une des deux ci-dessus.)*

## Étape 2 — Installer

**Option A — App Desktop**
1. Télécharge l'app Claude Desktop (macOS, Apple Silicon ou Intel) depuis le site d'Anthropic.
2. Installe, ouvre, connecte-toi avec ton compte Claude.
3. Clique l'onglet **« Code »**.

**Option B — Terminal**
Dans le Terminal, colle :
```bash
curl -fsSL https://claude.ai/install.sh | bash
```
*(ou, si tu as Homebrew : `brew install --cask claude-code`)*

## Étape 3 — Prérequis (comme d'habitude)

- **Docker Desktop lancé** (`open -a Docker`) — le moteur reels-af en dépend.
- Le projet est déjà là : `~/Claude/Projects/reels-af`.

## Étape 4 — M'ouvrir sur reels-af

**App Desktop :** onglet « Code » → ouvrir le dossier `~/Claude/Projects/reels-af`.

**Terminal :**
```bash
cd ~/Claude/Projects/reels-af
claude
```
(La première fois, il te demandera de te connecter. Ensuite, tape ta consigne.)

## Étape 5 — Ta première consigne (copie-colle)

> Lis `CLAUDE.md` et `ROLLBACK.md` pour reprendre le contexte du projet reels-af. Fais-moi un point sur l'état actuel (versions, ce qui marche, le backlog), puis propose par quoi on continue.

Je démarrerai à plein régime : **`CLAUDE.md` est lu automatiquement** au début de chaque session (on l'a écrit ensemble — architecture, pièges durs, historique, préférences).

---

## Ce qui change concrètement pour nous

- Je lance **moi-même** les rendus : `bash reel.sh <url>`, et je surveille la sortie.
- **Mode dev déjà en place** : après une modif de code, un simple `docker compose restart reel-af` (~3 s) suffit — je le ferai directement.
- **git propre** : commits, tags, retours arrière en natif (fini les verrous `.git/*.lock` du dossier monté).
- J'atteins **tes services locaux** : moteur `:8090`, Veille `:8080`, Critique `:8002`.

## Sécurité — tu restes aux commandes

Claude Code **demande la permission avant d'agir** (lancer une commande, modifier un fichier). Tu approuves, comme ici. Tu peux tout arrêter à tout moment. Ton rôle ne change pas : tu diriges et tu juges le résultat.

## Filet de sécurité

- `ROLLBACK.md` : comment revenir à une version stable (`git checkout v1.3.0-stable`, etc.).
- `MARQUE.md`, `OPERER_AU_QUOTIDIEN.md` (dans phase1-veille) : les autres repères du projet.

---

*Quand tu es prêt : ouvre la porte (Étape 4), colle la première consigne (Étape 5), et on continue reels-af — en plus rapide.*
