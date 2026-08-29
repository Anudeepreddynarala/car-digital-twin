"""
Rudimentary Tesla-style perception in Isaac Sim 5.1.

A sensor rig drives forward through a scene of labelled objects and reports,
every step:   "<class> at <range> m"   e.g.  "car at 10.0 m".

Two things that are easy to get wrong and cost real time:

  1. rep.orchestrator.step() is what drives a capture. world.step(render=True)
     advances the sim but never triggers the annotator, so get_data() returns
     an empty array while the process still exits 0 - a silent no-op.

  2. Isaac 5.1 labels prims with add_labels() (UsdSemantics, applies
     SemanticsLabelsAPI). add_update_semantics() is the legacy call.

Range and class both come from the bounding_box_3d annotator, whose records are
  (semanticId, x_min, y_min, z_min, x_max, y_max, z_max, transform4x4, occlusion)
with the world position in the transform's last row.

Run:
    /workspace/isaac/venv/bin/python /workspace/perception_demo.py --headless
"""
import argparse, math

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--steps", type=int, default=12)
parser.add_argument("--speed", type=float, default=2.0, help="metres per step")
args = parser.parse_args()

from isaacsim import SimulationApp
sim_app = SimulationApp({"headless": args.headless})

import numpy as np
import omni.usd
import omni.replicator.core as rep
from pxr import UsdGeom, UsdLux, Gf
import isaacsim.core.utils.semantics as S

SENSOR_HEIGHT = 1.6

#  label,      x,     y,   (sx,  sy,  sz),   colour
OBJECTS = [
    ("person",  7.0,  -3.0, (0.5, 0.4, 1.8), (0.9, 0.7, 0.2)),
    ("car",    10.0,   0.0, (4.5, 1.8, 1.5), (0.8, 0.1, 0.1)),
    ("tree",   14.0,   9.0, (1.0, 1.0, 5.0), (0.1, 0.45, 0.15)),
    ("tree",   20.0,   5.0, (1.0, 1.0, 6.0), (0.1, 0.5, 0.1)),
    ("car",    25.0,  -8.0, (4.5, 1.8, 1.5), (0.2, 0.2, 0.7)),
    ("building", 35.0, -12.0, (12.0, 10.0, 18.0), (0.6, 0.6, 0.65)),
]


def build_scene(stage):
    UsdLux.DistantLight.Define(stage, "/World/Light").CreateIntensityAttr(3000.0)
    ground = UsdGeom.Plane.Define(stage, "/World/Ground")
    ground.CreateWidthAttr(400.0); ground.CreateLengthAttr(400.0)
    ground.CreateAxisAttr("Z")

    for i, (label, x, y, (sx, sy, sz), colour) in enumerate(OBJECTS):
        prim_path = f"/World/obj_{i}_{label}"
        cube = UsdGeom.Cube.Define(stage, prim_path)
        cube.CreateSizeAttr(1.0)
        cube.CreateDisplayColorAttr([Gf.Vec3f(*colour)])
        xf = UsdGeom.Xformable(cube.GetPrim())
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(x, y, sz / 2.0))
        xf.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))
        # 5.1 API: applies SemanticsLabelsAPI:class
        S.add_labels(cube.GetPrim(), labels=[label], instance_name="class")


def detections_from(annot, sensor_xyz):
    """-> [(range_m, class, (x, y, z)), ...] sorted near to far."""
    data = annot.get_data()
    records = data.get("data", [])
    id_to_label = {
        int(k): v.get("class", "?")
        for k, v in data.get("info", {}).get("idToLabels", {}).items()
    }

    out = []
    for r in records:
        tf = np.array(r["transform"]).reshape(4, 4)
        # local bbox centre -> world, via the transform's translation row
        centre_local = np.array([
            (float(r["x_min"]) + float(r["x_max"])) / 2.0,
            (float(r["y_min"]) + float(r["y_max"])) / 2.0,
            (float(r["z_min"]) + float(r["z_max"])) / 2.0,
            1.0,
        ])
        wx, wy, wz, _ = centre_local @ tf
        d = math.dist((wx, wy, wz), sensor_xyz)
        out.append((d, id_to_label.get(int(r["semanticId"]), "?"), (wx, wy, wz)))

    out.sort(key=lambda t: t[0])
    return out


def main():
    stage = omni.usd.get_context().get_stage()
    build_scene(stage)

    cam = rep.create.camera(position=(0.0, 0.0, SENSOR_HEIGHT), look_at=(50.0, 0.0, 1.0))
    rp = rep.create.render_product(cam, (1280, 720))
    bbox3d = rep.AnnotatorRegistry.get_annotator("bounding_box_3d")
    bbox3d.attach(rp)

    # First capture always comes back empty - the render product is not
    # populated yet. Burn one step before trusting any output.
    rep.orchestrator.step(rt_subframes=4)

    print("\n" + "=" * 62)
    print("  PERCEPTION  --  sensor driving forward along +X")
    print("=" * 62)
    print("  NOTE: camera FOV is ~47 deg, so objects beyond +/-23.5 deg")
    print("  off-axis are NOT detected. That is correct behaviour for a")
    print("  single forward camera - and the reason radar/lidar matter.")

    for step in range(args.steps):
        sensor_x = step * args.speed
        sensor_xyz = (sensor_x, 0.0, SENSOR_HEIGHT)
        with cam:
            rep.modify.pose(position=sensor_xyz, look_at=(sensor_x + 50.0, 0.0, 1.0))

        rep.orchestrator.step(rt_subframes=4)      # <- drives the capture
        dets = detections_from(bbox3d, sensor_xyz)

        print(f"\n-- t={step:02d}  sensor at x={sensor_x:5.1f} m  --  "
              f"{len(dets)} objects")
        for rng, label, _ in dets:
            bar = "#" * max(1, min(40, int(42 - rng)))
            print(f"   {label:<9} {rng:6.1f} m  {bar}")

    sim_app.close()


if __name__ == "__main__":
    main()
