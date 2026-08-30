"""
RTX Radar: measure range and size from real returns, scored against ground truth.

Creation pattern taken from NVIDIA's own test_commands.py rather than inferred:

    omni.kit.commands.execute("IsaacSensorCreateRtxRadar",
                              path=..., translation=Gf.Vec3d, orientation=Gf.Quatd)
    -> prim.IsA("OmniRadar")

Data comes through the GenericModelOutput annotator (used for both lidar and
radar in isaacsim's own tests), parsed with get_gmo_data().

    /workspace/isaac/venv/bin/python /workspace/radar_measure.py --headless
"""
import argparse, json, math

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--steps", type=int, default=40)
args = parser.parse_args()

from isaacsim import SimulationApp
sim_app = SimulationApp({"headless": args.headless})

import numpy as np
import omni.usd, omni.kit.commands
import omni.replicator.core as rep
from pxr import UsdGeom, UsdLux, Gf
import isaacsim.core.utils.semantics as S

try:
    from isaacsim.sensors.rtx import get_gmo_data
except Exception:
    get_gmo_data = None

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
    g = UsdGeom.Plane.Define(stage, "/World/Ground")
    g.CreateWidthAttr(400.0); g.CreateLengthAttr(400.0); g.CreateAxisAttr("Z")
    S.add_labels(g.GetPrim(), labels=["ground"], instance_name="class")

    truth = []
    for i, (label, x, y, (sx, sy, sz)) in enumerate(TARGETS):
        c = UsdGeom.Cube.Define(stage, f"/World/t{i}_{label}")
        c.CreateSizeAttr(1.0)
        xf = UsdGeom.Xformable(c.GetPrim()); xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(x, y, sz / 2.0))
        xf.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))
        S.add_labels(c.GetPrim(), labels=[label], instance_name="class")
        truth.append({"label": label, "centre": (x, y, sz / 2.0), "size": (sx, sy, sz),
                      "range": round(math.dist((x - sx / 2.0, y, sz / 2.0),
                                               (0.0, 0.0, SENSOR_H)), 2)})
    return truth


def make_radar():
    ok, prim = omni.kit.commands.execute(
        "IsaacSensorCreateRtxRadar",
        path="/World/radar",
        translation=Gf.Vec3d(0.0, 0.0, SENSOR_H),
        orientation=Gf.Quatd(1.0, 0.0, 0.0, 0.0),
    )
    if prim is None or not prim.IsValid():
        raise RuntimeError("radar prim not created")
    print(f"radar prim={prim.GetPath()} isOmniRadar={prim.IsA('OmniRadar')}", flush=True)
    return prim


def extract_points(raw):
    """GMO buffers vary by build - report what is there, then find xyz."""
    if raw is None:
        return np.empty((0, 3)), {}

    d = {}
    if isinstance(raw, dict):
        d = raw
    else:
        for a in dir(raw):
            if a.startswith("_"):
                continue
            try:
                v = getattr(raw, a)
            except Exception:
                continue
            if not callable(v):
                d[a] = v

    print("GMO FIELDS:", flush=True)
    for k in sorted(d):
        try:
            arr = np.asarray(d[k])
            if arr.dtype.kind in "fiub":
                print(f"   {k:<26} shape={arr.shape} dtype={arr.dtype}"
                      + (f" min={np.nanmin(arr):.2f} max={np.nanmax(arr):.2f}"
                         if arr.size else ""), flush=True)
        except Exception:
            pass

    def grab(*names):
        for n in names:
            for k, v in d.items():
                if k.split(":")[-1] == n:
                    a = np.asarray(v)
                    if a.size:
                        return a
        return None

    pts = grab("x", "positions", "point_cloud_data", "data", "xyz")
    if pts is not None and pts.ndim == 2 and pts.shape[1] >= 3:
        return pts[:, :3].astype(np.float64), d

    # radar commonly reports spherical: range / azimuth / elevation
    r = grab("radialDistance", "distance", "range", "r")
    az = grab("azimuth", "azimuthAngle")
    el = grab("elevation", "elevationAngle")
    if r is not None and az is not None and el is not None:
        r = r.astype(np.float64).ravel()
        az = az.astype(np.float64).ravel(); el = el.astype(np.float64).ravel()
        n = min(len(r), len(az), len(el))
        r, az, el = r[:n], az[:n], el[:n]
        if n and np.nanmax(np.abs(az)) > 2 * np.pi:
            az = np.radians(az); el = np.radians(el)
        pts = np.stack([r * np.cos(el) * np.cos(az),
                        r * np.cos(el) * np.sin(az),
                        r * np.sin(el)], axis=1)
        print(f"reconstructed {len(pts)} points from range/az/el", flush=True)
        return pts, d
    return np.empty((0, 3)), d


def cluster(points, eps=2.0, min_pts=3):
    if len(points) == 0:
        return []
    keys = np.floor(points / eps).astype(np.int64)
    table = {}
    for i, k in enumerate(map(tuple, keys)):
        table.setdefault(k, []).append(i)
    seen, out = set(), []
    for k in table:
        if k in seen:
            continue
        stack, grp = [k], []
        seen.add(k)
        while stack:
            c = stack.pop(); grp.extend(table[c])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nb = (c[0]+dx, c[1]+dy, c[2]+dz)
                        if nb in table and nb not in seen:
                            seen.add(nb); stack.append(nb)
        if len(grp) >= min_pts:
            out.append(points[grp])
    return out


def main():
    stage = omni.usd.get_context().get_stage()
    truth = build_scene(stage)
    radar = make_radar()

    rp = rep.create.render_product(radar.GetPath(), [1, 1])
    annot = rep.AnnotatorRegistry.get_annotator("GenericModelOutput")
    annot.attach(rp)
    print("attached GenericModelOutput", flush=True)

    for _ in range(args.steps):
        rep.orchestrator.step(rt_subframes=2)

    raw = annot.get_data()
    if get_gmo_data is not None:
        try:
            raw = get_gmo_data(raw)
            print("parsed via get_gmo_data()", flush=True)
        except Exception as e:
            print(f"get_gmo_data failed: {type(e).__name__}: {e}", flush=True)

    pts, fields = extract_points(raw)
    print(f"\nRADAR RETURNS: {len(pts)}", flush=True)

    result = {"n_points": int(len(pts)), "fields": sorted([str(k) for k in fields])[:20]}
    if len(pts) == 0:
        print("NO RETURNS - see GMO FIELDS above", flush=True)
        open("/workspace/radar.result", "w").write(json.dumps(result, indent=2) + "\nDONE\n")
        sim_app.close(); return

    obj = pts[pts[:, 2] > 0.3]
    groups = cluster(obj)

    print("\n" + "=" * 76)
    print("  MEASURED from radar returns          vs        GROUND TRUTH")
    print("=" * 76)
    print(f"{'range':>8}{'L':>7}{'W':>7}{'H':>7}{'pts':>7}   |  "
          f"{'label':<9}{'range':>8}{'L':>7}{'W':>7}{'H':>7}{'err':>8}")
    print("-" * 76)
    rows = []
    for g in groups:
        dist = np.linalg.norm(g - np.array([0.0, 0.0, SENSOR_H]), axis=1)
        lo, hi = g.min(axis=0), g.max(axis=0)
        rng = float(dist.min())
        size = tuple(float(hi[i] - lo[i]) for i in range(3))
        cx, cy = float(g[:, 0].mean()), float(g[:, 1].mean())
        best = min(truth, key=lambda t: math.dist((cx, cy), (t["centre"][0], t["centre"][1])))
        err = round(rng - best["range"], 2)
        print(f"{rng:8.2f}{size[0]:7.2f}{size[1]:7.2f}{size[2]:7.2f}{len(g):7d}   |  "
              f"{best['label']:<9}{best['range']:8.2f}{best['size'][0]:7.2f}"
              f"{best['size'][1]:7.2f}{best['size'][2]:7.2f}{err:+8.2f}")
        rows.append({"range_m": round(rng, 2), "size_lwh": [round(v, 2) for v in size],
                     "n_points": len(g), "matched": best["label"],
                     "truth_range": best["range"], "range_err": err})
    result["measurements"] = rows
    result["truth"] = truth
    open("/workspace/radar.result", "w").write(json.dumps(result, indent=2) + "\nDONE\n")
    sim_app.close()


if __name__ == "__main__":
    main()
