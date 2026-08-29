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

## Why we build our own image

The known-good community recipe pins **Isaac Sim 4.0.0**, because 5.x/6.x run as
an unprivileged user with a read-only `/usr` — you cannot `apt-get install` a
desktop into a *running* 6.x container.

That limit only applies at runtime. At **build** time we are root, so
`docker/Dockerfile` layers the desktop onto the current **6.0.1** image instead
of starting a new project two years behind.

Tradeoff: the 4.0.0 recipe is battle-tested and ours is not. If the build fights
you, falling back to 4.0.0 is a legitimate move, not a defeat.

## Setup

### 1. NGC account and API key (free)

The Isaac Sim container is free but **gated behind authentication**.

1. Sign up at <https://developer.nvidia.com> and generate an NGC API key.
2. On the pod, log in to the registry. The username is the literal
   string `$oauthtoken` — not your email:

```bash
docker login nvcr.io
# Username: $oauthtoken
# Password: <your NGC API key>
```

### 2. Expose an HTTP port on the pod

In the RunPod console, add **8080** as an exposed **HTTP** port. If the pod is
already running you may need to stop it to edit ports. RunPod will then serve it
at `https://<POD_ID>-8080.proxy.runpod.net`.

Do **not** bother exposing 47998/UDP. It will not work.

### 3. Build and run

Copy `docker/` to the pod (`/workspace/docker`), then:

```bash
cd /workspace/docker
docker build -t car-twin:latest .

docker run --gpus all -d --name car-twin \
  -p 8080:8080 \
  -e ACCEPT_EULA=Y \
  -e PRIVACY_CONSENT=Y \
  -e VNC_PASSWORD='pick-a-real-password' \
  -v /workspace/assets:/workspace/assets \
  car-twin:latest
```

`ACCEPT_EULA=Y` accepts the NVIDIA Isaac Sim license. Set `VNC_PASSWORD` —
without it the desktop has **no authentication**, and the proxy URL is the only
thing standing between your session and the internet.

### 4. Open it

Browse to `https://<POD_ID>-8080.proxy.runpod.net`. First launch takes several
minutes — Isaac compiles shaders before the viewport appears. A grey or black
viewport for the first few minutes is expected; a *permanently* grey viewport
means a GPU/driver mismatch.

Watch progress with `docker logs -f car-twin`.

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
