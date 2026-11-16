#!/usr/bin/env bash
# One scanned PDF to its final tables, all six stages, on one machine with an NVIDIA GPU.
# usage: tables/run_doc.sh <pdf> <doc dir>          from the repository root, after ./setup.sh
#   1. prepare: upright pages and box OCR, CPU               -> <doc>/{pages,ocr,orientation.json}
#   2. MinerU on the pages, GPU                              -> <doc>/mineru/pNN.{md,raw.json}
#   3. second read of the tables the checks flag, GPU        -> <doc>/reread/, <doc>/mineru/reread.json
#   4. Gemini on every page with a table (GEMINI_API_KEY)    -> <doc>/gemini/pNN.json
#   5. workflow: the final tables and their flags            -> <doc>/tables/pNN.json
#   6. report: counts and every flag                         -> <doc>/report.md
# Settings come from the environment or from .env at the repository root (see .env.example).
# Every step skips pages and crops it already did, so a stopped run is resumed by running it again.
set -euo pipefail
pdf=$(realpath "$1")
doc=$(realpath -m "$2")
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
PY=${PY:-.venv/bin/python}
name=$(basename "$doc")

mineru() {  # MinerU on $1/pages -> $1/mineru; $2: name of the job and of its log, logs/<name>.log
  local dir=$1 job=$2 n
  if ! bash tables/mineru/run_mineru.sh "$dir" "$job" || ! tail -n 1 "logs/$job.log" | grep -q '^DONE'; then
    echo "run_doc: MinerU failed on $dir, see logs/$job.log" >&2
    exit 1
  fi
  n=$( (find "$dir/mineru" -maxdepth 1 -name '*.md' 2>/dev/null || true) | wc -l)
  echo "$dir: $(ls "$dir/pages" | wc -l) images, $n read by MinerU"
  [ "$n" -gt 0 ] || { echo "run_doc: MinerU read no page of $dir" >&2; exit 1; }
}

mkdir -p "$doc"
$PY -m tables.prepare "$pdf" "$doc" > "$doc/prepare.log" 2>&1
mineru "$doc" "$name"
$PY -m tables.reread crops "$doc"
if [ -n "$(ls "$doc/reread/pages" 2>/dev/null)" ]; then
  mineru "$doc/reread" "${name}_reread"
  $PY -m tables.reread compare "$doc"
  $PY -m tables.reread accept "$doc"
fi
$PY -m tables.gemini_read "$doc" "${GEMINI_CAP:-100}" > "$doc/gemini.log" 2>&1
if grep -q 'cap reached' "$doc/gemini.log"; then
  echo "run_doc: Gemini call cap (GEMINI_CAP=${GEMINI_CAP:-100}) reached, some pages have no Gemini read; see $doc/gemini.log" >&2
fi
if grep -q ' FAILED ' "$doc/gemini.log"; then
  echo "run_doc: Gemini failed on $(grep -c ' FAILED ' "$doc/gemini.log") page(s); see $doc/gemini.log" >&2
fi
$PY -m tables.workflow "$doc"
$PY -m tables.report "$doc" > "$doc/report.md"
echo "done: $doc/tables/ ($(ls "$doc/tables" | wc -l) pages with tables), $doc/report.md"
