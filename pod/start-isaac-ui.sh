#!/usr/bin/env bash
# Path C: Isaac Sim (pip) + noVNC on a standard root RunPod pod.
#
# Chain: Xvfb -> fluxbox -> x11vnc -> websockify/noVNC -> Isaac Sim GUI
# Serves on ONE HTTP port, because RunPod's proxy is TCP-only and Isaac's
# built-in WebRTC livestream needs UDP 47998. See SETUP.md.
set -uo pipefail

VENV=/workspace/isaac/venv
DISPLAY_NUM="${DISPLAY_NUM:-99}"
SCREEN_RES="${SCREEN_RES:-1920x1080x24}"
WEB_PORT="${WEB_PORT:-8888}"          # the only HTTP port RunPod exposes here
VNC_PASSWORD="${VNC_PASSWORD:-}"
LOG=/workspace/isaac-ui.log

export DISPLAY=":${DISPLAY_NUM}"
export OMNI_KIT_ACCEPT_EULA=YES
export ACCEPT_EULA=Y
export PRIVACY_CONSENT=Y

log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# --- free the port ----------------------------------------------------------
# Jupyter owns 8888 on this template. RunPod's proxy does not care what is
# behind the port, so we take it over.
if [ "$WEB_PORT" = "8888" ] && pgrep -f jupyter >/dev/null; then
  log "stopping jupyter to free :8888"
  pkill -f jupyter || true
  sleep 2
fi

pkill -f "Xvfb ${DISPLAY}" 2>/dev/null || true
pkill -f "websockify.*${WEB_PORT}" 2>/dev/null || true
sleep 1

# --- 1. virtual display -----------------------------------------------------
log "Xvfb ${DISPLAY} @ ${SCREEN_RES}"
Xvfb "${DISPLAY}" -screen 0 "${SCREEN_RES}" -ac +extension GLX +extension RANDR +render -noreset \
  >>"$LOG" 2>&1 &

for i in $(seq 1 30); do
  xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && { log "ERROR: Xvfb never came up"; exit 1; }
  sleep 1
done
log "Xvfb ready"

# --- 2. window manager ------------------------------------------------------
# Without a WM, Kit's dialogs have no decorations and stack unclickably.
fluxbox >>"$LOG" 2>&1 &
sleep 1

# --- 3. VNC -----------------------------------------------------------------
ARGS=(-display "${DISPLAY}" -forever -shared -noxdamage -rfbport 5900 -localhost)
if [ -n "${VNC_PASSWORD}" ]; then
  mkdir -p /root/.vnc
  x11vnc -storepasswd "${VNC_PASSWORD}" /root/.vnc/passwd >/dev/null 2>&1
  ARGS+=(-rfbauth /root/.vnc/passwd)
  log "VNC auth enabled"
else
  ARGS+=(-nopw)
  log "WARNING: no VNC_PASSWORD - anyone with the pod URL controls this session"
fi
x11vnc "${ARGS[@]}" >>"$LOG" 2>&1 &
sleep 2

# --- 4. noVNC ---------------------------------------------------------------
log "noVNC on :${WEB_PORT}"
websockify --web=/usr/share/novnc "${WEB_PORT}" localhost:5900 >>"$LOG" 2>&1 &
sleep 1

# --- 5. Isaac Sim -----------------------------------------------------------
if [ ! -x "${VENV}/bin/isaacsim" ]; then
  log "ERROR: ${VENV}/bin/isaacsim missing - is the pip install finished?"
  log "Desktop is up on :${WEB_PORT} anyway; open a terminal there to debug."
  wait
fi

log "launching Isaac Sim (first run compiles shaders - several minutes)"
"${VENV}/bin/isaacsim" isaacsim.exp.full --allow-root >>"$LOG" 2>&1 &

log "READY -> https://<POD_ID>-${WEB_PORT}.proxy.runpod.net"
wait
