"""Mood board → style custom — distillation vision (un seul appel .ai()).

Téléversé depuis /texte : N images de référence → UN preset de style visuel
réutilisable, au même format que les presets codés en dur de
render/images._ART_STYLE_PRESETS. Appel court et indépendant d'un rendu de
reel — ne prend PAS _REEL_RENDER_LOCK (voir app.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reel_af.models import MoodboardDistillation

_SYSTEM = """Tu es directeur artistique pour Bon Stock, un média québécois sur le cannabis légal. On te donne un mood board : plusieurs images de référence. Distille-les en UN seul preset de style visuel réutilisable.

Observe ce que les images ont en COMMUN : technique (photo, peinture à l'huile, aquarelle, vecteur plat, collage, sérigraphie…), traitement des contours, texture et grain, palette, éclairage, niveau d'abstraction, ambiance. Ignore le sujet précis de chaque image — on appliquera ce style à d'autres sujets. Ne capture que le LOOK.

english_prompt : 60-90 mots, EN ANGLAIS, décrivant les traits visuels (technique, contours, texture, palette, éclairage, ambiance) PLUS les exclusions pertinentes (no photorealism / no gradients / no outlines / etc. selon le cas). NE NOMME JAMAIS un artiste, studio, marque ou œuvre — décris les traits, car les modèles d'image édulcorent ou refusent les noms propres. Termine OBLIGATOIREMENT english_prompt par : "VERTICAL portrait composition (taller than wide, subject occupies the upper-middle two-thirds), fills the frame, no text or letters".

Exemple de gabarit pour english_prompt (style existant, à titre d'illustration du format attendu — NE PAS COPIER) : « bold pop-art comic illustration, thick black ink outlines around every shape, flat unshaded colors filled with visible Ben-Day dot halftone, a limited bright primary palette of red, yellow, blue, black and white, high-contrast comic-book framing, no photorealism, no gradients, no soft shading, no film grain; VERTICAL portrait composition (taller than wide, subject occupies the upper-middle two-thirds), fills the frame, no text or letters ».

nom : nom court FR du style, 2-4 mots. bon : "bon pour…", 3-5 mots sur l'usage ou l'émotion. desc : 1 phrase FR décrivant le style."""


async def distill_style(app: Any, image_paths: list[Path]) -> MoodboardDistillation:
    """N images (chemins locaux) → MoodboardDistillation (appel de vision).

    `app.ai()` auto-détecte les chemins de fichiers image et les encode en
    base64 pour le modèle de raisonnement courant (REEL_AF_MODEL, vision-
    capable) — pas besoin de passer `model=` explicitement.
    """
    return await app.ai(
        *[str(p) for p in image_paths], system=_SYSTEM, schema=MoodboardDistillation,
    )
