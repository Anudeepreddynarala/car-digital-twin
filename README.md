# Car Digital Twin — NVIDIA Omniverse / Isaac Sim on RunPod

Software-in-the-loop digital twin of a car: the vehicle and all its sensors live
inside Omniverse. A sensor rig drives through a labelled scene and reports what
it sees — **class + range per object** ("car at 10 m, tree at 20 m") — as the
foundation for a Tesla-style perception stack.

**Status: working.** Isaac Sim 5.1.0 runs on a RunPod RTX 4090, GUI in the
browser, perception validated against ground truth.

---

## Start here

| If you want to… | Read |
|---|---|
| Stand up the pod from scratch | **[SETUP.md](SETUP.md)** |
| Understand *why* it is built this way | [SETUP.md § constraints](SETUP.md) |
| Just run something | [Quick start](#quick-start) below |

## Quick start

Assumes a pod already provisioned per [SETUP.md](SETUP.md).

```bash
# 1. browser GUI  (serves noVNC on the pod's one HTTP port)
VNC_PASSWORD='pick-one' bash /workspace/start-isaac-ui.sh

# 2. tunnel it to localhost (encrypted; the RunPod proxy is plain HTTP)
ssh -N -L 8080:localhost:8888 -p <SSH_PORT> root@<POD_IP>
#    -> http://localhost:8080/vnc.html

# 3. watch a car drive and detect objects, in the GUI
DISPLAY=:99 /workspace/isaac/venv/bin/python /workspace/drive_demo.py

# 4. or headless, for numbers only (much faster)
/workspace/isaac/venv/bin/python /workspace/perception_demo.py --headless
```

## What's here

| Path | What it is |
|---|---|
| `SETUP.md` | Full runbook + every constraint that bit us |
| `pod/start-isaac-ui.sh` | Xvfb → fluxbox → x11vnc → noVNC → Isaac Sim |
| `pod/drive_demo.py` | **Visible** demo: car drives, chase cam, live detections |
| `pod/perception_demo.py` | Headless: range + class per object, validated |
| `docker/` | Path B only — building an image off-pod. Not used. |
| `renting server with UI.pdf` | Original reference. **Superseded**, see SETUP.md |

## Verified working

- Isaac Sim **Full 5.1.0**, RTX - Real-Time renderer
- **RTX 4090**, driver 580.159.04, reported in-app as `1.1 GiB used, 21.0 GiB available`
- **118 FPS** / 8.4 ms frame time in the browser GUI
- Perception validated: sensor at x=2 m reports a car placed at x=10 m as **8.0 m**;
  x=6 → 4.1 m; x=10 → 0.9 m; object drops out once passed

## Roadmap

- [x] Pod, GPU, Vulkan, Isaac Sim, browser GUI
- [x] Range + class per object (ground-truth annotator)
- [x] Visible driving demo with chase camera
- [ ] RTX radar + stereo cameras, compared against ground truth
- [ ] YOLO on the camera feed (PyTorch 2.7 already installed)
- [ ] Traffic signs / signals / lanes — **blocked on road content**, see below

### The one structural risk

Isaac Sim ships **no drivable road content** — its environments are warehouses,
kitchens and hospital corridors. Signs, signals and lane markings need a scene
that contains them. Options, roughly by effort: hand-build a test road; buy
third-party SimReady assets; import OpenDRIVE (community, unofficial); or run
**CARLA** for scenario content and keep Isaac for sensor fidelity.

CARLA is free (MIT; assets CC-BY) and is *easier* to host here than Isaac —
its client-server protocol is plain TCP, so the UDP problem below does not apply.
The tradeoff is fidelity: CARLA's radar is explicitly a non-raytraced placeholder
and its LiDAR is plain ray-casting, where Isaac's RTX sensors are physically based.

## Three things that will waste your day if you don't know them

1. **RunPod pods cannot build Docker images** — no daemon inside. Build off-pod
   and deploy *from* the image, or install with pip as we do.
2. **"no suitable CUDA GPU" means the Vulkan *loader* is missing**, not the
   driver. `apt-get install libvulkan1`. Do not add a second ICD — the NVIDIA one
   already exists at `/etc/vulkan/icd.d/`, and two makes Kit error on duplicates.
3. **`rep.orchestrator.step()` drives captures.** `world.step(render=True)`
   advances the sim but never triggers the annotator, so `get_data()` returns an
   empty array *and the process still exits 0*. Assert on content, not exit code.

Full detail in [SETUP.md](SETUP.md).
