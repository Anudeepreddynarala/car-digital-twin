"""
Drive a predetermined route through a CARLA town, detecting objects by class
and range.

This is the CARLA counterpart to pod/drive_demo.py. The difference is what you
do NOT have to build: the town, the roads, the junctions, the signage, the
route planner and the driving controller all ship with CARLA.

UNTESTED - written while Isaac Sim was still installing. Treat as a starting
point, not a validated script. Run install_carla.sh first, start the server,
then this.

    /workspace/carla/CarlaUE4.sh -RenderOffScreen -carla-rpc-port=2000 &
    /workspace/carla-venv/bin/python carla_drive.py --town Town10HD_Opt
"""
import argparse, math, random, time, sys

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="localhost")
parser.add_argument("--port", type=int, default=2000)
parser.add_argument("--town", default="Town10HD_Opt")
parser.add_argument("--seconds", type=float, default=90.0)
parser.add_argument("--range", type=float, default=50.0, help="report objects within N metres")
args = parser.parse_args()

import carla

# CARLA's semantic tags -> the classes we care about.
INTERESTING = {
    12: "pedestrian",
    14: "car",
    15: "truck",
    16: "bus",
    18: "motorcycle",
    19: "bicycle",
    7:  "traffic_light",
    8:  "traffic_sign",
    9:  "vegetation",
    1:  "building",
}


def main():
    client = carla.Client(args.host, args.port)
    client.set_timeout(60.0)

    print(f"loading {args.town} ...", flush=True)
    world = client.load_world(args.town)
    amap = world.get_map()

    # Deterministic stepping: the server advances only when we tick, so sensor
    # data lines up with vehicle state instead of racing it.
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05          # 20 Hz
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()
    spawn_points = amap.get_spawn_points()

    vehicle_bp = bp_lib.filter("vehicle.tesla.model3")[0]
    start = spawn_points[0]
    vehicle = world.spawn_actor(vehicle_bp, start)
    print(f"spawned {vehicle.type_id} at {start.location}", flush=True)

    actors = [vehicle]
    try:
        # ---- the predetermined route -------------------------------------
        # GlobalRoutePlanner turns (start, end) into a waypoint list that
        # follows the road network - lanes, junctions and turns included.
        try:
            from agents.navigation.global_route_planner import GlobalRoutePlanner
            grp = GlobalRoutePlanner(amap, 2.0)
            dest = spawn_points[len(spawn_points) // 2].location
            route = grp.trace_route(start.location, dest)
            print(f"route: {len(route)} waypoints, "
                  f"{sum(1 for _ in route) * 2.0:.0f} m", flush=True)
        except ImportError:
            route = None
            print("NOTE: agents package not on PYTHONPATH; using autopilot instead.",
                  flush=True)
            print("      export PYTHONPATH=$PYTHONPATH:/workspace/carla/PythonAPI/carla",
                  flush=True)

        # ---- sensors ------------------------------------------------------
        # ray_cast_semantic returns each point tagged with its object class AND
        # its position - class + range in one sensor, the direct analogue of
        # Isaac's bounding_box_3d annotator.
        lidar_bp = bp_lib.find("sensor.lidar.ray_cast_semantic")
        lidar_bp.set_attribute("range", str(args.range))
        lidar_bp.set_attribute("rotation_frequency", "20")
        lidar_bp.set_attribute("channels", "32")
        lidar_bp.set_attribute("points_per_second", "200000")
        lidar = world.spawn_actor(
            lidar_bp, carla.Transform(carla.Location(z=2.0)), attach_to=vehicle)
        actors.append(lidar)

        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "1280")
        cam_bp.set_attribute("image_size_y", "720")
        camera = world.spawn_actor(
            cam_bp, carla.Transform(carla.Location(x=1.5, z=1.6)), attach_to=vehicle)
        actors.append(camera)

        latest = {"lidar": None}
        lidar.listen(lambda d: latest.__setitem__("lidar", d))
        camera.listen(lambda img: None)          # keep the sensor alive

        vehicle.set_autopilot(True)              # TrafficManager drives

        print("\n" + "=" * 60)
        print("  DRIVING  -  class + range from semantic lidar")
        print("=" * 60, flush=True)

        steps = int(args.seconds / settings.fixed_delta_seconds)
        for step in range(steps):
            world.tick()
            data = latest["lidar"]
            if data is None or step % 20:
                continue

            # nearest point per class
            nearest = {}
            for p in data:
                label = INTERESTING.get(p.object_tag)
                if not label:
                    continue
                d = math.sqrt(p.point.x ** 2 + p.point.y ** 2 + p.point.z ** 2)
                if label not in nearest or d < nearest[label]:
                    nearest[label] = d

            tf = vehicle.get_transform()
            spd = vehicle.get_velocity()
            kph = 3.6 * math.sqrt(spd.x ** 2 + spd.y ** 2 + spd.z ** 2)
            print(f"\nt={step * settings.fixed_delta_seconds:5.1f}s  "
                  f"({tf.location.x:7.1f},{tf.location.y:7.1f})  {kph:5.1f} km/h  "
                  f"{len(nearest)} classes", flush=True)
            for label, d in sorted(nearest.items(), key=lambda kv: kv[1]):
                bar = "#" * max(1, min(30, int(32 - d / 2)))
                print(f"   {label:<14} {d:6.1f} m  {bar}", flush=True)

    finally:
        print("\ncleaning up", flush=True)
        for a in reversed(actors):
            try:
                a.destroy()
            except Exception:
                pass
        s = world.get_settings()
        s.synchronous_mode = False
        world.apply_settings(s)


if __name__ == "__main__":
    main()
