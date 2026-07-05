#!/bin/bash
# Lance un reel Bon Stock.
#   • Donne une URL de nouvelle  -> mode ARTICLE (recommandé : ancré à la source,
#     reste sur le sujet, faits réels).
#   • Donne un sujet entre guillemets -> mode SUJET (machine à angles viraux).
#   • Ajoute un 2e argument pour tester un style visuel (ex. style1) sans
#     toucher à .env ni redémarrer Docker — voir _ART_STYLE_PRESETS dans
#     src/reel_af/render/images.py.
#
# Exemples :
#   bash reel.sh https://bonstock.quebec/ma-nouvelle
#   bash reel.sh https://bonstock.quebec/ma-nouvelle style1
#   bash reel.sh "cannabis et sommeil" style1
#
# Le reel final atterrit dans  output/<id>/reel.mp4  (ouvre le dossier : open output)

PORT=8090
ARG="$1"
STYLE="$2"

if [ -z "$ARG" ]; then
  echo "Donne une URL d'article, OU un sujet entre guillemets."
  echo "  Article (recommandé) :  bash reel.sh https://bonstock.quebec/…"
  echo "  Sujet                :  bash reel.sh \"cannabis et sommeil\""
  echo "  Style visuel (option) : bash reel.sh https://…/article style1"
  exit 1
fi

case "$ARG" in
  http://*|https://*)
    echo "Mode ARTICLE — reel à partir de : $ARG"
    [ -n "$STYLE" ] && echo "Style visuel : $STYLE"
    curl -s -X POST "http://localhost:$PORT/api/v1/execute/async/reel-af.reel_article_to_reel" \
      -H "Content-Type: application/json" \
      -d "{\"input\": {\"url\": \"$ARG\", \"art_style\": \"$STYLE\"}}"
    ;;
  *)
    echo "Mode SUJET — reel à partir du sujet : $ARG"
    [ -n "$STYLE" ] && echo "Style visuel : $STYLE"
    curl -s -X POST "http://localhost:$PORT/api/v1/execute/async/reel-af.reel_topic_to_reel" \
      -H "Content-Type: application/json" \
      -d "{\"input\": {\"topic\": \"$ARG\", \"art_style\": \"$STYLE\"}}"
    ;;
esac

echo
echo "Lancé. Suis l'avancement en direct :  http://localhost:$PORT/ui/"
echo "Reel final :  output/<id>/reel.mp4   (ouvre le dossier :  open output )"
