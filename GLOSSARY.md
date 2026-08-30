# Glossary — what every piece of this actually is

Written for someone who knows entry-level programming and none of this stack.

## The layer cake

Each layer talks only to its neighbours. Nearly every problem in this project
was one layer failing to talk to the one below it.

```
  your Python script      <- you write this
  Replicator              <- "give me the data"
  Isaac Sim               <- robotics application
  Omniverse Kit           <- application framework
  OpenUSD                 <- describes the scene
  RTX Renderer            <- turns the scene into pixels
  Vulkan                  <- how software asks the GPU to draw
  NVIDIA driver           <- how the OS talks to the card
  RTX 4090                <- the actual silicon
```

---

## Hardware

**GPU** — a chip with thousands of small processors doing simple maths in
parallel. A CPU has ~8-16 powerful cores; a GPU has thousands of weak ones.

Two core types matter:

- **CUDA cores** — general parallel maths. Every NVIDIA GPU has them.
- **RT cores** — dedicated hardware answering one question: *does this ray of
  light hit this triangle?* Only RTX-class cards have them.

**This is why A100 / H100 / H200 do not work.** They cost far more than a 4090
and are much better at AI training, but they have **no RT cores** — built for
maths, not pictures. Not a power problem; the wrong kind of chip.

**Driver** — software letting the OS talk to the card. `nvidia-smi` reports it.

## Vulkan

**A standard set of function calls for asking a GPU to draw.** A shared language
between your program and the GPU. Alternatives: OpenGL (older), DirectX
(Windows), Metal (Apple). Vulkan is the modern cross-platform one.

Two pieces, and their split cost us hours:

- **Loader** (`libvulkan1`) — knows the Vulkan vocabulary, nothing about your
  specific GPU. A translator who speaks the language but has not met the person.
- **ICD** (Installable Client Driver) — NVIDIA's actual implementation. The
  loader finds it via `/etc/vulkan/icd.d/nvidia_icd.json`, which says "the
  driver is in this library file".

Our failure: `vkCreateInstance: Found no drivers!` The loader was installed, the
JSON was correct, the library existed — but supporting libraries (`libegl1`,
`libglx0`, `libopengl0`) were missing so the ICD could not start. Everything
looked right and nothing worked.

## Rasterization vs ray tracing

- **Rasterization** — for each triangle, find the pixels it covers. Fast,
  approximates lighting with tricks. Traditional games.
- **Ray tracing** — simulate light rays bouncing. Physically accurate, very
  expensive without dedicated hardware. That hardware is the RT cores.

**The Omniverse RTX Renderer ray traces.** Correct for a digital twin: if you
are generating sensor data, light should behave like light.

---

## OpenUSD

**Universal Scene Description**, from Pixar, who needed many artists working on
one film scene at once. Now the standard for 3D interchange. Both a file format
and a live runtime.

Analogy: **a filesystem crossed with the HTML DOM.**

| Term | Meaning | Analogy |
|---|---|---|
| **Stage** | the entire scene | the whole document |
| **Prim** | one thing in it — cube, light, camera ("primitive") | an element / a file |
| **Path** | its address, `/World/EgoCar/body` | a file path |
| **Attribute** | a property: size, colour, intensity | an HTML attribute |
| **Xform** | a prim that positions things; children inherit | a `<div>` you move |
| **Schema** | a prim's *type* — `UsdGeom.Cube` | a class |
| **Applied schema** | extra capability bolted on | a mixin |

Two did real work in our demo:

**Xform hierarchy** — `/World/EgoCar` is an Xform; `body` and `roof` are
children. Move the parent, USD moves the children. The code never touches them.

**Applied schemas** — `add_labels()` attaches `SemanticsLabelsAPI` carrying the
text `"car"`. That is how a grey box becomes semantically a car. Without it a
cube is geometry with no meaning.

**Hydra** sits between USD and the renderer. USD says what exists; Hydra hands
it to a "render delegate". This is why renderers are swappable.

---

## Omniverse

**Not one program — a collection:**

- **Kit** — the application framework. Everything in it is an **extension** (a
  plugin); the log spam at startup is extensions loading.
- **RTX Renderer** — the ray tracer.
- **Replicator** — the synthetic-data toolkit.
- **Nucleus** — a collaboration server for teams sharing USD. Unused here.

**Isaac Sim = Kit + PhysX + RTX sensors + ROS bridge + robot assets.** That is
all "Isaac Sim" means: a Kit app with robotics extensions.

## Replicator

Rendering makes pictures. Replicator gets **data** back out.

- **Render product** — a camera bound to a resolution.
- **Annotator** — extracts information from a render product. `rgb` gives
  pixels; `bounding_box_3d` gives class + position; `semantic_segmentation`
  labels every pixel.
- **Orchestrator** — drives the loop. `rep.orchestrator.step()` = render one
  frame and update all annotators.

That last one caused a silent bug: `world.step()` advances the *simulation* but
never tells Replicator to capture, so the annotator returned an empty array and
the program exited 0 reporting zero objects.

**PhysX** — NVIDIA's physics engine (gravity, collisions, suspension). **We are
not using it.** The car is teleported 0.35 m per frame: an animation, not a
simulation.

---

## The display stack (cloud only)

Linux draws windows with **X11**. A rented server has no monitor, so:

- **Xvfb** — a fake X display in memory. Apps draw into it; nobody sees it.
- **x11vnc** — reads that display, serves it over VNC.
- **websockify** — VNC speaks TCP, browsers speak WebSocket. Translates.
- **noVNC** — a VNC client in JavaScript, running in your browser tab.

`Isaac draws -> Xvfb -> x11vnc -> websockify -> noVNC -> browser`

**None of this exists on your own desktop** — Isaac just opens a window. That is
why LOCAL.md is so much shorter than SETUP.md.

## CARLA and Unreal

**Unreal Engine** is a game engine — a prebuilt system for rendering and running
interactive 3D worlds. **CARLA** is a driving simulator built on it. That is the
only reason Unreal appears anywhere in this project.

**You never write Unreal code.** CARLA ships as a prebuilt binary you run as a
server and drive from Python over a network port. Unreal is an implementation
detail underneath.

## Infrastructure

- **Container** — a packaged filesystem + process isolation. A RunPod "pod" is a
  container with a GPU attached. Its filesystem resets on restart, which is why
  everything important lives in `/workspace`.
- **`/workspace`** — a network-backed volume that persists across restarts. Slow
  for many small files, which is why the install took so long.
- **SSH tunnel** — `ssh -N -L 8080:localhost:8888` forwards a port on your
  machine to a port on the pod, encrypted.
