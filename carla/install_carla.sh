#!/usr/bin/env bash
# Install CARLA alongside Isaac Sim on the same pod.
#
# CARLA is a prebuilt Unreal Engine 4 binary + a Python client library. You do
# NOT write Unreal code and never open the Unreal Editor - you start the server
# and talk to it from Python over TCP (ports 2000-2002).
#
# That TCP-only protocol is why CARLA is EASIER to host on RunPod than Isaac:
# the UDP/WebRTC problem that forced the noVNC setup does not apply.
#
#   bash carla/install_carla.sh
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

CARLA_VERSION="${CARLA_VERSION:-0.9.16}"
DEST="${DEST:-/workspace/carla}"
log(){ echo "[$(date +%H:%M:%S)] $*"; }

log "runtime deps (CARLA targets 22.04; 24.04 needs these explicitly)"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    libomp5 libvulkan1 libsdl2-2.0-0 libxrandr2 libxinerama1 libxcursor1 \
    libpng16-16 libtiff6 libjpeg-turbo8 xdg-user-dirs wget >/dev/null 2>&1 \
  || log "  WARN some deps failed (names differ across Ubuntu releases)"

mkdir -p "$DEST"
if [ -x "$DEST/CarlaUE4.sh" ]; then
    log "CARLA already present at $DEST - skipping ~20GB download"
else
    URL="https://github.com/carla-simulator/carla/releases/download/${CARLA_VERSION}/CARLA_${CARLA_VERSION}.tar.gz"
    log "downloading CARLA ${CARLA_VERSION} (~20GB) from GitHub releases"
    log "  $URL"
    if ! wget -q --show-progress -O "$DEST/carla.tar.gz" "$URL"; then
        log "ERROR download failed. Check the exact asset name at:"
        log "      https://github.com/carla-simulator/carla/releases"
        exit 1
    fi
    log "extracting"
    tar -xzf "$DEST/carla.tar.gz" -C "$DEST" && rm -f "$DEST/carla.tar.gz"
fi

log "python client library"
# Its own venv: CARLA pins numpy differently from Isaac Sim, and sharing one
# environment makes them fight.
python3 -m venv /workspace/carla-venv 2>/dev/null || true
/workspace/carla-venv/bin/pip install -q --upgrade pip
/workspace/carla-venv/bin/pip install -q "carla==${CARLA_VERSION}" numpy pygame \
  || log "  WARN pip carla failed - fall back to the .whl in ${DEST}/PythonAPI/carla/dist/"

cat <<EOM

===========================================================
 CARLA installed at ${DEST}
===========================================================
 Start the server (headless - no display needed):
     ${DEST}/CarlaUE4.sh -RenderOffScreen -carla-rpc-port=2000 &

 Then run the client:
     /workspace/carla-venv/bin/python /workspace/carla_drive.py

 NOTE: CARLA and Isaac Sim both want the whole GPU.
       Run one at a time.
===========================================================
EOM
