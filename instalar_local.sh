#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if command -v uv >/dev/null 2>&1; then
  test -x .venv/bin/python || uv venv .venv --python python3
  uv pip install --python .venv/bin/python -r requirements-local.txt
else
  test -x .venv/bin/python || python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-local.txt
fi
mkdir -p models
.venv/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("base", device="cpu", compute_type="int8")'
(cd models && ../.venv/bin/python -m piper.download_voices pt_BR-cadu-medium)
printf '\nInstalação concluída. Inicie Ollama (porta 11434) ou LM Studio (porta 1234).\n'
printf 'Ollama: bash iniciar_local.sh --server http://127.0.0.1:11434/v1 --model NOME_DO_MODELO\n'
printf 'LM Studio: bash iniciar_local.sh --server http://127.0.0.1:1234/v1\n'
