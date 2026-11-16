#!/usr/bin/env bash
# One scanned PDF to its final tables, all six stages, on one machine with an NVIDIA GPU.
# usage: tables/run_doc.sh <pdf> <doc dir>          from the repository root, after ./setup.sh
#   1. prepare: upright pages, then box OCR (CPU)            -> <doc>/{pages,ocr,orientation.json}
#   2. MinerU on the pages (GPU)                             -> <doc>/mineru/pNN.{md,raw.json}
#   3. second read of the tables the checks flag (GPU)       -> <doc>/reread/, <doc>/mineru/reread.json
#   4. Gemini on every page with a table (GEMINI_API_KEY)    -> <doc>/gemini/pNN.json
#   5. workflow: the final tables and their flags            -> <doc>/tables/pNN.json
#   6. report: counts and every flag                         -> <doc>/report.md
# What runs side by side: once the pages are upright, MinerU (GPU) and the box OCR (CPU) start together; Gemini
# (network) starts as soon as MinerU has said which pages hold a table. One MinerU process reads the pages and, after
# the box OCR is done and the crops of stage 3 are cut, the crops: its model is loaded once.
# Settings come from the environment or from .env at the repository root (see .env.example).
# Every step skips pages and crops it already did, so a stopped run is resumed by running it again.
set -euo pipefail
pdf=$(realpath "$1")
doc=$(realpath -m "$2")
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
PY=${PY:-.venv/bin/python}
name=$(basename "$doc")
ready=$doc/reread/.ready
t0=$(date +%s)
stamp() { echo "[$(( $(date +%s) - t0 ))s] $*"; }

mkdir -p "$doc/reread" logs
rm -f "$ready" "$doc/mineru/.done"
trap 'touch "$ready"' EXIT  # whatever happens here, the MinerU process does not wait for crops forever

$PY -m tables.prepare "$pdf" "$doc" pages > "$doc/prepare.log" 2>&1
stamp "pages upright: $(ls "$doc/pages" | wc -l)"

bash tables/mineru/run_mineru.sh "$name" "$doc/pages" "$doc/mineru" \
  --crops "$doc/reread/pages" "$doc/reread/mineru" "$ready" --jobs "${MINERU_JOBS:-1}" &
gpu=$!
$PY -m tables.prepare "$pdf" "$doc" ocr >> "$doc/prepare.log" 2>&1 &
cpu=$!

until [ -e "$doc/mineru/.done" ]; do
  kill -0 $gpu 2>/dev/null || { echo "run_doc: MinerU failed on $doc, see logs/$name.log" >&2; exit 1; }
  sleep 2
done
n=$( (find "$doc/mineru" -maxdepth 1 -name 'p*.md' 2>/dev/null || true) | wc -l)
stamp "MinerU read $n of $(ls "$doc/pages" | wc -l) pages"
[ "$n" -gt 0 ] || { echo "run_doc: MinerU read no page of $doc" >&2; exit 1; }

$PY -m tables.gemini_read "$doc" "${GEMINI_CAP:-100}" "${GEMINI_JOBS:-8}" > "$doc/gemini.log" 2>&1 &
net=$!

wait $cpu || { echo "run_doc: box OCR failed, see $doc/prepare.log" >&2; exit 1; }
stamp "box OCR done"
$PY -m tables.reread crops "$doc"
touch "$ready"
wait $gpu && tail -n 1 "logs/$name.log" | grep -q '^DONE' \
  || { echo "run_doc: MinerU failed on the crops, see logs/$name.log" >&2; exit 1; }
if [ -n "$(ls "$doc/reread/pages" 2>/dev/null)" ]; then
  $PY -m tables.reread compare "$doc"
  $PY -m tables.reread accept "$doc"
fi
stamp "second reads done"

wait $net || { echo "run_doc: Gemini step failed, see $doc/gemini.log" >&2; exit 1; }
stamp "Gemini done"
if grep -q 'NOT READ' "$doc/gemini.log"; then
  echo "run_doc: Gemini did not read some pages ($(grep 'NOT READ' "$doc/gemini.log")); see $doc/gemini.log" >&2
fi
$PY -m tables.workflow "$doc"
$PY -m tables.report "$doc" > "$doc/report.md"
stamp "done: $doc/tables/ ($(ls "$doc/tables" | wc -l) pages with tables), $doc/report.md"
