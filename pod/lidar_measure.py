"""
RTX LiDAR: measure range and size from real returns, scored against ground truth.

This is the step from "the simulator told me" to "I measured it".

  ground truth  : bounding_box_3d annotator - reads the scene graph
  measurement   : RTX LiDAR point cloud    - ray-traced returns off geometry

Every object gets both, side by side, with the error between them. A LiDAR does
not care whether it hits a photoreal car or a grey box, so primitive geometry is
fine here - and it makes ground truth exact, which is what you want when the
thing under test is the measurement itself.

    /workspace/isaac/venv/bin/python /workspace/lidar_measure.py --headless
"""
import argparse, json, math

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--steps", type=int, default=6)
parser.add_argument("--config", default="Example_Rotary", help="RTX lidar config")
args = parser.parse_args()

from isaacsim import SimulationApp
sim_app = SimulationApp({"headless": args.headless})

import numpy as np
import omni.usd
import omni.replicator.core as rep
from pxr import UsdGeom, UsdLux, Gf, Usd
import isaacsim.core.utils.semantics as S
from isaacsim.core.api import World
from isaacsim.sensors.rtx import LidarRtx, SUPPORTED_LIDAR_CONFIGS
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.storage.native import get_assets_root_path

SENSOR_H = 1.6

#  label,      x,     y,  (length, width, height)
TARGETS = [
    ("car",     12.0,   0.0, (4.5, 1.8, 1.5)),
    ("person",   8.0,  -2.5, (0.5, 0.4, 1.8)),
    ("tree",    18.0,   4.0, (1.2, 1.2, 5.0)),
    ("car",     25.0,  -6.0, (4.5, 1.8, 1.5)),
    ("building",38.0,  10.0, (10.0, 8.0, 12.0)),
]


def build_scene(stage):
    UsdLux.DistantLight.Define(stage, "/World/Sun").CreateIntensityAttr(1500.0)
    g = UsdGeom.Plane.Define(stage, "/World/Ground")
    g.CreateWidthAttr(300.0); g.CreateLengthAttr(300.0); g.CreateAxisAttr("Z")

    truth = {}
    for i, (label, x, y, (sx, sy, sz)) in enumerate(TARGETS):
        path = f"/World/t{i}_{label}"
        c = UsdGeom.Cube.Define(stage, path)
        c.CreateSizeAttr(1.0)
        xf = UsdGeom.Xformable(c.GetPrim()); xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(x, y, sz / 2.0))
        xf.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))
        S.add_labels(c.GetPrim(), labels=[label], instance_name="class")
        # range from the sensor origin to the nearest FACE, which is what a
        # lidar actually sees - not the centre.
        near_x = x - sx / 2.0
        truth[path] = {
            "label": label, "centre": (x, y, sz / 2.0), "size": (sx, sy, sz),
            "range_to_face": round(math.dist((near_x, y, sz / 2.0),
                                             (0.0, 0.0, SENSOR_H)), 2),
        }
    return truth


def make_lidar(world, stage):
    """Create an RTX lidar the way NVIDIA's own test does.

    Three things matter, all of which fail SILENTLY if you get them wrong:

      1. The prim must be an OmniLidar with OmniSensorGenericLidarCoreAPI
         applied. LidarRtx will not create a usable one for you.
      2. config_file_name must be an exact entry from SUPPORTED_LIDAR_CONFIGS.
         A bare name like "Example_Rotary" does not resolve, and you get a
         sensor with numCols=0, fov=0, rotationRate=0 - no error raised.
      3. initialize() must be called after world.reset().

    Symptom of any of these: annotators attach fine, keys exist, arrays empty.
    """
    configs = []
    try:
        configs = [str(c) for c in SUPPORTED_LIDAR_CONFIGS]
    except Exception as e:
        print(f"could not read SUPPORTED_LIDAR_CONFIGS: {e}", flush=True)

    chosen = None
    for c in configs:                       # prefer an exact stem match
        if c.split("/")[-1].split(".")[0].lower() == args.config.lower():
            chosen = c; break
    if chosen is None:
        for c in configs:
            if args.config.lower() in c.lower():
                chosen = c; break
    if chosen is None:
        chosen = configs[0] if configs else None
    print(f"lidar config -> {chosen}", flush=True)

    # The .usd entries in SUPPORTED_LIDAR_CONFIGS are ASSETS to reference onto
    # the prim, not a filename the class loads for you. Passing them as
    # config_file_name leaves numCols=0 / fov=0 with no error raised.
    root = get_assets_root_path()
    ref_ok = False
    if chosen and root:
        url = root + chosen if chosen.startswith("/") else chosen
        try:
            add_reference_to_stage(usd_path=url, prim_path="/World/lidar")
            ref_ok = True
            print(f"referenced sensor asset: {url}", flush=True)
        except Exception as e:
            print(f"add_reference_to_stage failed: {type(e).__name__}: {e}", flush=True)

    # The referenced asset's ROOT is an Xform; the OmniLidar sits inside it.
    # LidarRtx rejects anything that is not an OmniLidar, so descend to find it.
    lidar_path = "/World/lidar"
    prim = stage.GetPrimAtPath(lidar_path)
    if prim and prim.IsValid() and prim.GetTypeName() != "OmniLidar":
        for d in Usd.PrimRange(prim):
            if d.GetTypeName() == "OmniLidar":
                lidar_path = str(d.GetPath())
                prim = d
                print(f"found OmniLidar descendant at {lidar_path}", flush=True)
                break
    if not prim or not prim.IsValid():
        prim = stage.DefinePrim(lidar_path, "OmniLidar")
    if prim.GetTypeName() == "OmniLidar" and not prim.HasAPI("OmniSensorGenericLidarCoreAPI"):
        prim.ApplyAPI("OmniSensorGenericLidarCoreAPI")
    print(f"prim type={prim.GetTypeName()} path={lidar_path} "
          f"hasAPI={prim.HasAPI('OmniSensorGenericLidarCoreAPI')} ref={ref_ok}", flush=True)

    kwargs = {} if ref_ok else ({"config_file_name": chosen} if chosen else {})
    lidar = LidarRtx(prim_path=lidar_path, name="lidar",
                     translation=np.array([0.0, 0.0, SENSOR_H]), **kwargs)
    world.scene.add(lidar)
    return lidar


def _harvest(lidar):
    """Frame dict first; fall back to reading the attached annotators directly."""
    d = {}
    try:
        f = lidar.get_current_frame()
        if isinstance(f, dict):
            d.update(f)
    except Exception as e:
        print(f"get_current_frame failed: {type(e).__name__}", flush=True)
    try:
        for name, a in (lidar.get_annotators() or {}).items():
            try:
                v = a.get_data()
                if isinstance(v, dict):
                    for k, vv in v.items():
                        d.setdefault(f"{name}:{k}", vv)
                else:
                    d.setdefault(name, v)
            except Exception:
                pass
    except Exception:
        pass
    return d


def points_from(lidar):
    """Return (points Nx3, distances N, raw dict).

    Keys arrive prefixed by annotator name, e.g.
    'IsaacCreateRTXLidarScanBuffer:data' - match on the suffix, not equality.
    """
    d = _harvest(lidar)

    shapes = {}
    for k, v in d.items():
        try:
            a = np.asarray(v)
            if a.dtype.kind in "fiub" and a.size:
                shapes[k] = f"{a.shape} {a.dtype}"
        except Exception:
            pass
    print("FIELD SHAPES:", flush=True)
    for k in sorted(shapes):
        print(f"   {k:<58} {shapes[k]}", flush=True)

    print("SENSOR METADATA (does the config describe real beams?):", flush=True)
    for k, v in sorted(d.items()):
        tail = k.split(":")[-1]
        if tail in ("numRows", "numCols", "rotationRate", "horizontalFov",
                    "horizontalResolution", "azimuthRange", "depthRange"):
            try:
                print(f"   {tail:<24} = {np.asarray(v).tolist()}", flush=True)
            except Exception:
                print(f"   {tail:<24} = {v}", flush=True)
    empty = [k for k, v in d.items()
             if k.split(':')[-1] in ('data', 'distance', 'azimuth', 'elevation',
                                     'intensity', 'linearDepthData')]
    print(f"   data-bearing keys present: {empty}", flush=True)

    def find(*suffixes):
        for k, v in d.items():
            tail = k.split(":")[-1]
            if tail in suffixes:
                a = np.asarray(v)
                if a.size:
                    return a
        return None

    pts = find("data", "point_cloud_data", "pointCloudData", "points", "xyz")
    if pts is not None and pts.ndim == 2 and pts.shape[1] >= 3:
        pts = pts[:, :3].astype(np.float64)
    else:
        pts = None

    dist = find("distance", "linearDepthData", "range")
    dist = dist.astype(np.float64).ravel() if dist is not None else None

    # reconstruct xyz from spherical if the cartesian buffer is absent
    if pts is None and dist is not None:
        az = find("azimuth"); el = find("elevation")
        if az is not None and el is not None and len(az) == len(dist):
            az = az.astype(np.float64).ravel(); el = el.astype(np.float64).ravel()
            if np.nanmax(np.abs(az)) > 2 * np.pi:      # degrees -> radians
                az = np.radians(az); el = np.radians(el)
            pts = np.stack([dist * np.cos(el) * np.cos(az),
                            dist * np.cos(el) * np.sin(az),
                            dist * np.sin(el)], axis=1)
            print(f"reconstructed {len(pts)} points from distance/azimuth/elevation",
                  flush=True)

    if pts is None:
        pts = np.empty((0, 3))
    # drop non-returns
    keep = np.isfinite(pts).all(axis=1) & (np.linalg.norm(pts, axis=1) > 0.05)
    return pts[keep], (dist[keep] if dist is not None and len(dist) == len(keep) else None), d


def cluster(points, eps=1.5, min_pts=8):
    """Grid-based clustering. Objects here are well separated, so a simple
    voxel flood-fill is enough and avoids a scikit-learn dependency."""
    if len(points) == 0:
        return []
    keys = np.floor(points / eps).astype(np.int64)
    table = {}
    for idx, k in enumerate(map(tuple, keys)):
        table.setdefault(k, []).append(idx)

    seen, clusters = set(), []
    for k in table:
        if k in seen:
            continue
        stack, group = [k], []
        seen.add(k)
        while stack:
            cur = stack.pop()
            group.extend(table[cur])
            cx, cy, cz = cur
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nb = (cx + dx, cy + dy, cz + dz)
                        if nb in table and nb not in seen:
                            seen.add(nb); stack.append(nb)
        if len(group) >= min_pts:
            clusters.append(points[group])
    return clusters


def main():
    world = World(stage_units_in_meters=1.0)
    stage = omni.usd.get_context().get_stage()
    truth = build_scene(stage)
    lidar = make_lidar(world, stage)

    # add_*_to_frame() is deprecated in 5.0 - it warns and populates nothing.
    # attach_annotator() is the supported route.
    #   IsaacCreateRTXLidarScanBuffer -> full 3D point cloud
    #   IsaacComputeRTXLidarFlatScan  -> 2D slice
    attached = []
    for ann in ("IsaacCreateRTXLidarScanBuffer", "IsaacComputeRTXLidarFlatScan"):
        try:
            lidar.attach_annotator(ann)
            attached.append(ann)
        except Exception as e:
            print(f"attach_annotator({ann}) failed: {type(e).__name__}: {e}", flush=True)
    print(f"attached annotators: {attached}", flush=True)

    world.reset()

    # 3. initialize() - without it the sensor never starts producing
    try:
        lidar.initialize()
        print("lidar.initialize() OK", flush=True)
    except Exception as e:
        print(f"lidar.initialize() failed: {type(e).__name__}: {e}", flush=True)

    try:
        print(f"render product -> {lidar.get_render_product_path()}", flush=True)
    except Exception:
        pass
    try:
        lidar.enable_visualization()
    except Exception:
        pass

    # let the sweep accumulate - a rotary lidar needs several frames for a
    # full revolution
    # world.step() advances physics/rendering but does NOT reliably drive the
    # RTX sensor render pass. Drive the orchestrator too - same lesson as the
    # camera annotators earlier.
    n = max(args.steps, 60)
    for i in range(n):
        world.step(render=True)
        try:
            rep.orchestrator.step(rt_subframes=1)
        except Exception as e:
            if i == 0:
                print(f"orchestrator.step unavailable: {type(e).__name__}", flush=True)

    pts, dists, raw = points_from(lidar)
    report = {"lidar_config": args.config,
              "beams_numRows": None, "beams_numCols": None,
              "frame_keys": sorted([str(k) for k in raw.keys()])[:16],
              "n_points": int(len(pts))}
    print(json.dumps(report, indent=2), flush=True)

    if len(pts) == 0:
        print("NO POINTS - inspect buffer_keys above", flush=True)
        open("/workspace/lidar.result", "w").write(json.dumps(report, indent=2) + "\nDONE\n")
        sim_app.close(); return

    # drop ground returns so clusters are objects, not one big floor
    obj_pts = pts[pts[:, 2] > 0.35]
    groups = cluster(obj_pts)

    rows = []
    for g in groups:
        d = np.linalg.norm(g - np.array([0.0, 0.0, SENSOR_H]), axis=1)
        lo = g.min(axis=0); hi = g.max(axis=0)
        rows.append({
            "n_points": int(len(g)),
            "range_m": round(float(d.min()), 2),
            "size_lwh": [round(float(hi[0] - lo[0]), 2),
                         round(float(hi[1] - lo[1]), 2),
                         round(float(hi[2] - lo[2]), 2)],
            "centre_xy": [round(float(g[:, 0].mean()), 2),
                          round(float(g[:, 1].mean()), 2)],
        })
    rows.sort(key=lambda r: r["range_m"])

    # match each measurement to the nearest ground-truth object
    print("\n" + "=" * 78)
    print("  MEASURED (lidar returns)          vs        GROUND TRUTH")
    print("=" * 78)
    print(f"{'range':>8} {'L':>6} {'W':>6} {'H':>6} {'pts':>6}   |  "
          f"{'label':<9} {'range':>7} {'L':>6} {'W':>6} {'H':>6}")
    print("-" * 78)
    for r in rows:
        best, bd = None, 1e9
        for t in truth.values():
            dd = math.dist((r["centre_xy"][0], r["centre_xy"][1]),
                           (t["centre"][0], t["centre"][1]))
            if dd < bd:
                bd, best = dd, t
        if best is None or bd > 6.0:
            print(f"{r['range_m']:8.2f} {r['size_lwh'][0]:6.2f} {r['size_lwh'][1]:6.2f} "
                  f"{r['size_lwh'][2]:6.2f} {r['n_points']:6d}   |  (unmatched)")
            continue
        r["matched"] = best["label"]
        r["truth_range"] = best["range_to_face"]
        r["truth_size"] = list(best["size"])
        r["range_err"] = round(r["range_m"] - best["range_to_face"], 2)
        print(f"{r['range_m']:8.2f} {r['size_lwh'][0]:6.2f} {r['size_lwh'][1]:6.2f} "
              f"{r['size_lwh'][2]:6.2f} {r['n_points']:6d}   |  "
              f"{best['label']:<9} {best['range_to_face']:7.2f} "
              f"{best['size'][0]:6.2f} {best['size'][1]:6.2f} {best['size'][2]:6.2f}"
              f"   err {r['range_err']:+.2f} m")

    report["measurements"] = rows
    report["ground_truth"] = list(truth.values())
    open("/workspace/lidar.result", "w").write(json.dumps(report, indent=2) + "\nDONE\n")
    sim_app.close()


if __name__ == "__main__":
    main()
