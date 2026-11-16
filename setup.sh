#!/usr/bin/env bash
# Once, after cloning: the two Python environments. Needs uv (https://docs.astral.sh/uv/). uv fetches its own Python
# 3.12, which carries the C headers Triton (vLLM) compiles against; a system Python without its -dev package lacks them.
#   .venv          stages 1 and 3-6 (requirements.txt; rapidocr downloads the PP-OCRv6 small models on first use)
#   .venvs/mineru  MinerU for stages 2 and 3 (tables/mineru/requirements.txt, exact versions; about 8 GB; its model
#                  weights, about 2.5 GB, are downloaded into .cache/ on the first run)
set -euo pipefail
cd "$(dirname "$0")"
source tables/mineru/env.sh
uv venv -q --allow-existing .venv --python 3.12 --managed-python
uv pip install -q --python .venv/bin/python -r requirements.txt
uv venv -q --allow-existing .venvs/mineru --python 3.12 --managed-python
uv pip sync -q --python .venvs/mineru/bin/python tables/mineru/requirements.txt  # exact: also removes anything else
[ -f .env ] || cp .env.example .env
echo "ready; put your Gemini key in .env"
