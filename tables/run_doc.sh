#!/usr/bin/env bash
# One scanned PDF to its final tables, all six stages, on one machine with an NVIDIA GPU.
# usage: tables/run_doc.sh <pdf> <doc dir>          from the repository root, after ./setup.sh
#   1. prepare: upright pages, then box OCR (CPU)            -> <doc>/{pages,ocr,orientation.json}
#   2. MinerU on the pages (GPU)                             -> <doc>/mineru/pNN.{md,raw.json}
#   3. second read of the tables the checks flag (GPU)       -> <doc>/reread/, <doc>/mineru/reread.json
#   4. Gemini on every page with a table (GEMINI_API_KEY)    -> <doc>/gemini/pNN.json
#   5. workflow: the final tables and their flags            -> <doc>/tables/pNN.json
#   6. report: counts and every flag                         -> <doc>/report.md
# What runs side by side: MinerU (GPU) and Gemini (network) start at once and each takes a page as soon as it is
# ready: MinerU every page image as stage 1 turns it upright, Gemini every page MinerU has read and found a table on.
# The box OCR (CPU) starts when all pages are upright. One MinerU process reads the pages and then, once the box OCR
# is done and the crops of stage 3 are cut, the crops: its model is loaded once.
# Settings come from the environment or from .env at the repository root (see .env.example).
# Every step skips pages and crops it already did, so a stopped run is resumed by running it again. A run that fails
# or is interrupted stops every step it started.
set -euo pipefail
set -m  # each background step in its own process group, so that it can be stopped with all its children
pdf=$(realpath "$1")
doc=$(realpath -m "$2")
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
PY=${PY:-.venv/bin/python}
name=$(basename "$doc")
ready=$doc/reread/.ready
t0=$(date +%s)
stamp() { echo "[$(( $(date +%s) - t0 ))s] $*"; }

started=()
stop() {
  local rc=$? p
  touch "$ready"  # the MinerU process never waits for crops forever
  if [ "$rc" -ne 0 ]; then
    for p in "${started[@]}"; do kill -TERM -- "-$p" 2>/dev/null || true; done
  fi
}
trap stop EXIT
trap 'exit 130' INT TERM

mkdir -p "$doc/pages" "$doc/reread" logs
rm -f "$ready" "$doc/mineru/.done" "$doc/pages/.done"

bash tables/mineru/run_mineru.sh "$name" "$doc/pages" "$doc/mineru" --until "$doc/pages/.done" \
  --crops "$doc/reread/pages" "$doc/reread/mineru" "$ready" --jobs "${MINERU_JOBS:-1}" &
gpu=$!; started+=($gpu)
$PY -m tables.gemini_read "$doc" "${GEMINI_CAP:-100}" "${GEMINI_JOBS:-8}" --follow > "$doc/gemini.log" 2>&1 &
net=$!; started+=($net)

# Stage 1 uses a third of the CPU threads by default (PREP_JOBS): MinerU also needs the CPU to keep the GPU fed.
$PY -m tables.prepare "$pdf" "$doc" pages "${PREP_JOBS:-0}" > "$doc/prepare.log" 2>&1 \
  || { echo "run_doc: stage 1 failed, see $doc/prepare.log" >&2; exit 1; }
stamp "pages upright: $(ls "$doc/pages" | wc -l)"
$PY -m tables.prepare "$pdf" "$doc" ocr "${PREP_JOBS:-0}" >> "$doc/prepare.log" 2>&1 &
cpu=$!; started+=($cpu)

until [ -e "$doc/mineru/.done" ]; do
  kill -0 $gpu 2>/dev/null || { echo "run_doc: MinerU failed on $doc, see logs/$name.log" >&2; exit 1; }
  sleep 1
done
n=$( (find "$doc/mineru" -maxdepth 1 -name 'p*.md' 2>/dev/null || true) | wc -l)
stamp "MinerU read $n of $(ls "$doc/pages" | wc -l) pages"
[ "$n" -gt 0 ] || { echo "run_doc: MinerU read no page of $doc" >&2; exit 1; }

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
