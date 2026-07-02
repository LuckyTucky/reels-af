# Bon Stock — Fiche de marque (infos récurrentes)

*Dossier central pour tout ce qui revient d'un reel/projet à l'autre. Mets à jour ici, une seule fois.*

---

## Identité

- **Nom** : Bon Stock
- **Nature** : média québécois sur la science, l'industrie et la consommation du cannabis légal (Québec, Canada, monde).
- **Public** : francophone, curieux, sensible à la rigueur scientifique et au marché québécois/canadien.
- **Emoji maison** : 🌿

## Signature vocale de fin (implémentée)

- Phrase : **« Bon Stock loves cannabis! »** — voix off au moment où le logo apparaît.
- **Voix** : féminine, chaleureuse et constante (Gemini TTS, voix « Kore »). Générée
  **une seule fois** puis mise en cache (`output/.bonstock-signature.wav`) et réutilisée.
- **Remplacer par ta propre voix** : dépose un fichier `bon-stock/signature.wav` (ou
  .mp3/.m4a) — il est prioritaire sur la génération automatique.
- **Indicatif sonore de fond (jingle)** — optionnel : dépose `bon-stock/indicatif.wav`
  (ou .mp3…). Il joue **sous** la voix pendant l'outro, à volume réduit.
- L'outro s'allonge automatiquement pour ne jamais couper la voix.

### Réglages (variables d'env, modifiables via `.env` sans reconstruire)

- `REEL_AF_SIGNATURE` — `0` pour désactiver la signature vocale (défaut activé).
- `REEL_AF_SIGNATURE_TEXT` — changer la phrase.
- `REEL_AF_SIGNATURE_VOICE` — voix Gemini (défaut `Kore` ; autres féminines : `Aoede`).
- `REEL_AF_SIGNATURE_BG_VOLUME` — volume du jingle (défaut `0.35`).

## Logo

- **Fichier** : `bon-stock/logo.png` (déposé par Luc).
- Format idéal : **PNG à fond transparent**, bonne résolution (le reel est en 1080×1920).
- Utilisé automatiquement par le montage (`render/stitch.py`) pour le **plan de fin (outro)**.
- Pour pointer vers un autre fichier : variable d'env `REEL_AF_LOGO` (chemin absolu).

## Couleurs (utilisées dans la veille — à confirmer/compléter)

- Vert principal : `#2E7D32`
- Vert vif (accents) : `#16a34a`
- *(À compléter avec les couleurs officielles de la charte si tu les as.)*

## Réglages du plan de fin (outro)

- Durée : **2 s** (variable d'env `REEL_AF_OUTRO_S`).
- Fond : **noir** par défaut (variable d'env `REEL_AF_OUTRO_BG`, ex. `black`, `white`, `#0b3d2e`).
- Logo centré, léger fondu d'entrée.

## Liens

- Site (exemple vu dans le projet) : `bonstock.quebec` *(à confirmer)*

---

*Note : les éléments marqués « à confirmer » sont des déductions tirées du projet ; corrige-les au besoin.*
