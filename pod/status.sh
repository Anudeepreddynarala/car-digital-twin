#!/usr/bin/env bash
# One-glance status of the pod. Run from the RunPod web terminal or over SSH:
#     bash /workspace/status.sh
echo "=============================================="
echo " POD STATUS  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

echo
echo "--- GPU ---"
nvidia-smi --query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total \
           --format=csv,noheader 2>/dev/null || echo "  nvidia-smi unavailable"

echo
echo "--- Isaac Sim / demos running ---"
FOUND=0
for pat in drive_demo perception_demo isaacsim _sensorapi _lidarprobe; do
  while read -r pid rest; do
    [ -n "$pid" ] && { printf "  [%s] %s\n" "$pid" "$(echo "$rest" | cut -c1-70)"; FOUND=1; }
  done < <(pgrep -af "$pat" 2>/dev/null | grep -v "grep\|status.sh")
done
[ "$FOUND" = "0" ] && echo "  (nothing running)"

echo
echo "--- display stack (needed for the browser UI) ---"
for p in Xvfb x11vnc websockify fluxbox; do
  pgrep -f "$p" >/dev/null && echo "  $p: UP" || echo "  $p: DOWN"
done
(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null) | grep -q ':8888' \
  && echo "  port 8888: LISTENING (browser UI reachable)" \
  || echo "  port 8888: not listening"

echo
echo "--- disk (/workspace is the only persistent mount) ---"
du -sh /workspace/* 2>/dev/null | sort -hr | head -5
echo "  quota:"
df -h /workspace 2>/dev/null | tail -1 | sed 's/^/    /'

echo
echo "--- recent demo output ---"
if [ -f /workspace/drive.log ]; then
  grep -E "^x=" /workspace/drive.log 2>/dev/null | tail -3 | sed 's/^/  /' \
    || echo "  (no detections logged yet)"
else
  echo "  (no drive.log)"
fi

echo
echo "=============================================="
echo " Start the driving demo : /workspace/run_drive.sh"
echo " Start the browser UI   : VNC_PASSWORD=xxx bash /workspace/start-isaac-ui.sh"
echo " Watch a log live       : tail -f /workspace/drive.log"
echo "=============================================="
