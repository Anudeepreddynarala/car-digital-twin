# Car Digital Twin — Omniverse on RunPod

## Read this first: the PDF in this folder is not a guide for this project

`renting server with UI.pdf` is a generic "how to rent a VPS with a web control
panel" explainer. It never mentions Omniverse, OpenUSD, Isaac Sim, Kit, or
Nucleus. Its concrete recommendation — a 2-vCPU / 4-GB Ubuntu VPS running
Docker + Portainer — has no GPU and will not run Omniverse at all. Its
"server UI" suggestions (cPanel, Plesk, Webmin, Portainer) are web panels for
*administering a host*; none of them render an Omniverse viewport.

Keep it as background reading on VPS shopping. Do not follow it here.

## The three facts that actually constrain this project

**1. The GPU must have RT cores.**
The Omniverse RTX renderer requires them. A100, H100, and H200 are compute-only
and are *not supported* for Omniverse/Isaac Sim rendering, despite being the
most expensive options on the menu. Use RTX 4090, RTX A6000, A40, or L40S.

**2. Isaac Sim's built-in livestreaming cannot work on RunPod.**
WebRTC livestream needs **UDP 47998**; RunPod's proxy forwards **TCP only**.
This is not a misconfiguration you can fix — NAT port remapping breaks WebRTC's
ICE negotiation for the browser client, the native client, and SSH tunnels
alike. There are multiple open NVIDIA/GitHub issues on exactly this.

The fix is to stop trying to stream: render Isaac to a **virtual X display** and
serve it over a **single HTTP port** with noVNC. No UDP, no ICE, no TURN.

**3. The Omniverse Launcher is dead.** Retired 1 Oct 2025. Any tutorial telling
you to install it is stale. Distribution is now GitHub + NGC containers.

## The build constraint that shapes everything

**RunPod Pods cannot build Docker images.** Pods *are* containers and there is no
Docker daemon inside them — this is a documented RunPod limitation, not a quirk
of your pod. So "copy a Dockerfile up and build it" is not available.

That fact explains the community recipe's Isaac **4.0.0** pin, which looks
arbitrary until you connect it:

| Isaac version | Runs as | Can you install a desktop at runtime? |
|---|---|---|
| 4.0.0 | root | **Yes** — this is why the recipe works |
| 5.1+ / 6.x | UID 1234, non-root, read-only `/usr` | No |

On a platform where you cannot build, and an image that runs unprivileged, there
is no way to add a desktop to Isaac 6.x *on the pod*. The version pin is
load-bearing.

So there are three paths. The one we are actually using is Path C, which only
became visible after inspecting the pod.

---

## Path C — pip install onto a standard root pod  ← **the one we're using**

**Verified working on this hardware.** The insight: the 4.0.0 pin exists because
the *official container* runs unprivileged. A standard RunPod Jupyter/PyTorch
template runs as **root**, so that constraint simply does not apply — `apt-get
install xvfb x11vnc novnc` just works, and Isaac Sim installs from pip.

Two consequences worth stating plainly:

- **No NGC API key needed.** `pypi.nvidia.com` is open, no auth. The registry
  credential that blocks Paths A and B is irrelevant here.
- **Isaac Sim 5.1.0 (Jan 2026)** instead of 4.0.0 (Jun 2024), with no redeploy.

### Verified pod baseline

| Check | Required | This pod |
|---|---|---|
| User | root, to `apt install` | root (uid 0) |
| OS / GLIBC | 2.35+ | Ubuntu 24.04.3, GLIBC 2.39 |
| Python | exactly 3.11 for Isaac 5.x | 3.11 present (system default is 3.12) |
| Driver | 580.65.06+ | 580.159.04 |
| GPU | RT cores | RTX 4090, 24 GB |

### The disk trap

`/` is a **30 GB overlay**. Isaac with `[all,extscache]` will not fit. Everything
large must go to `/workspace`:

```bash
export TMPDIR=/workspace/tmp
export PIP_CACHE_DIR=/workspace/.pip-cache
python3.11 -m venv /workspace/isaac/venv
/workspace/isaac/venv/bin/pip install "isaacsim[all,extscache]==5.1.0" \
  --extra-index-url https://pypi.nvidia.com
```

`/workspace` is also the only persistent mount — the container filesystem is
wiped on restart, so this placement solves capacity and persistence together.

### Start the UI

```bash
VNC_PASSWORD='something-real' bash /workspace/start-isaac-ui.sh
```

Then open `https://<POD_ID>-8888.proxy.runpod.net`.

`pod/start-isaac-ui.sh` serves noVNC on **8888**, taking the port from Jupyter,
because 8888 is the only HTTP port this pod exposes and RunPod's proxy does not
care what is behind it. Adding 8080 instead would require a pod stop.

### Gotcha: SSH keys are baked in at pod creation

RunPod writes `authorized_keys` from a `PUBLIC_KEY` env var fixed when the pod is
**created**. Adding a key in Settings afterward does nothing for an existing pod,
and **restarting does not help** — the entrypoint re-runs with the same baked-in
value. Append it via the web terminal instead:

```bash
mkdir -p ~/.ssh && echo '<your pubkey>' >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
```

---

## Path A — official Isaac 4.0.0 container (fallback)

Isaac Sim 4.0.0, desktop installed at runtime, one HTTP port. Proven recipe,
but two years old and needs an NGC key. Use only if Path C fails.

### A1. Deploy a pod with the right image

Your current pod probably will not work as-is unless it was already deployed
from an Isaac Sim image. Deploy a new one:

- **Image:** `nvcr.io/nvidia/isaac-sim:4.0.0`
  (or the community template `Isaac-Sim-Official`, ID `4qyomso891`)
- **GPU:** RTX 4090, RTX A6000, A40, or L40S.
  **Not** RTX 5090 / RTX PRO 6000 — Blackwell postdates Isaac 4.0.0 and the
  viewport renders permanently grey.
- **Expose HTTP port:** `8080`
- **Container disk:** 60 GB+ (the image alone is ~10 GB compressed)
- **Volume:** 50 GB+ mounted at `/workspace`
- **Environment:**
  - `ACCEPT_EULA=Y`
  - `PRIVACY_CONSENT=Y`
  - `VNC_PASSWORD=<pick a real password>`

`nvcr.io` requires authentication even though the image is free. Add NGC
container-registry credentials in RunPod settings: username is the literal
string `$oauthtoken`, password is your NGC API key from
<https://developer.nvidia.com>.

### A2. Start the desktop

In the pod's web terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/Sa3d-99/runpod_noVNC_isaac_sim/main/bootstrap.sh | bash
```

This downloads the repo to `/workspace/runpod_noVNC_isaac_sim` and runs
`novnc.sh`, which starts Xvfb → fluxbox → x11vnc → websockify → Isaac Sim.
It is a third-party script; it was reviewed and is clean, but it is not NVIDIA's.
To read before running, drop the `| bash`.

`rm -rf` on `/workspace/runpod_noVNC_isaac_sim` runs without confirmation, so do
not put your own work in that directory.

**Set `VNC_PASSWORD`.** Unset, the script runs `x11vnc -nopw` and anyone with
the pod URL gets full mouse-and-keyboard control of the session.

### A3. Open it

`https://<POD_ID>-8080.proxy.runpod.net`

First launch takes several minutes while shaders compile. A grey viewport for
the first few minutes is normal; a *permanently* grey one means a GPU mismatch
(usually Blackwell on 4.0.0).

To restart later without re-bootstrapping:

```bash
cd /workspace/runpod_noVNC_isaac_sim && bash novnc.sh   # start
cd /workspace/runpod_noVNC_isaac_sim && bash stop.sh    # stop
```

---

## Path B — Isaac Sim 6.0.1 (build off-pod, deploy from registry)

Only worth doing once Path A has proven the pod, GPU, and workflow. Starting a
new project on a 2024 Isaac build is a real cost, but so is fighting a toolchain
before you have ever seen the viewport.

Since the pod cannot build, build elsewhere and deploy *from* the result:

1. Build `docker/Dockerfile` off-pod — GitHub Actions (see
   `.github/workflows/build-image.yml`) or any x86_64 Linux box with Docker.
   **Not your Mac:** it is arm64 and Isaac is amd64; emulated cross-build of a
   ~30 GB image is impractical.
2. Push to a registry (GHCR works; your token has `write:packages`).
3. Deploy a RunPod pod from that image, exposing HTTP 8080.

`docker/Dockerfile` installs the desktop as root at **build** time, which
sidesteps the read-only `/usr` problem entirely — the constraint is runtime-only.

**Unverified.** This image has not been built or run yet. Disk is the likely
failure point: the Isaac base is ~10 GB compressed and considerably larger
extracted, which is tight for a standard GitHub-hosted runner even after the
disk-reclaim step in the workflow.

## Next step for the car itself: CAD to OpenUSD

The vehicle model has to become OpenUSD before Omniverse can use it. NVIDIA
ships an open-source converter:

- `NVIDIA-Omniverse/usd-convert-cad` — Python + Kit, converts CAD to OpenUSD
- `NVIDIA-Omniverse/aif-pipeline-samples` — the CAD-to-USD workflow docs,
  including the `cad_convert.py` / `validate.py` / `optimize.py` steps for
  producing SimReady assets

Raw automotive CAD is far too heavy to render interactively — the optimize/decimate
pass is not optional.

## Gotchas

- **Stopping the container does not stop billing.** Stop the *pod* in the RunPod
  console.
- **Put everything in `/workspace`.** On most RunPod templates that is the only
  persistent volume; the container filesystem is wiped on restart.
- **The 10-GB image pull plus build is slow.** Build once, then use RunPod's
  template/snapshot feature so you are not rebuilding every session.
- **Blackwell caution.** RTX 5090 / RTX PRO 6000 work with current Isaac, but
  will render a grey viewport on the older 4.0.0 fallback path.

## Open question

"Digital twin of a car" still splits three ways, and they need different builds:

1. **Photoreal design / configurator** — paint, materials, interior, review renders
2. **Driving / autonomy simulation** — the car as an ego vehicle in a scenario
3. **Engineering / telemetry twin** — physics or live sensor data fed into the scene

Path 1 leans on the CAD-to-USD pipeline above. Path 2 leans on Isaac Sim's
physics and sensors. Path 3 needs a data ingress story that does not exist yet.
