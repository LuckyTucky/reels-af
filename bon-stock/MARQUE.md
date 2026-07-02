# Bon Stock — Fiche de marque (infos récurrentes)

*Dossier central pour tout ce qui revient d'un reel/projet à l'autre. Mets à jour ici, une seule fois.*

---

## Identité

- **Nom** : Bon Stock
- **Nature** : média québécois sur la science, l'industrie et la consommation du cannabis légal (Québec, Canada, monde).
- **Public** : francophone, curieux, sensible à la rigueur scientifique et au marché québécois/canadien.
- **Emoji maison** : 🌿

## Signature vocale (pour l'outro audio — à venir)

- Phrase : **« Bon Stock loves cannabis! »**
- Usage prévu : clip audio de signature collé à la fin de chaque reel (enregistrement fixe ou TTS).

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
