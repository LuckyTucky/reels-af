#!/usr/bin/env bash
# ===========================================================================
#  Bon Stock — Reels À LA CHAÎNE (un seul à la fois, jamais en parallèle)
# ===========================================================================
#  Traite plusieurs reels LES UNS APRÈS LES AUTRES : lance le 1er, attend qu'il
#  soit terminé, puis lance le 2e, etc. Fini le ralentissement des runs en
#  parallèle. Les URLs qui échouent (ex. liens Google News RSS) sont sautées.
#
#  DEUX FAÇONS DE L'UTILISER :
#
#   A) Donner les URLs directement :
#        bash reels_a_la_chaine.sh "https://…article1"  "https://…article2"
#
#   B) Remplir le fichier « reels_a_faire.txt » (une URL par ligne) puis :
#        bash reels_a_la_chaine.sh
#      (les lignes vides et celles commençant par # sont ignorées — tu peux
#       donc "décocher" une nouvelle en mettant # devant.)
#
#  Pré-requis : Docker démarré + moteur reels-af en route
#               (open -a Docker ; puis  docker compose up -d).
# ===========================================================================

set -uo pipefail

PORT=8090
CP="http://localhost:$PORT"
DELAI_MAX=1200          # abandon d'un reel après 20 min (puis on passe au suivant)
PROJET="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJET"

# --- 1) Rassembler les URLs : arguments en priorité, sinon reels_a_faire.txt ---
URLS=()
if [ "$#" -gt 0 ]; then
  URLS=("$@")
elif [ -f reels_a_faire.txt ]; then
  while IFS= read -r ligne || [ -n "$ligne" ]; do
    ligne="${ligne%%#*}"                       # retirer les commentaires
    ligne="$(printf '%s' "$ligne" | xargs)"    # enlever les espaces autour
    [ -n "$ligne" ] && URLS+=("$ligne")
  done < reels_a_faire.txt
fi

if [ "${#URLS[@]}" -eq 0 ]; then
  echo "Aucune URL à traiter."
  echo "  • soit :  bash reels_a_la_chaine.sh \"https://…\" \"https://…\""
  echo "  • soit : remplis reels_a_faire.txt (une URL par ligne) puis relance sans argument."
  exit 1
fi

total=${#URLS[@]}
echo "🎬 File d'attente Bon Stock : $total reel(s), traités UN PAR UN."
echo "   (moteur : $CP — assure-toi que Docker tourne)"

ok=0; echec=0; i=0
mkdir -p output

for url in "${URLS[@]}"; do
  i=$((i+1))
  echo
  echo "──────────────────────────────────────────────────────────────────────"
  echo " [$i/$total]  $url"
  echo "──────────────────────────────────────────────────────────────────────"

  # --- 2) Lancer le reel (async) et récupérer l'execution_id ---
  resp=$(curl -sS -X POST "$CP/api/v1/execute/async/reel-af.reel_article_to_reel" \
    -H "Content-Type: application/json" \
    -d "{\"input\":{\"url\":\"$url\"}}" 2>/dev/null)
  exec_id=$(printf '%s' "$resp" | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('execution_id',''))
except Exception: print('')" 2>/dev/null)

  if [ -z "$exec_id" ]; then
    echo "  ⚠ Moteur injoignable (aucun execution_id)."
    echo "    Docker est-il démarré ?  open -a Docker  puis  docker compose up -d"
    echec=$((echec+1))
    continue
  fi
  echo "  execution_id = $exec_id — en cours…"

  # --- 3) Attendre la fin AVANT de passer au suivant ---
  start=$(date +%s)
  while :; do
    resp=$(curl -sS "$CP/api/v1/executions/$exec_id" 2>/dev/null)
    status=$(printf '%s' "$resp" | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('status','?'))
except Exception: print('?')" 2>/dev/null)
    elapsed=$(($(date +%s) - start))

    case "$status" in
      succeeded)
        vp=$(printf '%s' "$resp" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('result') or {}).get('video_path',''))
except Exception: print('')" 2>/dev/null)
        echo "  ✅ [${elapsed}s] TERMINÉ → ${vp:-output/<id>/reel.mp4}"
        ok=$((ok+1)); break
        ;;
      failed)
        echo "  ❌ [${elapsed}s] ÉCHEC — URL probablement inexploitable"
        echo "     (ex. lien Google News RSS, ou page sans vrai contenu). On saute."
        echec=$((echec+1)); break
        ;;
      *)
        printf "  … [%4ds] %s\n" "$elapsed" "$status"
        ;;
    esac

    if [ "$elapsed" -gt "$DELAI_MAX" ]; then
      echo "  ⏱ Délai dépassé ($((DELAI_MAX/60)) min) — on passe au suivant."
      echec=$((echec+1)); break
    fi
    sleep 20
  done
done

echo
echo "══════════════════════════════════════════════════════════════════════"
echo " Terminé : $ok réussi(s), $echec échec/saut(s) sur $total."
echo " Tes reels sont dans  output/  →  ouvre le dossier :  open output"
echo "══════════════════════════════════════════════════════════════════════"
