#!/usr/bin/env bash
# Bring up: Xvfb -> openbox -> x11vnc -> websockify/noVNC -> Isaac Sim
set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-99}"
SCREEN_RES="${SCREEN_RES:-1920x1080x24}"
NOVNC_PORT="${NOVNC_PORT:-8080}"
VNC_PASSWORD="${VNC_PASSWORD:-}"

export DISPLAY=":${DISPLAY_NUM}"

log() { echo "[start-gui] $*"; }

cleanup() {
  log "shutting down..."
  kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- 1. virtual display -----------------------------------------------------
log "starting Xvfb on ${DISPLAY} at ${SCREEN_RES}"
Xvfb "${DISPLAY}" -screen 0 "${SCREEN_RES}" \
     -ac +extension GLX +extension RANDR +render -noreset &

for i in $(seq 1 30); do
  if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then break; fi
  [ "$i" -eq 30 ] && { log "ERROR: Xvfb did not come up"; exit 1; }
  sleep 1
done
log "Xvfb ready"

# --- 2. window manager ------------------------------------------------------
# Without a WM, Isaac Sim's dialogs and menus have no decorations and can end up
# unclickable / stacked on top of each other.
openbox --sm-disable &
sleep 1

# --- 3. VNC server ----------------------------------------------------------
X11VNC_ARGS=(-display "${DISPLAY}" -forever -shared -noxdamage -rfbport 5900)

if [ -n "${VNC_PASSWORD}" ]; then
  mkdir -p /root/.vnc
  x11vnc -storepasswd "${VNC_PASSWORD}" /root/.vnc/passwd >/dev/null 2>&1
  X11VNC_ARGS+=(-rfbauth /root/.vnc/passwd)
  log "VNC password auth ENABLED"
else
  X11VNC_ARGS+=(-nopw)
  log "WARNING: no VNC_PASSWORD set - anyone with the pod URL can control this session"
fi

x11vnc "${X11VNC_ARGS[@]}" &
sleep 2

# --- 4. noVNC over a single HTTP port ---------------------------------------
log "serving noVNC on :${NOVNC_PORT}"
websockify --web=/usr/share/novnc "${NOVNC_PORT}" localhost:5900 &
sleep 1

# --- 5. Isaac Sim -----------------------------------------------------------
LAUNCHER=""
for candidate in \
    /isaac-sim/runapp.sh \
    /isaac-sim/isaac-sim.sh \
    /isaac-sim/isaac-sim.selector.sh; do
  if [ -x "${candidate}" ]; then LAUNCHER="${candidate}"; break; fi
done

if [ -z "${LAUNCHER}" ]; then
  log "ERROR: no Isaac Sim launcher found under /isaac-sim. Contents:"
  ls -la /isaac-sim 2>/dev/null || log "  (/isaac-sim does not exist)"
  log "GUI is still up on :${NOVNC_PORT} - open a terminal there and launch manually."
  wait
fi

log "launching Isaac Sim via ${LAUNCHER}"
"${LAUNCHER}" --allow-root || {
  log "Isaac Sim exited. Desktop stays up so you can debug via noVNC."
  wait
}

wait
