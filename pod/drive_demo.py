"""
Visible driving demo - runs WITH the GUI so you can watch it in noVNC.

A car body drives forward along +X through a scene of labelled objects.
A sensor camera rides on the car. Every step it prints range + class, and
draws a green line from the car to each detected object in the viewport.

Run on the pod (NOT headless):
    /workspace/isaac/venv/bin/python /workspace/drive_demo.py
"""
import math, time

from isaacsim import SimulationApp
sim_app = SimulationApp({"headless": False, "width": 1920, "height": 1080})

import numpy as np
import omni.usd, omni.kit.app
import omni.replicator.core as rep
from pxr import UsdGeom, UsdLux, Gf, Sdf
import isaacsim.core.utils.semantics as S

try:
    from isaacsim.util.debug_draw import _debug_draw
    draw = _debug_draw.acquire_debug_draw_interface()
except Exception:
    draw = None

def look_at_matrix(eye, target, up=Gf.Vec3d(0, 0, 1)):
    """USD camera transform for an eye looking at target.

    Gf SetLookAt builds a *view* matrix; a camera's transform is its inverse.
    """
    m = Gf.Matrix4d()
    m.SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), up)
    return m.GetInverse()


SENSOR_H = 1.6
SPEED    = 0.35          # metres per frame
STEPS    = 400

OBJECTS = [
    ("person",   18.0,  -3.0, (0.5, 0.4, 1.8),   (0.95, 0.75, 0.2)),
    ("car",      30.0,   0.0, (4.5, 1.8, 1.5),   (0.85, 0.1, 0.1)),
    ("tree",     42.0,   6.0, (1.2, 1.2, 5.0),   (0.1, 0.5, 0.15)),
    ("tree",     58.0,  -6.0, (1.2, 1.2, 6.0),   (0.1, 0.45, 0.12)),
    ("car",      70.0,   3.0, (4.5, 1.8, 1.5),   (0.2, 0.2, 0.75)),
    ("building", 95.0, -14.0, (14.0, 12.0, 20.0),(0.6, 0.6, 0.65)),
    ("building",110.0,  16.0, (12.0, 10.0, 16.0),(0.55, 0.55, 0.6)),
]


def main():
    stage = omni.usd.get_context().get_stage()

    UsdLux.DistantLight.Define(stage, "/World/Sun").CreateIntensityAttr(3500.0)
    UsdLux.DomeLight.Define(stage, "/World/Sky").CreateIntensityAttr(800.0)

    ground = UsdGeom.Plane.Define(stage, "/World/Ground")
    ground.CreateWidthAttr(600.0); ground.CreateLengthAttr(600.0)
    ground.CreateAxisAttr("Z")
    ground.CreateDisplayColorAttr([Gf.Vec3f(0.22, 0.22, 0.24)])

    # lane stripes so the motion is obvious
    for i in range(60):
        s = UsdGeom.Cube.Define(stage, f"/World/lane_{i}")
        s.CreateSizeAttr(1.0)
        s.CreateDisplayColorAttr([Gf.Vec3f(0.85, 0.85, 0.85)])
        xf = UsdGeom.Xformable(s.GetPrim()); xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(i * 4.0, 0.0, 0.02))
        xf.AddScaleOp().Set(Gf.Vec3f(2.0, 0.18, 0.02))

    for i, (label, x, y, (sx, sy, sz), col) in enumerate(OBJECTS):
        p = f"/World/obj_{i}_{label}"
        c = UsdGeom.Cube.Define(stage, p)
        c.CreateSizeAttr(1.0)
        c.CreateDisplayColorAttr([Gf.Vec3f(*col)])
        xf = UsdGeom.Xformable(c.GetPrim()); xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(x, y, sz / 2.0))
        xf.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))
        S.add_labels(c.GetPrim(), labels=[label], instance_name="class")

    # --- the car: a body you can actually see moving ---
    car = UsdGeom.Xform.Define(stage, "/World/EgoCar")
    car_move = UsdGeom.Xformable(car.GetPrim()).AddTranslateOp()

    body = UsdGeom.Cube.Define(stage, "/World/EgoCar/body")
    body.CreateSizeAttr(1.0)
    body.CreateDisplayColorAttr([Gf.Vec3f(0.9, 0.85, 0.1)])
    bxf = UsdGeom.Xformable(body.GetPrim()); bxf.ClearXformOpOrder()
    bxf.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0.75))
    bxf.AddScaleOp().Set(Gf.Vec3f(4.2, 1.9, 1.4))

    roof = UsdGeom.Cube.Define(stage, "/World/EgoCar/roof")
    roof.CreateSizeAttr(1.0)
    roof.CreateDisplayColorAttr([Gf.Vec3f(0.15, 0.15, 0.18)])
    rxf = UsdGeom.Xformable(roof.GetPrim()); rxf.ClearXformOpOrder()
    rxf.AddTranslateOp().Set(Gf.Vec3d(-0.3, 0, 1.65))
    rxf.AddScaleOp().Set(Gf.Vec3f(2.2, 1.7, 0.9))

    cam = rep.create.camera(position=(0, 0, SENSOR_H), look_at=(60, 0, 1))
    rp  = rep.create.render_product(cam, (1280, 720))
    bbox3d = rep.AnnotatorRegistry.get_annotator("bounding_box_3d")
    bbox3d.attach(rp)

    # Point the VIEWPORT camera at the car. Without this you get Isaac's
    # default camera pose, which stares at empty ground - the scene is fine,
    # you just cannot see it.
    persp = stage.GetPrimAtPath("/OmniverseKit_Persp")
    chase_op = None
    if persp and persp.IsValid():
        xf = UsdGeom.Xformable(persp)
        xf.ClearXformOpOrder()
        chase_op = xf.AddTransformOp()

    rep.orchestrator.step(rt_subframes=2)   # warmup; first capture is empty

    print("\n" + "=" * 60)
    print("  DRIVING  -  watch the yellow car in the viewport")
    print("=" * 60, flush=True)

    for step in range(STEPS):
        x = step * SPEED
        car_move.Set(Gf.Vec3d(x, 0.0, 0.0))
        sensor = (x + 2.0, 0.0, SENSOR_H)
        with cam:
            rep.modify.pose(position=sensor, look_at=(x + 60.0, 0.0, 1.0))

        # chase cam: behind, beside and above the car, looking at it
        if chase_op is not None:
            eye = (x - 14.0, -11.0, 7.0)
            chase_op.Set(look_at_matrix(eye, (x + 6.0, 0.0, 1.0)))

        rep.orchestrator.step(rt_subframes=2)

        d = bbox3d.get_data()
        recs = d.get("data", [])
        labels = {int(k): v.get("class", "?")
                  for k, v in d.get("info", {}).get("idToLabels", {}).items()}
        dets = []
        for r in recs:
            tf = np.array(r["transform"]).reshape(4, 4)
            c4 = np.array([(float(r["x_min"]) + float(r["x_max"])) / 2,
                           (float(r["y_min"]) + float(r["y_max"])) / 2,
                           (float(r["z_min"]) + float(r["z_max"])) / 2, 1.0])
            wx, wy, wz, _ = c4 @ tf
            dets.append((math.dist((wx, wy, wz), sensor),
                         labels.get(int(r["semanticId"]), "?"), (wx, wy, wz)))
        dets.sort(key=lambda t: t[0])

        if draw is not None:
            draw.clear_lines()
            if dets:
                draw.draw_lines([sensor] * len(dets), [t[2] for t in dets],
                                [(0.1, 1.0, 0.3, 1.0)] * len(dets),
                                [3.0] * len(dets))

        if step % 10 == 0:
            near = "  ".join(f"{l}@{r:.0f}m" for r, l, _ in dets[:4])
            print(f"x={x:6.1f}m | {len(dets)} objs | {near}", flush=True)

        sim_app.update()          # keep the viewport responsive

    print("done", flush=True)
    sim_app.close()


if __name__ == "__main__":
    main()
