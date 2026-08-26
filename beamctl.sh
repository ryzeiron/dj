#!/bin/sh
# Lanceur macOS / Linux : ./beamctl.sh
cd "$(dirname "$0")" || exit 1
exec python3 -m beamctl --output usb --open "$@"
