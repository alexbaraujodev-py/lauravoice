#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import faster_whisper' 2>/dev/null; then
  laura_python="$PWD/.venv/bin/python"
elif [[ -x ../Falar/.venv/bin/python ]] && ../Falar/.venv/bin/python -c 'import faster_whisper' 2>/dev/null; then
  laura_python="$PWD/../Falar/.venv/bin/python"
else
  printf 'Execute primeiro: bash instalar_local.sh\n' >&2
  exit 1
fi
exec "$laura_python" laura_voice.py "$@"
