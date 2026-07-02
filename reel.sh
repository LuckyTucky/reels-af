#!/bin/bash
# Lance un reel Bon Stock.
#   • Donne une URL de nouvelle  -> mode ARTICLE (recommandé : ancré à la source,
#     reste sur le sujet, faits réels).
#   • Donne un sujet entre guillemets -> mode SUJET (machine à angles viraux).
#
# Exemples :
#   bash reel.sh https://bonstock.quebec/ma-nouvelle
#   bash reel.sh "cannabis et sommeil"
#
# Le reel final atterrit dans  output/<id>/reel.mp4  (ouvre le dossier : open output)

PORT=8090
ARG="$1"

if [ -z "$ARG" ]; then
  echo "Donne une URL d'article, OU un sujet entre guillemets."
  echo "  Article (recommandé) :  bash reel.sh https://bonstock.quebec/…"
  echo "  Sujet                :  bash reel.sh \"cannabis et sommeil\""
  exit 1
fi

case "$ARG" in
  http://*|https://*)
    echo "Mode ARTICLE — reel à partir de : $ARG"
    curl -s -X POST "http://localhost:$PORT/api/v1/execute/async/reel-af.reel_article_to_reel" \
      -H "Content-Type: application/json" \
      -d "{\"input\": {\"url\": \"$ARG\"}}"
    ;;
  *)
    echo "Mode SUJET — reel à partir du sujet : $ARG"
    curl -s -X POST "http://localhost:$PORT/api/v1/execute/async/reel-af.reel_topic_to_reel" \
      -H "Content-Type: application/json" \
      -d "{\"input\": {\"topic\": \"$ARG\"}}"
    ;;
esac

echo
echo "Lancé. Suis l'avancement en direct :  http://localhost:$PORT/ui/"
echo "Reel final :  output/<id>/reel.mp4   (ouvre le dossier :  open output )"
