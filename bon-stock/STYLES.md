# Presets de style visuel — reels-af

*Référence des 10 styles testés le 2026-07-04/05. Chaque preset remplace la
note de style envoyée à Gemini Image pour TOUS les plans du reel. Décrit par
traits visuels, jamais par le nom d'un artiste (les modèles d'image
édulcorent ou refusent les prompts qui nomment un style connu par son nom).*

## Comment les utiliser

```bash
bash reel.sh "https://url-article" style3
bash reel.sh "un sujet entre guillemets" style7
```

Sans style précisé : comportement normal (style selon le sujet). Aucun
redémarrage de Docker requis pour changer de style entre deux reels — c'est
un paramètre par reel, pas un réglage `.env`.

Pour ajouter un nouveau style : éditer `_ART_STYLE_PRESETS` dans
[`src/reel_af/render/images.py`](../src/reel_af/render/images.py) — décrire
les traits techniques + palette + exclusions + cadrage (le cadrage vertical
sans texte est une contrainte technique constante, à garder dans tout
nouveau preset).

## Les 10 styles

| # | Nom de travail | Référence / moodboard | Statut |
|---|---|---|---|
| 1 | Pop-art / trames de points | Lichtenstein (décrit sans nommer) | ✅ Validé (2 reels) |
| 2 | Affiche mi-siècle / papier découpé | Saul Bass | ✅ Validé (1 reel) |
| 3 | Espace négatif à double lecture | Noma Bar | ✅ Validé (1 reel) |
| 4 | Film noir couleur (pulp peint) | Affiches de films noir, couleur | ✅ Validé (1 reel) |
| 5 | Film noir noir-et-blanc (clair-obscur) | Photogrammes de films noir, N&B | ✅ Validé (1 reel) |
| 6 | Illustration onirique, silhouettes bleues | Jean-Michel Folon | ✅ Validé (1 reel) |
| 7 | Réalisme narratif, Americana chaleureuse | Norman Rockwell | ✅ Validé (1 reel) |
| 8 | Affiche protestataire, contours encrés | Edel Rodriguez | ✅ Validé (1 reel) |
| 9 | Pochoir/sérigraphie, rouge/crème/sarcelle | Shepard Fairey | ✅ Validé (1 reel) |
| 10 | Psychédélique 60-70, rubans de couleurs | Milton Glaser | ✅ Validé (1 reel) |

## Descriptions complètes

### Style 1 — Pop-art / trames de points
Illustration bande dessinée pop-art audacieuse : contours d'encre noire
épais autour de chaque forme, couleurs plates non ombrées remplies de
trames de points Ben-Day visibles (surtout dans les ombres, tons de peau,
arrière-plans), palette primaire vive limitée (rouge, jaune, bleu, noir,
blanc), cadrage graphique à fort contraste façon page de comic vintage.
Aucun photoréalisme, aucun dégradé, aucun grain de film.

### Style 2 — Affiche mi-siècle / papier découpé
Illustration d'affiche graphique mi-siècle : le sujet réduit à une
silhouette plate ou une forme symbolique abstraite (comme découpée aux
ciseaux dans du papier coloré et collée), formes nettes à bords durs sans
contour, palette à fort contraste dominée par l'orange brûlé, le jaune
moutarde, le noir et le blanc crème avec un accent occasionnel sarcelle ou
rouge, grand espace négatif dramatique, léger grain de papier sérigraphié
vintage et léger décalage de repérage des couleurs.

### Style 3 — Espace négatif à double lecture
Illustration vectorielle minimaliste moderne construite entièrement de
silhouettes plates : seulement 2-3 couleurs pleines par image, aucun
dégradé/texture/grain/contour, formes vectorielles nettes. Usage astucieux
de l'espace négatif pour que le vide entre ou dans une silhouette se lise
comme une seconde image cachée liée au sujet — un double sens visuel
espiègle. Aplats de couleur saturée audacieux, clarté d'affiche graphique.

### Style 4 — Film noir couleur (pulp peint)
Illustration d'affiche de film policier pulp dramatique : coup de pinceau
peint (pas photographique, pas vectoriel plat), éclairage latéral directionnel
dur qui coupe visages et scènes en moitié lumière/moitié ombre profonde,
palette saturée rouge sang/orange brûlé/noir avec reflets crème, angles
dramatiques inclinés, imperméables/feutres/ombres portées longues évoquant
danger et mystère, grain d'impression vintage visible.

### Style 5 — Film noir noir-et-blanc (clair-obscur)
Vrai photogramme noir-et-blanc, aucune couleur, éclairage clair-obscur à
fort contraste avec noirs profonds encrés et blancs brûlés, une seule
lumière clé dure projetant des motifs d'ombre à bords durs (stores
vénitiens, rampes d'escalier, barreaux de fenêtre) sur visages et murs,
brume/fumée atmosphérique épaisse, ambiance nocturne feutrée, réalisme
photographique net avec grain argentique visible.

### Style 6 — Illustration onirique, silhouettes bleues
Illustration gouache-et-aquarelle douce et onirique, ambiance surréaliste
poétique et fantaisiste, figure humaine simplifiée aux contours arrondis
avec visage vierge ou minimal, dégradés de couleur aérographés doux (ciels
fondant du bleu vers l'ambre chaud ou le rose), une petite figure solitaire
contre un ciel ou paysage vaste évoquant le calme et l'émerveillement,
contours arrondis doux sans contour noir dur, palette pastel-à-saturée
dominée par les bleus.

### Style 7 — Réalisme narratif, Americana chaleureuse
Illustration à l'huile réaliste chaleureuse et narrative façon couverture
de magazine mi-siècle classique, détail finement rendu et réaliste sur
personnages, visages et scènes américaines du quotidien, palette
nostalgique chaleureuse (ambres, rouges doux, verts atténués), composition
narrative captant un moment ou une expression humaine authentique, éclairage
naturaliste doux, texture entièrement peinte avec détail fin au pinceau —
pas plat, pas graphique, pas vectoriel.

### Style 8 — Affiche protestataire, contours encrés
Illustration d'affiche protestataire audacieuse et expressive, contours
encrés à la main épais et rugueux avec texture de coup de pinceau visible,
palette saturée plate dominée par l'orange feu, le rouge et le jaune plus
noir et crème, énergie graphique brute et urgente, figures simplifiées et
légèrement exagérées avec un aspect satirique, texture d'affiche sérigraphiée
à fort contraste, symbolisme graphique audacieux, qualité délibérément brute
et dessinée à la main — aucun photoréalisme, aucune propreté numérique lisse.

### Style 9 — Pochoir/sérigraphie, rouge/crème/sarcelle
Illustration d'affiche de propagande façon pochoir, texture de pochoir et
de trame de points superposée à fort contraste, palette limitée signature
de rouge profond, crème/blanc cassé et bleu sarcelle atténué plus noir,
portraiture graphique forte à base de silhouette avec cadrage héroïque
monumental, blocs de couleur pochoirs plats à bords nets francs, énergie
d'art politique populaire.

### Style 10 — Psychédélique 60-70, rubans de couleurs
Illustration plate espiègle psychédélique années 60-70, une silhouette ou
forme de profil noire plate audacieuse ancrant l'image, combinée à des
bandes de couleur plates façon rubans tourbillonnants dans des teintes
saturées façon arc-en-ciel (orange, rose, violet, vert, jaune) rayonnant
vers l'extérieur, chaque bande un aplat de couleur unique sans dégradé ni
ombrage, linéature fluide énergique et groovy espiègle, harmonie de couleur
vibrante et joyeuse, illustration d'affiche purement plate en 2D sans
photoréalisme ni ombrage de profondeur.
