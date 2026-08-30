"""
Measure range and size from a DEPTH CAMERA, scored against ground truth.

Uses only annotators verified working on this build:
    distance_to_camera     -> metres per pixel, measured off scene geometry
    semantic_segmentation  -> class per pixel
    bounding_box_3d        -> ground truth, for scoring only

This is real measurement, not the simulator handing over answers: depth is
rendered from geometry, then back-projected through the camera intrinsics into
a point cloud, and range/size are computed from those points.

    /workspace/isaac/venv/bin/python /workspace/depth_measure.py --headless
"""
import argparse, json, math

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--width", type=int, default=1280)
parser.add_argument("--height", type=int, default=720)
parser.add_argument("--focal", type=float, default=24.0)      # mm
parser.add_argument("--aperture", type=float, default=20.955) # mm, Kit default
args = parser.parse_args()

from isaacsim import SimulationApp
sim_app = SimulationApp({"headless": args.headless})

import numpy as np
import omni.usd
import omni.replicator.core as rep
from pxr import UsdGeom, UsdLux, Gf
import isaacsim.core.utils.semantics as S

SENSOR_H = 1.6

#  label,      x,     y,  (length, width, height)
TARGETS = [
    ("car",      12.0,  0.0, (4.5, 1.8, 1.5)),
    ("person",    8.0, -2.0, (0.5, 0.4, 1.8)),
    ("tree",     18.0,  3.5, (1.2, 1.2, 5.0)),
    ("car",      25.0, -5.0, (4.5, 1.8, 1.5)),
    ("building", 38.0,  9.0, (10.0, 8.0, 12.0)),
]


def build_scene(stage):
    UsdLux.DistantLight.Define(stage, "/World/Sun").CreateIntensityAttr(1500.0)
    UsdLux.DomeLight.Define(stage, "/World/Sky").CreateIntensityAttr(200.0)
    g = UsdGeom.Plane.Define(stage, "/World/Ground")
    g.CreateWidthAttr(400.0); g.CreateLengthAttr(400.0); g.CreateAxisAttr("Z")
    g.CreateDisplayColorAttr([Gf.Vec3f(0.2, 0.2, 0.22)])
    S.add_labels(g.GetPrim(), labels=["ground"], instance_name="class")

    truth = {}
    for i, (label, x, y, (sx, sy, sz)) in enumerate(TARGETS):
        c = UsdGeom.Cube.Define(stage, f"/World/t{i}_{label}")
        c.CreateSizeAttr(1.0)
        c.CreateDisplayColorAttr([Gf.Vec3f(0.7, 0.3, 0.3)])
        xf = UsdGeom.Xformable(c.GetPrim()); xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(x, y, sz / 2.0))
        xf.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))
        S.add_labels(c.GetPrim(), labels=[label], instance_name="class")
        # range to the NEAREST FACE - what a depth sensor actually sees
        truth.setdefault(label, []).append({
            "label": label, "centre": (x, y, sz / 2.0), "size": (sx, sy, sz),
            "range": round(math.dist((x - sx / 2.0, y, sz / 2.0),
                                     (0.0, 0.0, SENSOR_H)), 2),
        })
    return truth


def main():
    stage = omni.usd.get_context().get_stage()
    truth = build_scene(stage)

    cam = rep.create.camera(position=(0.0, 0.0, SENSOR_H),
                            look_at=(60.0, 0.0, 1.0),
                            focal_length=args.focal)
    rp = rep.create.render_product(cam, (args.width, args.height))

    depth = rep.AnnotatorRegistry.get_annotator("distance_to_camera")
    seg   = rep.AnnotatorRegistry.get_annotator("semantic_segmentation")
    gt    = rep.AnnotatorRegistry.get_annotator("bounding_box_3d")
    for a in (depth, seg, gt):
        a.attach(rp)

    for _ in range(8):                      # first capture is always empty
        rep.orchestrator.step(rt_subframes=8)

    D = np.asarray(depth.get_data(), dtype=np.float64)
    sd = seg.get_data()
    Sg = np.asarray(sd["data"]) if isinstance(sd, dict) else np.asarray(sd)
    id2label = {}
    if isinstance(sd, dict):
        id2label = {int(k): v.get("class", "?")
                    for k, v in sd.get("info", {}).get("idToLabels", {}).items()}

    print(f"depth {D.shape} {D.dtype} finite={np.isfinite(D).sum()} "
          f"min={np.nanmin(D[np.isfinite(D)]) if np.isfinite(D).any() else -1:.2f} "
          f"max={np.nanmax(D[np.isfinite(D)]) if np.isfinite(D).any() else -1:.2f}", flush=True)
    print(f"seg   {Sg.shape} labels={id2label}", flush=True)

    if Sg.ndim == 3:
        Sg = Sg[..., 0]
    H, W = D.shape[:2]

    # camera intrinsics: fx = width * focal_length / horizontal_aperture
    fx = W * args.focal / args.aperture
    fy = fx                                  # square pixels
    cx, cy = W / 2.0, H / 2.0
    vv, uu = np.mgrid[0:H, 0:W]

    print("\n" + "=" * 80)
    print("  MEASURED from depth camera            vs        GROUND TRUTH")
    print("=" * 80)
    print(f"{'class':<10}{'range':>8}{'L':>7}{'W':>7}{'H':>7}{'px':>8}   |"
          f"{'range':>8}{'L':>7}{'W':>7}{'H':>7}   {'err':>7}")
    print("-" * 80)

    rows = []
    for sid, label in sorted(id2label.items()):
        if label in ("ground", "BACKGROUND", "UNLABELLED", "?"):
            continue
        m = (Sg == sid) & np.isfinite(D) & (D > 0.1)
        if m.sum() < 30:
            continue
        d = D[m]
        # back-project this object's pixels into camera-space 3D points
        z = d
        x = (uu[m] - cx) * z / fx
        y = (vv[m] - cy) * z / fy
        pts = np.stack([z, -x, -y], axis=1)     # camera -> world-ish axes

        rng = float(d.min())
        size = (float(pts[:, 0].max() - pts[:, 0].min()),
                float(pts[:, 1].max() - pts[:, 1].min()),
                float(pts[:, 2].max() - pts[:, 2].min()))

        cands = truth.get(label, [])
        best = min(cands, key=lambda t: abs(t["range"] - rng)) if cands else None
        row = {"label": label, "range_m": round(rng, 2),
               "size_lwh": [round(v, 2) for v in size], "pixels": int(m.sum())}
        if best:
            row["truth_range"] = best["range"]
            row["truth_size"] = list(best["size"])
            row["range_err"] = round(rng - best["range"], 2)
            print(f"{label:<10}{rng:8.2f}{size[0]:7.2f}{size[1]:7.2f}{size[2]:7.2f}"
                  f"{m.sum():8d}   |{best['range']:8.2f}{best['size'][0]:7.2f}"
                  f"{best['size'][1]:7.2f}{best['size'][2]:7.2f}   {row['range_err']:+7.2f}")
        else:
            print(f"{label:<10}{rng:8.2f}{size[0]:7.2f}{size[1]:7.2f}{size[2]:7.2f}"
                  f"{m.sum():8d}   |  (no ground truth match)")
        rows.append(row)

    print("=" * 80)
    print("Note: measured L/W/H under-read - a depth camera only sees the faces")
    print("pointing at it, so the far side of every object is never sampled.")

    out = {"measurements": rows,
           "truth": {k: v for k, v in truth.items()},
           "intrinsics": {"fx": round(fx, 1), "width": W, "height": H}}
    open("/workspace/depth.result", "w").write(json.dumps(out, indent=2) + "\nDONE\n")
    sim_app.close()


if __name__ == "__main__":
    main()
