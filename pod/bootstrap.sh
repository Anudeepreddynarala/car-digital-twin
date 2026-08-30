#!/usr/bin/env bash
# One-command restore after a RunPod stop/start.
#
# /workspace PERSISTS across a pod stop; the container filesystem does NOT.
# So the ~30GB Isaac Sim install survives, but apt packages are gone.
# This reinstalls only what was lost, then starts the UI.
#
#   curl -fsSL https://raw.githubusercontent.com/Anudeepreddynarala/car-digital-twin/main/pod/bootstrap.sh | bash
#
# Env: VNC_PASSWORD=... to set the desktop password (strongly recommended)
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

VENV=/workspace/isaac/venv
log(){ echo "[$(date +%H:%M:%S)] $*"; }

log "STEP 1/5  apt packages (lost on restart - these live on the container fs)"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    xvfb x11vnc fluxbox novnc websockify x11-utils xterm imagemagick \
    python3.11-venv python3.11-dev libvulkan1 vulkan-tools \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 >/dev/null 2>&1
ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html
log "  apt done"

log "STEP 2/5  Vulkan check"
# Must be exactly ONE device. The NVIDIA ICD already ships at /etc/vulkan/icd.d/
# - do NOT add another under /usr/share, or Kit refuses to start on duplicates.
N=$(vulkaninfo --summary 2>/dev/null | grep -c "deviceName" || echo 0)
vulkaninfo --summary 2>/dev/null | grep -E "deviceName|apiVersion" | head -2
if [ "$N" -eq 1 ]; then
    log "  OK - exactly one Vulkan device"
elif [ "$N" -eq 0 ]; then
    log "  ERROR - no Vulkan device. Isaac will fail with 'no suitable CUDA GPU'."
    log "          Check the pod actually has a GPU: nvidia-smi"
    exit 1
else
    log "  ERROR - $N devices. Duplicate ICDs; Kit will refuse to start."
    log "          ls /etc/vulkan/icd.d/ /usr/share/vulkan/icd.d/ and remove the extra."
    exit 1
fi

log "STEP 3/5  Isaac Sim"
if [ -x "${VENV}/bin/isaacsim" ]; then
    log "  found existing install at ${VENV} - skipping the 30GB download"
    "${VENV}/bin/python" -c "import isaacsim" 2>/dev/null \
        && log "  import OK" || log "  (import check inconclusive; normal outside a Kit app)"
else
    log "  no install found - this is a fresh volume, installing (~30GB, 30-60 min)"
    export TMPDIR=/workspace/tmp PIP_CACHE_DIR=/workspace/.pip-cache
    mkdir -p "$TMPDIR" "$PIP_CACHE_DIR" /workspace/isaac
    python3.11 -m venv "${VENV}"
    "${VENV}/bin/pip" install -q --upgrade pip setuptools wheel
    "${VENV}/bin/pip" install "isaacsim[all,extscache]==5.1.0" \
        --extra-index-url https://pypi.nvidia.com
fi

log "STEP 4/5  demo scripts"
cd /workspace
for f in start-isaac-ui.sh run_drive.sh drive_demo.py perception_demo.py; do
    if [ ! -f "/workspace/$f" ]; then
        curl -fsSL -o "/workspace/$f" \
          "https://raw.githubusercontent.com/Anudeepreddynarala/car-digital-twin/main/pod/$f" \
          && log "  fetched $f" || log "  WARN could not fetch $f"
    fi
done
chmod +x /workspace/*.sh 2>/dev/null

log "STEP 5/5  starting the browser UI"
if [ -z "${VNC_PASSWORD:-}" ]; then
    log "  WARNING: VNC_PASSWORD unset - the desktop will have NO auth."
    log "           Re-run as: VNC_PASSWORD='something' bash bootstrap.sh"
fi
setsid nohup env VNC_PASSWORD="${VNC_PASSWORD:-}" /workspace/start-isaac-ui.sh \
    < /dev/null > /workspace/ui-boot.log 2>&1 &

sleep 12
if (ss -lnt 2>/dev/null || netstat -lnt) | grep -q ':8888'; then
    log "  noVNC listening on 8888"
else
    log "  WARN noVNC not listening yet - check /workspace/isaac-ui.log"
fi

cat <<EOM

===========================================================
 READY
===========================================================
 Browser UI : the pod's port-8888 HTTP link, or tunnel it:
     ssh -N -L 8080:localhost:8888 -p <SSH_PORT> root@<POD_IP>
     -> http://localhost:8080/vnc.html

 Drive demo : /workspace/run_drive.sh
 Headless   : ${VENV}/bin/python /workspace/perception_demo.py --headless
===========================================================
EOM
