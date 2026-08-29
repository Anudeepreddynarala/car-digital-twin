# Car Digital Twin — NVIDIA Omniverse on RunPod

Building an OpenUSD digital twin of a car, running Omniverse on a rented
RTX-class GPU pod.

**Start with [SETUP.md](SETUP.md).** It documents the real constraints of this
setup — the RT-core GPU requirement, why Isaac Sim's WebRTC livestream cannot
work on RunPod, and the noVNC approach that does.

## Layout

| Path | What it is |
|---|---|
| `SETUP.md` | The runbook. Read first. |
| `docker/Dockerfile` | Isaac Sim 6.0.1 + noVNC desktop layer |
| `docker/start-gui.sh` | Xvfb → openbox → x11vnc → noVNC → Isaac Sim |
| `renting server with UI.pdf` | Original reference. **Superseded** — see SETUP.md. |

## Status

- [x] GPU class verified (RTX-class, has RT cores)
- [x] Browser-GUI approach chosen (noVNC over one HTTP port)
- [ ] Image built and running on the pod
- [ ] Car CAD sourced and converted to OpenUSD
- [ ] Twin scope locked (configurator vs. driving sim vs. telemetry)
