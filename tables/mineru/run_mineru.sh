#!/usr/bin/env bash
# MinerU2.5-Pro through tables/mineru/mineru_dir.py. Log: logs/<name>.log, last line DONE or FAIL. Called by
# tables/run_doc.sh; runs alone too.
# usage, from the repository root: bash tables/mineru/run_mineru.sh <name> <arguments of mineru_dir.py>
#   e.g. bash tables/mineru/run_mineru.sh VIC data/VIC/pages data/VIC/mineru
# MinerU's environment is .venvs/mineru and its model weights go to .cache/ on first use (./setup.sh, env.sh).
# GPU_LOCK (optional): a lock file other jobs on a shared GPU take with flock; this job then takes it too and waits
# until the GPU memory is free before it starts.
set -uo pipefail
source tables/mineru/env.sh
export MINERU_MODEL_SMALL_BACKEND=torch MINERU_MODEL_VLM_ENGINE=vllm
unset MINERU_API_URL MINERU_API_KEY MINERU_MODEL_VLM_API_KEY
name=$1
shift

wait_free() {  # until less than 2000 MiB of GPU memory is in use, at most 1 h
  local i used
  for i in $(seq 120); do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n 1)
    [ "${used:-99999}" -lt 2000 ] && return 0
    sleep 30
  done
  echo "FAIL: GPU still has ${used} MiB in use after 1 h"
  return 1
}

run() {
  .venvs/mineru/bin/python tables/mineru/mineru_dir.py "$@" || { echo "FAIL $name"; return 1; }
  echo DONE
}

mkdir -p logs
{
  if [ -n "${GPU_LOCK:-}" ]; then
    echo "$(date -u +%FT%TZ) waiting for $GPU_LOCK"
    exec 9>>"$GPU_LOCK"
    flock 9
    echo "$(date -u +%FT%TZ) lock taken"
    wait_free && run "$@"
  else
    run "$@"
  fi
} > "logs/$name.log" 2>&1
