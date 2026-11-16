# Sourced by setup.sh and run_mineru.sh, from the repository root: every download and cache (MinerU's model weights,
# pip and uv caches) stays in .cache/ of this repository.
export XDG_CACHE_HOME=$PWD/.cache
export UV_CACHE_DIR=$PWD/.cache/uv
export HF_HOME=$PWD/.cache/hf
export MODELSCOPE_CACHE=$PWD/.cache/modelscope
export PIP_CACHE_DIR=$PWD/.cache/pip
export TORCH_HOME=$PWD/.cache/torch
export MINERU_HOME=$PWD/.cache/mineru
export FLASHINFER_WORKSPACE_BASE=$PWD/.cache  # flashinfer (vLLM) otherwise writes ~/.cache/flashinfer
export PATH=$PWD/.venvs/mineru/bin:$PATH  # tools vLLM calls by name (ninja)
