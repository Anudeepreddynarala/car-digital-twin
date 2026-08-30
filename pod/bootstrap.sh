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

log "STEP 2/5  driver + Vulkan check"

# Driver check FIRST - it is instant, and a too-old driver is the most common
# cause of the Vulkan failure below. Verified working: 580.159.04.
# Verified BROKEN: 570.195.03 (all libs present, CUDA fine, vkCreateInstance
# still fails inside the driver). Filter for CUDA 13.0 when deploying to get 580+.
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
DRV_MAJOR=${DRV%%.*}
log "  driver: ${DRV:-unknown}"
if [ -n "$DRV_MAJOR" ] && [ "$DRV_MAJOR" -lt 580 ] 2>/dev/null; then
    log "  WARNING: driver $DRV is below 580. Isaac Sim 5.1 wants 580.65.06+."
    log "           Driver 570 has been observed to fail Vulkan init on RunPod"
    log "           even with a complete library set. If the check below fails,"
    log "           redeploy the pod filtering for CUDA 13.0 (-> driver 580+)."
fi

# Must be exactly ONE device. The NVIDIA ICD already ships at /etc/vulkan/icd.d/
# - do NOT add another under /usr/share, or Kit refuses to start on duplicates.
N=$(vulkaninfo --summary 2>/dev/null | grep -c "deviceName"); N=${N:-0}
vulkaninfo --summary 2>/dev/null | grep -E "deviceName|apiVersion" | head -2
if [ "$N" -eq 1 ]; then
    log "  OK - exactly one Vulkan device"
elif [ "$N" -eq 0 ]; then
    log "  ERROR - no Vulkan device. Isaac will fail with 'no suitable CUDA GPU'."
    log ""
    log "  Diagnose in this order:"
    log "    1. nvidia-smi                      - is there a GPU at all?"
    log "    2. ls /etc/vulkan/icd.d/           - is the NVIDIA ICD present?"
    log "    3. ldconfig -p | grep libvulkan    - is the loader installed?"
    log "    4. vulkaninfo --summary            - read the actual loader error"
    log ""
    log "  If everything above looks CORRECT and it still fails, the driver"
    log "  mount on this host is broken. Do not keep debugging - redeploy the"
    log "  pod filtering for CUDA 13.0 to get driver 580+."
    log "  Known good: 580.159.04.  Known bad: 570.195.03."
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
