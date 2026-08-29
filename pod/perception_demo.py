"""
Rudimentary Tesla-style perception in Isaac Sim.

Builds a small scene of labelled objects, puts a sensor rig in the middle, and
reports every frame:  "<class> at <range> m"  -- e.g. "car at 10.2 m".

Range + class both come from Replicator's bounding_box_3d annotator, which
returns a semantic label and an oriented box per object, so we do not need to
fuse a separate depth pass.

Run on the pod:
    /workspace/isaac/venv/bin/python /workspace/perception_demo.py            # GUI
    /workspace/isaac/venv/bin/python /workspace/perception_demo.py --headless # faster
"""
import argparse
import math

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--frames", type=int, default=600)
args = parser.parse_args()

# SimulationApp MUST be constructed before any other isaacsim/omni import.
from isaacsim import SimulationApp

sim_app = SimulationApp({"headless": args.headless, "renderer": "RayTracedLighting"})

import numpy as np
import omni.replicator.core as rep
from pxr import Usd, UsdGeom, Gf

# Namespaces moved from omni.isaac.* to isaacsim.* in 4.5/5.0. Try new first.
try:
    from isaacsim.core.api import World
    from isaacsim.core.utils.semantics import add_update_semantics
except ImportError:                                    # pragma: no cover
    from omni.isaac.core import World
    from omni.isaac.core.utils.semantics import add_update_semantics

try:
    from isaacsim.util.debug_draw import _debug_draw
    draw = _debug_draw.acquire_debug_draw_interface()
except Exception:
    draw = None

SENSOR_HEIGHT = 1.6          # roughly windscreen height, metres

# (label, x, y, size, colour) -- laid out at known ranges so the readout is
# easy to sanity-check against ground truth.
OBJECTS = [
    ("car",      10.0,   0.0, (4.5, 1.8, 1.5), (0.8, 0.1, 0.1)),
    ("tree",     20.0,   5.0, (1.0, 1.0, 6.0), (0.1, 0.5, 0.1)),
    ("building", 35.0, -12.0, (12.0, 10.0, 18.0), (0.6, 0.6, 0.65)),
    ("person",    7.0,  -3.0, (0.5, 0.4, 1.8), (0.9, 0.7, 0.2)),
    ("car",      25.0,  -8.0, (4.5, 1.8, 1.5), (0.2, 0.2, 0.7)),
    ("tree",     14.0,   9.0, (1.0, 1.0, 5.0), (0.1, 0.45, 0.15)),
]


def build_scene():
    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    stage = world.stage

    for i, (label, x, y, (sx, sy, sz), colour) in enumerate(OBJECTS):
        path = f"/World/obj_{i}_{label}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)
        cube.CreateDisplayColorAttr([Gf.Vec3f(*colour)])

        xform = UsdGeom.Xformable(cube.GetPrim())
        xform.ClearXformOpOrder()
        xform.AddTranslateOp().Set(Gf.Vec3d(x, y, sz / 2.0))
        xform.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))

        # This is what makes the object show up as a *class* in the annotator.
        add_update_semantics(cube.GetPrim(), semantic_label=label, type_label="class")

    return world


def main():
    world = build_scene()

    camera = rep.create.camera(
        position=(0.0, 0.0, SENSOR_HEIGHT),
        rotation=(0.0, 0.0, 0.0),
        focal_length=24.0,
    )
    rp = rep.create.render_product(camera, (1280, 720))

    bbox3d = rep.AnnotatorRegistry.get_annotator("bounding_box_3d")
    bbox3d.attach(rp)

    world.reset()
    for _ in range(30):        # let the annotator warm up
        world.step(render=True)

    print("\n" + "=" * 58)
    print("  PERCEPTION  --  range and class per detected object")
    print("=" * 58)

    for frame in range(args.frames):
        world.step(render=True)
        if frame % 60:                       # report ~once a second
            continue

        data = bbox3d.get_data()
        boxes = data.get("data", [])
        id_to_label = {
            int(k): v.get("class", "?")
            for k, v in data.get("info", {}).get("idToLabels", {}).items()
        }

        detections = []
        for b in boxes:
            # Box centre in world space, via its transform.
            tf = np.array(b["transform"]).reshape(4, 4)
            cx = (float(b["x_min"]) + float(b["x_max"])) / 2.0
            cy = (float(b["y_min"]) + float(b["y_max"])) / 2.0
            cz = (float(b["z_min"]) + float(b["z_max"])) / 2.0
            world_c = np.array([cx, cy, cz, 1.0]) @ tf

            dx = float(world_c[0]) - 0.0
            dy = float(world_c[1]) - 0.0
            dz = float(world_c[2]) - SENSOR_HEIGHT
            rng = math.sqrt(dx * dx + dy * dy + dz * dz)
            detections.append((rng, id_to_label.get(int(b["semanticId"]), "?"),
                               (float(world_c[0]), float(world_c[1]), float(world_c[2]))))

        detections.sort(key=lambda d: d[0])

        print(f"\n-- frame {frame} -- {len(detections)} objects")
        for rng, label, _ in detections:
            bar = "#" * max(1, int(40 - rng))
            print(f"   {label:<10} {rng:6.1f} m  {bar}")

        # Draw a line from the sensor to each detection, in the viewport.
        if draw is not None and detections:
            draw.clear_lines()
            origin = (0.0, 0.0, SENSOR_HEIGHT)
            draw.draw_lines(
                [origin] * len(detections),
                [d[2] for d in detections],
                [(0.1, 0.9, 0.3, 1.0)] * len(detections),
                [2.0] * len(detections),
            )

    sim_app.close()


if __name__ == "__main__":
    main()
