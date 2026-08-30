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
    # CARLA is NOT hosted on GitHub releases - those carry no assets, only
    # tiny.carla.org redirect links to a CDN. Resolved target:
    URL="https://carla-releases.b-cdn.net/Linux/CARLA_${CARLA_VERSION}.tar.gz"
    log "downloading CARLA ${CARLA_VERSION} (8.3GB) from the CARLA CDN"
    log "  $URL"
    if ! wget -q --show-progress -O "$DEST/carla.tar.gz" "$URL"; then
        log "ERROR download failed. Resolve the current link from:"
        log "      https://tiny.carla.org/carla-0-9-16-linux"
        exit 1
    fi
    log "extracting"
    tar -xzf "$DEST/carla.tar.gz" -C "$DEST" && rm -f "$DEST/carla.tar.gz"
fi

# Optional: AdditionalMaps (14.8GB) adds Town06/07/11/12/13/15. Town10HD -
# the detailed urban map - is already in the base package, so this is skipped
# by default. Set CARLA_EXTRA_MAPS=1 to fetch it.
if [ "${CARLA_EXTRA_MAPS:-0}" = "1" ] && [ ! -f "$DEST/.extra_maps_done" ]; then
    log "downloading AdditionalMaps (14.8GB)"
    wget -q --show-progress -O "$DEST/maps.tar.gz" \
        "https://carla-releases.b-cdn.net/Linux/AdditionalMaps_${CARLA_VERSION}.tar.gz" \
      && tar -xzf "$DEST/maps.tar.gz" -C "$DEST" && rm -f "$DEST/maps.tar.gz" \
      && touch "$DEST/.extra_maps_done"
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
