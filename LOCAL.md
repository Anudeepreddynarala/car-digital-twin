# Running on your own desktop

Isaac Sim runs natively on a local machine with an RTX GPU — **no RunPod, no
noVNC, no SSH**. If you have the hardware, this is the easier path: you get a
native window at full frame rate instead of a video stream.

## Requirements

| | Minimum | Notes |
|---|---|---|
| **GPU** | RTX with RT cores | RTX 4080 / 16 GB+. **A100, H100, H200 do NOT work** — no RT cores |
| **VRAM** | 16 GB | 8 GB will run trivial scenes and thrash on real ones |
| **Driver** | 580.65.06+ | `nvidia-smi` to check |
| **OS** | Ubuntu 22.04 / 24.04, or Windows 11 | GLIBC 2.35+ on Linux |
| **Python** | **exactly 3.11** | Isaac 5.x will not install on 3.10 or 3.12 |
| **Disk** | ~40 GB free | ~30 GB install + ~8 GB pip cache |

Consumer cards are fine — an RTX 4090 is what this was built on. A laptop RTX
4070 will run these demos.

## Install

**Linux**

```bash
sudo apt-get install -y python3.11-venv python3.11-dev libvulkan1 vulkan-tools

# must list exactly ONE device - two ICDs and Kit refuses to start
vulkaninfo --summary | grep deviceName

python3.11 -m venv ~/isaac-venv
~/isaac-venv/bin/pip install "isaacsim[all,extscache]==5.1.0" \
    --extra-index-url https://pypi.nvidia.com
```

**Windows 11 (PowerShell)**

```powershell
py -3.11 -m venv $HOME\isaac-venv
$HOME\isaac-venv\Scripts\pip install "isaacsim[all,extscache]==5.1.0" `
    --extra-index-url https://pypi.nvidia.com
```

No NGC account or API key needed — `pypi.nvidia.com` is unauthenticated. The
download is ~8 GB and unpacks to ~30 GB; budget 30–60 minutes.

## Run

```bash
git clone https://github.com/Anudeepreddynarala/car-digital-twin.git
cd car-digital-twin

# visible driving demo - opens a native window
~/isaac-venv/bin/python pod/drive_demo.py

# headless perception - numbers only, much faster
~/isaac-venv/bin/python pod/perception_demo.py --headless
```

First launch takes several minutes compiling shaders. A grey viewport during
that window is normal.

On Windows, swap the interpreter for `$HOME\isaac-venv\Scripts\python.exe`.

## What you can skip versus the cloud path

Everything display-related. `start-isaac-ui.sh`, Xvfb, x11vnc, noVNC,
websockify, the SSH tunnel, and the whole "RunPod's proxy is TCP-only so WebRTC
cannot work" problem are **cloud-only workarounds**. Locally, Isaac opens a
window.

You also skip: the 30 GB overlay trap (`/workspace` redirection), RunPod's
SSH-key-baked-at-creation quirk, and the no-Docker-daemon limitation.

## Still applies locally

- `rep.orchestrator.step()` drives captures. `world.step(render=True)` advances
  the sim but never triggers the annotator — `get_data()` returns empty **and the
  process still exits 0**.
- `/OmniverseKit_Persp` is not a prim. To point the viewport, make your own
  `UsdGeom.Camera` and assign it via `get_active_viewport().camera_path`.
- `add_labels()` is the Isaac 5.1 semantics API; `add_update_semantics()` is legacy.
- Missing `libvulkan1` gives `no suitable CUDA GPU was found` even when
  `nvidia-smi` is perfectly happy.

## Which path should I use?

| | Local desktop | RunPod |
|---|---|---|
| Native window, full frame rate | ✅ | ❌ video stream |
| Needs your own RTX GPU | ✅ | ❌ rent one |
| Setup complexity | low | display stack + tunnel |
| Cost | electricity | hourly |
| Scaling to many parallel runs | ❌ | ✅ |

Have an RTX card? Work locally. Building datasets at scale, or don't have the
hardware? RunPod — see [SETUP.md](SETUP.md).
