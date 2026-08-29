#!/usr/bin/env bash
pkill -9 -f drive_demo.py 2>/dev/null
sleep 1
rm -f /workspace/drive.log
cd /workspace
export DISPLAY=:99 OMNI_KIT_ACCEPT_EULA=YES ACCEPT_EULA=Y PRIVACY_CONSENT=Y TMPDIR=/workspace/tmp
setsid nohup /workspace/isaac/venv/bin/python -u /workspace/drive_demo.py \
  < /dev/null > /workspace/drive.log 2>&1 &
echo "started pid $!"
