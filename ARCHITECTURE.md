# How this actually works

What the code really does — including the parts the demo *looks* like it does
but doesn't.

## Unreal Engine is not involved

Zero references in any code. **Omniverse Kit is NVIDIA's own application
framework**, built on OpenUSD with the RTX renderer. It shares no lineage with
Unreal.

Unreal is relevant only as the alternative: **CARLA is built on Unreal Engine 4.**
If you switch to CARLA for road content, you are running UE4 and its renderer.
Choosing Omniverse means no Unreal anywhere in the stack.

## OpenUSD is not a file format here — it is the scene

Every object is a USD prim, created through the `pxr` API:

```python
cube = UsdGeom.Cube.Define(stage, "/World/obj_1_car")
cube.CreateSizeAttr(1.0)
xf = UsdGeom.Xformable(cube.GetPrim())
xf.AddTranslateOp().Set(Gf.Vec3d(30, 0, 0.75))
```

Four USD concepts do real work:

**Stage** — the live scene graph, via `omni.usd.get_context().get_stage()`. Not a
file on disk; the graph Isaac operates on.

**Prims and paths** — every object is addressed like a filesystem:
`/World/EgoCar/body`.

**Xform hierarchy** — how the car moves as one object. `/World/EgoCar` is an
`Xform`; `body` and `roof` are children. Setting a translate op on the *parent*
moves both children. USD composition does this, not application code.

**Applied schemas** — `add_labels()` applies `SemanticsLabelsAPI:class`, which is
how a grey cube becomes semantically "a car". The label is metadata on the prim,
read later by the annotator.

## The sensor chain

There is no "sensor object". A sensor is a three-stage pipeline:

```python
cam = rep.create.camera(position=..., look_at=...)    # 1. a USD Camera prim
rp  = rep.create.render_product(cam, (1280, 720))     # 2. camera + resolution
bbox3d = rep.AnnotatorRegistry.get_annotator("bounding_box_3d")
bbox3d.attach(rp)                                      # 3. extracts data from it
```

Full path from scene to Python:

```
USD Stage  (prims + semantic labels)
      |
Hydra render delegate
      |
RTX renderer          <- Vulkan, RT cores, ray traced
      |
Render Product        <- camera bound to a resolution
      |
Annotator             <- bbox3d / rgb / segmentation / depth
      |
NumPy array
```

`rep.orchestrator.step()` drives this entire chain for one frame. This is exactly
why `world.step(render=True)` yields nothing: it advances the simulation but
never pulls this pipeline.

**Which annotator you pick is the whole game.** `bounding_box_3d` reads the scene
graph and semantic labels — it never looks at a pixel. `rgb` returns actual
rendered pixels. That is the difference between ground truth and sensing.

## What makes this genuinely Omniverse

- **OpenUSD as interchange** — the scene opens in Blender, Houdini, Maya, or any
  USD tool
- **RTX renderer** — physically based ray tracing on RT cores. This is why
  A100/H100/H200 fail: no RT cores, no renderer. A rasterizer would not care.
- **Replicator** — NVIDIA's synthetic-data framework: render products,
  annotators, domain randomization, writers
- **Isaac Sim** — an Omniverse Kit app plus robotics extensions (PhysX, RTX
  sensors, ROS bridge)

## What is NOT real yet

**There is no physics.** The car moves by `car_move.Set(Gf.Vec3d(x, 0, 0))` —
teleported 0.35 m per frame. PhysX is never initialised: no rigid body, no
collider, no gravity. It is an animation, not a simulation. Real dynamics means a
PhysX vehicle with suspension, tyres and a drivetrain.

**The sensors are ground truth, not sensing.** See above.

**The assets are primitive cubes.** A "car" is a stretched box with a smaller box
on top.

| Layer | Real? |
|---|---|
| OpenUSD scene graph | yes — genuine prims, hierarchy, applied schemas |
| RTX ray-traced rendering | yes — Vulkan + RT cores |
| Semantic labelling | yes — `SemanticsLabelsAPI` |
| Replicator pipeline | yes — render products, annotators, orchestrator |
| Sensors | **no** — ground-truth annotator |
| Vehicle dynamics | **no** — no physics at all |
| Assets | **no** — primitive cubes |

The top four are the hard infrastructure and they work. The bottom three are the
next three pieces of work, and they are independent — pick any order.

## Next, concretely

1. **Real sensors** — RTX LiDAR and RTX Radar prims producing ray-traced returns,
   plus the `rgb` annotator for actual camera pixels. Score them against the
   `bounding_box_3d` ground truth already in place.
2. **Physics** — a PhysX vehicle so the car has dynamics instead of being
   teleported.
3. **Assets and road content** — the structural blocker. Isaac ships no drivable
   roads. See the README.
