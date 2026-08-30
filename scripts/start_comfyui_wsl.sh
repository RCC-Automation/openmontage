#!/usr/bin/env bash
# Start the WSL ComfyUI - the one that runs Wan - in your own terminal.
#
#   wsl -d Ubuntu-24.04
#   bash "$(wslpath "$(pwd)")/scripts/start_comfyui_wsl.sh"      # from the repo
#   COMFY_PORT=8190 bash scripts/start_comfyui_wsl.sh            # a different port
#
# Wan 2.2 runs here and nowhere else: it is 33% faster warm than on Windows, and
# since 2026-08-30 the Wan weights exist only in this filesystem.
# See wiki/comfyui/two-platforms.md.
#
# HSA_ENABLE_DXG_DETECTION is what makes ROCm find the GPU through /dev/dxg.
# WSL has no /dev/kfd, so without it hsa_init fails and there is no GPU at all.
#
# Never run this while the Windows ComfyUI is also up. GPU memory here is system
# RAM - 63.6 GiB total - and an idle second instance holding 41 GiB crashed the
# other one part-way through loading a model.
set -euo pipefail

COMFY_HOME="${COMFY_HOME:-$HOME/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-$HOME/comfy-venv}"
COMFY_PORT="${COMFY_PORT:-8189}"
COMFY_HOST="${COMFY_HOST:-127.0.0.1}"

[ -f "$COMFY_HOME/main.py" ] || {
  echo "No ComfyUI at $COMFY_HOME - set COMFY_HOME to its directory." >&2; exit 1; }
[ -f "$COMFY_VENV/bin/activate" ] || {
  echo "No virtualenv at $COMFY_VENV - set COMFY_VENV." >&2; exit 1; }

export HSA_ENABLE_DXG_DETECTION=1

if command -v curl >/dev/null && curl -sf -o /dev/null --max-time 3 \
     "http://127.0.0.1:8188/system_stats" 2>/dev/null; then
  echo "WARNING: something is answering on 8188 - the Windows ComfyUI may be running." >&2
  echo "         Running both at once has crashed the backend. Ctrl-C now to stop." >&2
  sleep 5
fi

echo "ComfyUI (WSL, ROCm) on http://${COMFY_HOST}:${COMFY_PORT}  -  Ctrl-C to stop"
echo "Wan runs here. LTX, stills and the VRGDG bridge run on Windows."
cd "$COMFY_HOME"
# shellcheck disable=SC1091
source "$COMFY_VENV/bin/activate"
exec python main.py --listen "$COMFY_HOST" --port "$COMFY_PORT" "$@"
