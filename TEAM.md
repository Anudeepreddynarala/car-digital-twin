# Team onboarding

Everything needed to pick this up. Read [SETUP.md](SETUP.md) for the full
reasoning; this is the short path to a running system.

## 1. Provision a pod

RunPod, **RTX 4090 / A6000 / A40 / L40S**. Must have RT cores — **A100, H100 and
H200 will not work**, they are compute-only and unsupported by the Omniverse RTX
renderer despite being the priciest options on the menu.

- Template: any Ubuntu 22.04/24.04 image running as **root** (a standard
  PyTorch/Jupyter template is fine — that is what we used)
- Expose **one HTTP port** (we reused 8888, the Jupyter port)
- Container disk 30 GB+, volume 60 GB+ mounted at **`/workspace`**

Python **3.11** must be available (Isaac 5.x requires exactly 3.11), GLIBC 2.35+,
driver 580.65.06+.

## 2. SSH in

RunPod bakes `PUBLIC_KEY` at pod **creation**. Adding a key in Settings later
does nothing for an existing pod, **and restarting does not help** — the
entrypoint re-runs with the same baked value. Use the web terminal:

```bash
mkdir -p ~/.ssh && echo '<your pubkey>' >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
```

## 3. Install

```bash
apt-get update && apt-get install -y \
    xvfb x11vnc fluxbox novnc websockify x11-utils \
    python3.11-venv python3.11-dev libvulkan1 vulkan-tools

# Vulkan must enumerate EXACTLY ONE device. Two ICDs -> Kit refuses to run.
vulkaninfo --summary | grep deviceName

# Everything large goes to /workspace: / is a small overlay AND is wiped on restart
export TMPDIR=/workspace/tmp PIP_CACHE_DIR=/workspace/.pip-cache
mkdir -p $TMPDIR $PIP_CACHE_DIR /workspace/isaac
python3.11 -m venv /workspace/isaac/venv
/workspace/isaac/venv/bin/pip install "isaacsim[all,extscache]==5.1.0" \
    --extra-index-url https://pypi.nvidia.com
```

~30 GB and 30–60 min. **No NGC account or API key needed** — `pypi.nvidia.com`
is unauthenticated. Only the *container* route requires NGC credentials.

## 4. Run

```bash
# GUI in the browser
VNC_PASSWORD='pick-one' bash /workspace/start-isaac-ui.sh
ssh -N -L 8080:localhost:8888 -p <SSH_PORT> root@<POD_IP>   # from your laptop
# -> http://localhost:8080/vnc.html

# visible driving demo
DISPLAY=:99 /workspace/isaac/venv/bin/python /workspace/drive_demo.py

# headless perception (numbers only, much faster)
/workspace/isaac/venv/bin/python /workspace/perception_demo.py --headless
```

In noVNC set **Settings → Scaling Mode → Local Scaling**, or a 1920×1080 desktop
renders 1:1 and you only see part of the window.

## Restarting after a pod stop

`/workspace` **persists** across a stop/start; the container filesystem does not.
So the ~30 GB Isaac Sim install survives, but apt packages (Xvfb, x11vnc, noVNC,
libvulkan1) and `~/.ssh/authorized_keys` are wiped.

One command restores everything and skips the big download:

```bash
VNC_PASSWORD='something' bash <(curl -fsSL https://raw.githubusercontent.com/Anudeepreddynarala/car-digital-twin/main/pod/bootstrap.sh)
```

It detects an existing `/workspace/isaac/venv` and reinstalls only what was lost
(~1 min). On a fresh volume it does the full install instead.

**Note:** a stop/start gives you a **new IP and SSH port**, and your SSH key is
gone from the container. Re-add it via the web terminal (see §2) — RunPod only
injects account keys into pods created *after* the key was added.

## 5. Conventions

- **Write to `/workspace`.** It is the only persistent mount; the container
  filesystem is wiped on restart. The `omniverse://` asset tree in the Content
  browser is read-only (hence the padlock icons) — load from it, never save to it.
- **Stopping a container does not stop billing.** Stop the *pod*.
- Run **one** Isaac instance at a time. Two compete for the GPU and stack
  overlapping windows on the same X display.

## Gotchas, ranked by time lost

| Symptom | Real cause | Fix |
|---|---|---|
| `no suitable CUDA GPU` though `nvidia-smi` is fine | Vulkan **loader** missing | `apt-get install libvulkan1` |
| `Multiple ICDs found for the same GPU` | Two NVIDIA ICDs | Keep `/etc/vulkan/icd.d/` only; do **not** add one under `/usr/share` |
| Annotator returns empty, exit code 0 | `world.step()` never triggers a capture | `rep.orchestrator.step()` |
| Objects present but undetected | Outside the camera's ~47° FOV | Widen FOV, or add radar/LiDAR |
| Viewport is blank but scene is fine | Viewport camera not pointed at anything | Make your own `UsdGeom.Camera` and set it via `get_active_viewport().camera_path`. **`/OmniverseKit_Persp` is not a prim on this stage** — `GetPrimAtPath` returns invalid and your camera code silently no-ops |
| Everything washed out flat white | Lights overexposed | DistantLight ~1200 + DomeLight ~150, not 3500/800 |
| Process dies the moment SSH returns | Backgrounding through SSH gets SIGHUP'd | `setsid nohup … < /dev/null &` — see `pod/run_drive.sh` |
| `docker build` fails on the pod | RunPod pods have no Docker daemon | Build off-pod, or use pip |
| Vulkan finds 0 devices although every NVIDIA lib is mounted and CUDA works | **Driver too old / bad mount.** Seen on 570.195.03 | Redeploy filtering **CUDA 13.0** → driver 580+. Known good: 580.159.04 |
| First `orchestrator.step()` returns nothing | Render product not populated yet | Burn one warmup step |
| ROS 2 bridge error on startup | ROS 2 Jazzy not installed | Harmless; ignore |

## Where the work goes next

Perception currently reads the simulator's **ground truth** — perfect, and
therefore cheating. That is deliberate: it builds the visualisation and gives a
reference to score real sensors against. Next is RTX radar and stereo cameras
producing actual returns, measured against that reference.

The structural blocker is **road content** — Isaac ships none. See the README.
