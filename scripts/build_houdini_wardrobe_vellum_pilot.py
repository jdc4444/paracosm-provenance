#!/usr/bin/env hython

"""Build one non-commercial Houdini Vellum wardrobe rescue proof."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import hou


ROOT = Path("/Users/alphaone/Documents/Code/paracosm-provenance")
PLAN_PATH = ROOT / "data/wardrobe-cloth-simulation-plan-20260728.json"
REVIEW_PATH = ROOT / "data/wardrobe-reviewed-cloth-proofs-20260728.json"
SETTLED_FRAME = 28

LEG_OBJECTS = {"pink-tie-dye-tights", "black-culottes"}
SKIRT_OBJECTS = {
    "purple-ruffle-skirt",
    "teal-pleated-skirt",
    "black-tiered-tulle-skirt",
    "navy-bubble-skirt",
    "navy-striped-velvet-skirt",
}
TORSO_OBJECTS = {
    "burgundy-button-corset",
    "navy-corset-vest",
    "pink-striped-shag-sweater",
    "olive-cropped-military-jacket",
    "multicolor-ribbed-top",
    "multicolor-mesh-top",
    "burgundy-cape-keyhole-top",
}

MATERIAL_SETTINGS = {
    "rigid-corsetry": {
        "mass": 0.16,
        "stretch_exp": 6,
        "bend": 2.5,
        "bend_exp": 1,
        "drag": 3.0,
    },
    "structured-ruffle": {
        "mass": 0.11,
        "stretch_exp": 5,
        "bend": 2.0,
        "bend_exp": -1,
        "drag": 4.0,
    },
    "sheer-lightweight": {
        "mass": 0.05,
        "stretch_exp": 4,
        "bend": 1.0,
        "bend_exp": -2,
        "drag": 6.0,
    },
    "stretch-jersey": {
        "mass": 0.08,
        "stretch_exp": 4,
        "bend": 1.0,
        "bend_exp": -2,
        "drag": 3.5,
    },
    "knit-fuzzy": {
        "mass": 0.10,
        "stretch_exp": 4,
        "bend": 2.0,
        "bend_exp": -1,
        "drag": 4.5,
    },
    "satin-fluid": {
        "mass": 0.10,
        "stretch_exp": 4,
        "bend": 1.0,
        "bend_exp": -2,
        "drag": 3.0,
    },
    "tulle-ruffle": {
        "mass": 0.05,
        "stretch_exp": 4,
        "bend": 1.0,
        "bend_exp": -2,
        "drag": 6.0,
    },
    "crisp-woven": {
        "mass": 0.12,
        "stretch_exp": 5,
        "bend": 2.5,
        "bend_exp": -1,
        "drag": 3.5,
    },
    "tailored-heavy": {
        "mass": 0.18,
        "stretch_exp": 5,
        "bend": 3.0,
        "bend_exp": 0,
        "drag": 3.0,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    return parser.parse_args()


def set_if_present(node: hou.Node, parm_name: str, value) -> None:
    parm = node.parm(parm_name)
    if parm is not None:
        parm.set(value)


def asset_url(path: Path) -> str:
    return f"/{path.relative_to(ROOT / 'public').as_posix()}"


def proxy_kind(object_id: str) -> str:
    if object_id in LEG_OBJECTS:
        return "legs"
    if object_id in SKIRT_OBJECTS:
        return "skirt"
    if object_id in TORSO_OBJECTS:
        return "torso"
    return "dress"


def add_tube(
    geometry: hou.Geometry,
    *,
    segments: int,
    rings: int,
    y_min: float,
    y_max: float,
    center_x,
    center_z,
    radius_x,
    radius_z,
    pleats: int = 0,
) -> None:
    tube_points: list[list[hou.Point]] = []
    for ring_index in range(rings):
        t = ring_index / (rings - 1)
        y = y_max + (y_min - y_max) * t
        ring_points: list[hou.Point] = []
        for segment_index in range(segments):
            theta = 2.0 * math.pi * segment_index / segments
            pleat = (
                1.0 + 0.018 * math.sin(theta * pleats) * min(1.0, t * 3.5)
                if pleats
                else 1.0
            )
            point = geometry.createPoint()
            point.setPosition(
                hou.Vector3(
                    center_x(t) + math.cos(theta) * radius_x(t) * pleat,
                    y,
                    center_z(t) + math.sin(theta) * radius_z(t) * pleat,
                )
            )
            ring_points.append(point)
        tube_points.append(ring_points)

    for ring_index in range(rings - 1):
        for segment_index in range(segments):
            next_segment = (segment_index + 1) % segments
            polygon = geometry.createPolygon()
            polygon.addVertex(tube_points[ring_index][segment_index])
            polygon.addVertex(tube_points[ring_index][next_segment])
            polygon.addVertex(tube_points[ring_index + 1][next_segment])
            polygon.addVertex(tube_points[ring_index + 1][segment_index])
            polygon.setIsClosed(True)


def build_proxy(
    bounds: hou.BoundingBox,
    kind: str,
    object_id: str,
    target_path: Path,
) -> hou.Geometry:
    geometry = hou.Geometry()
    minimum = bounds.minvec()
    maximum = bounds.maxvec()
    center = bounds.center()
    width = max(0.1, maximum.x() - minimum.x())
    height = max(0.1, maximum.y() - minimum.y())
    depth = max(0.08, maximum.z() - minimum.z())
    half_width = width * 0.5
    half_depth = depth * 0.5

    if kind == "legs":
        is_culottes = object_id == "black-culottes"
        for side in (-1.0, 1.0):
            add_tube(
                geometry,
                segments=48,
                rings=24,
                y_min=minimum.y(),
                y_max=maximum.y() - height * 0.10,
                center_x=lambda t, side=side: center.x()
                + side * width * (0.16 + 0.05 * t),
                center_z=lambda _t: center.z(),
                radius_x=lambda t: width
                * (
                    (0.22 + 0.05 * t)
                    if is_culottes
                    else (0.205 - 0.065 * t)
                ),
                radius_z=lambda t: max(
                    depth * (0.33 if is_culottes else 0.27),
                    width * 0.055,
                )
                * (1.0 - 0.12 * t),
            )
        # A short shared waistband keeps the bifurcated garment visually
        # connected while each leg remains its own clean simulation piece.
        add_tube(
            geometry,
            segments=80,
            rings=5,
            y_min=maximum.y() - height * 0.14,
            y_max=maximum.y(),
            center_x=lambda _t: center.x(),
            center_z=lambda _t: center.z(),
            radius_x=lambda _t: half_width * 0.68,
            radius_z=lambda _t: max(half_depth * 0.78, width * 0.09),
        )
    elif kind == "torso":
        add_tube(
            geometry,
            segments=88,
            rings=25,
            y_min=minimum.y(),
            y_max=maximum.y(),
            center_x=lambda _t: center.x(),
            center_z=lambda _t: center.z(),
            radius_x=lambda t: half_width
            * (
                0.78
                - 0.20 * math.sin(min(1.0, t) * math.pi)
                - 0.04 * t
            ),
            radius_z=lambda t: max(half_depth * (0.88 - 0.12 * t), width * 0.07),
        )
    elif kind == "skirt":
        is_bubble = object_id == "navy-bubble-skirt"
        add_tube(
            geometry,
            segments=96,
            rings=25,
            y_min=minimum.y(),
            y_max=maximum.y(),
            center_x=lambda _t: center.x(),
            center_z=lambda _t: center.z(),
            radius_x=lambda t: (
                half_width
                * (
                    0.53
                    + 0.48 * math.sin(min(1.0, t) * math.pi * 0.76)
                    - (0.08 * max(0.0, (t - 0.78) / 0.22) if is_bubble else 0.0)
                )
            ),
            radius_z=lambda t: max(
                half_depth
                * (
                    0.58
                    + 0.42 * math.sin(min(1.0, t) * math.pi * 0.76)
                ),
                width * 0.055,
            ),
            pleats=16 if "pleated" in object_id or is_bubble else 0,
        )
    else:
        is_column = object_id == "burgundy-sheer-column-dress"
        is_coat = object_id == "black-deconstructed-coat-dress"

        def dress_radius_x(t: float) -> float:
            if is_column:
                return half_width * (0.72 - 0.04 * t)
            if t < 0.34:
                upper_t = t / 0.34
                return half_width * (0.64 - 0.20 * upper_t)
            skirt_t = (t - 0.34) / 0.66
            flare = 0.78 if is_coat else 1.0
            return half_width * (0.44 + flare * 0.54 * skirt_t)

        def dress_radius_z(t: float) -> float:
            if is_column:
                return max(half_depth * 0.75, width * 0.055)
            if t < 0.34:
                return max(half_depth * (0.76 - 0.18 * (t / 0.34)), width * 0.06)
            skirt_t = (t - 0.34) / 0.66
            return max(
                half_depth * (0.58 + 0.38 * skirt_t),
                width * (0.06 + 0.04 * skirt_t),
            )

        add_tube(
            geometry,
            segments=96,
            rings=30,
            y_min=minimum.y(),
            y_max=maximum.y(),
            center_x=lambda _t: center.x(),
            center_z=lambda _t: center.z(),
            radius_x=dress_radius_x,
            radius_z=dress_radius_z,
            pleats=12
            if any(
                token in object_id
                for token in ("ruffle", "circle", "taffeta", "gown")
            )
            else 0,
        )

    rest_attrib = geometry.addAttrib(
        hou.attribType.Point, "rest", hou.Vector3()
    )
    for point in geometry.points():
        point.setAttribValue(rest_attrib, point.position())
    geometry.saveToFile(str(target_path))
    return geometry


def main() -> None:
    args = parse_args()
    plan = json.loads(PLAN_PATH.read_text())
    review = json.loads(REVIEW_PATH.read_text())
    plan_item = next(
        (item for item in plan["objects"] if item["objectId"] == args.object_id),
        None,
    )
    review_item = next(
        (
            item
            for item in review["proofs"]
            if item["objectId"] == args.object_id
            and item["status"] == "needs-prep"
        ),
        None,
    )
    if plan_item is None or review_item is None:
        raise RuntimeError(
            f"{args.object_id} is not in the reviewed Houdini rescue set"
        )

    material_class = plan_item["materialClass"]
    settings = MATERIAL_SETTINGS[material_class]
    kind = proxy_kind(args.object_id)
    source_glb = ROOT / "public" / plan_item["sourceModel"].lstrip("/")
    output_dir = (
        ROOT
        / f"public/archive/objects/3d/simulations/{args.object_id}/houdini-vellum-v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.object_id}-houdini-vellum-v1"
    scene_path = output_dir / f"{stem}.hipnc"
    proxy_rest_path = output_dir / f"{stem}-rest.bgeo.sc"
    proxy_sim_path = output_dir / f"{stem}-frame28.bgeo.sc"
    output_obj = output_dir / f"{stem}-frame28.obj"
    metadata_path = output_dir / f"{stem}-metadata.json"

    hou.hipFile.clear(suppress_save_prompt=True)
    hou.setFps(24)
    hou.playbar.setFrameRange(1, 48)
    hou.playbar.setPlaybackRange(1, 48)

    object_context = hou.node("/obj")
    geometry_object = object_context.createNode(
        "geo", f"{args.object_id.upper().replace('-', '_')}_VELLUM_RESCUE"
    )
    for child in geometry_object.children():
        child.destroy()

    source = geometry_object.createNode("gltf::2.0", "SOURCE_MESHY_GLTF")
    source.parm("gltffile").set(str(source_glb))
    source.parm("importnodegeometryas").set("flattenedgeometry")
    source_geometry = source.geometry()
    source_bounds = source_geometry.boundingBox()
    source_primitive_count = len(source_geometry.prims())
    reduction_percentage = min(
        100.0,
        max(14.0, 420000.0 / max(1, source_primitive_count) * 100.0),
    )

    build_proxy(source_bounds, kind, args.object_id, proxy_rest_path)
    source_height = source_bounds.sizevec().y()
    source_width = source_bounds.sizevec().x()
    source_depth = source_bounds.sizevec().z()
    rest_offset = max(0.24, source_height * 0.56)
    collider_radius = max(
        0.24,
        source_width * 0.36,
        source_depth * 0.5,
        source_height * 0.24,
    )
    initial_bottom = source_bounds.minvec().y() + rest_offset
    collider_center_y = initial_bottom - 0.045 - collider_radius

    source_reduce = geometry_object.createNode(
        "polyreduce::2.0", "PROOF_RENDER_REDUCTION"
    )
    source_reduce.setInput(0, source)
    source_reduce.parm("target").set("poly_percent")
    source_reduce.parm("percentage").set(reduction_percentage)
    set_if_present(source_reduce, "preserveuvseams", 1)
    set_if_present(source_reduce, "preservematerialboundaries", 1)

    source_rest = geometry_object.createNode("xform", "RENDER_REST_POSITION")
    source_rest.setInput(0, source_reduce)
    source_rest.parm("ty").set(rest_offset)

    proxy_file = geometry_object.createNode("file", "CLEAN_GARMENT_PROXY")
    proxy_file.parm("file").set(str(proxy_rest_path))
    proxy_rest = geometry_object.createNode("xform", "PROXY_REST_POSITION")
    proxy_rest.setInput(0, proxy_file)
    proxy_rest.parm("ty").set(rest_offset)

    cloth_constraints = geometry_object.createNode(
        "vellumconstraints", "MATERIAL_CLOTH_CONSTRAINTS"
    )
    cloth_constraints.setInput(0, proxy_rest)
    cloth_constraints.parm("constrainttype").set("cloth")
    cloth_constraints.parm("domass").set("on")
    cloth_constraints.parm("mass").set(settings["mass"])
    cloth_constraints.parm("dothickness").set("on")
    cloth_constraints.parm("thickness").set(max(0.006, source_width * 0.006))
    cloth_constraints.parm("stretchstiffness").set(2.5)
    cloth_constraints.parm("stretchstiffnessexp").set(settings["stretch_exp"])
    cloth_constraints.parm("stretchdampingratio").set(0.10)
    cloth_constraints.parm("bendstiffness").set(settings["bend"])
    cloth_constraints.parm("bendstiffnessexp").set(settings["bend_exp"])
    cloth_constraints.parm("benddampingratio").set(0.14)
    cloth_constraints.parm("dragnormal").set(settings["drag"])
    cloth_constraints.parm("dragtangent").set(0.16)

    volume_struts = geometry_object.createNode(
        "vellumconstraints", "CONSTRUCTION_VOLUME_STRUTS"
    )
    volume_struts.setInput(0, cloth_constraints, 0)
    volume_struts.setInput(1, cloth_constraints, 1)
    volume_struts.parm("constrainttype").set("surfacestruts")
    volume_struts.parm("strut_maxlen").set(
        max(source_width, source_depth, source_height) * 0.92
    )
    volume_struts.parm("strut_constraintsperpt").set(2)
    volume_struts.parm("strut_testnormals").set(1)
    volume_struts.parm("strut_jitter").set(0.18)

    collider = geometry_object.createNode("sphere", "INVISIBLE_SPHERE_COLLIDER")
    collider.parm("type").set("poly")
    collider.parm("surftype").set("quads")
    collider.parm("radx").set(collider_radius)
    collider.parm("rady").set(collider_radius)
    collider.parm("radz").set(collider_radius)
    collider.parm("tx").set(source_bounds.center().x())
    collider.parm("ty").set(collider_center_y)
    collider.parm("tz").set(source_bounds.center().z())
    collider.parm("freq").set(6)
    collider.parm("rows").set(48)
    collider.parm("cols").set(72)

    solver = geometry_object.createNode("vellumsolver", "VELLUM_SOLVER")
    solver.setInput(0, volume_struts, 0)
    solver.setInput(1, volume_struts, 1)
    solver.setInput(2, collider)
    solver.parm("startframe").set(1)
    solver.parm("simulationtype").set("dynamic")
    solver.parm("substeps").set(5)
    solver.parm("niter").set(160)
    solver.parm("collisionsiter").set(12)
    solver.parm("postcollisioniter").set(5)
    solver.parm("resolveall").set(1)
    solver.parm("doselfcollisions").set(1)
    solver.parm("gravityy").set(-5.3)
    solver.parm("timescale").set(0.70)
    solver.parm("veldamping").set(0.14)
    solver.parm("angveldamping").set(0.09)
    solver.parm("cachemaxsize").set(8000)

    capture = geometry_object.createNode("clothcapture", "CAPTURE_RENDER_TO_PROXY")
    capture.setInput(0, source_rest)
    capture.setInput(1, proxy_rest)
    capture.parm("radius").set(
        max(source_width, source_depth, source_height) * 0.46
    )

    deform = geometry_object.createNode("clothdeform", "DEFORM_RENDER_MESH")
    deform.setInput(0, capture)
    deform.setInput(1, proxy_rest)
    deform.setInput(2, solver, 0)
    normals = geometry_object.createNode("normal", "RECOMPUTE_NORMALS")
    normals.setInput(0, deform)
    set_if_present(normals, "cuspangle", 60.0)
    output_null = geometry_object.createNode("null", "OUT_HOUDINI_VELLUM_PROOF")
    output_null.setInput(0, normals)
    output_null.setDisplayFlag(True)
    output_null.setRenderFlag(True)
    geometry_object.layoutChildren()

    hou.setFrame(SETTLED_FRAME)
    simulated_proxy = solver.geometry()
    simulated_proxy.saveToFile(str(proxy_sim_path))
    deformed_geometry = output_null.geometry()
    if not deformed_geometry.points() or not simulated_proxy.points():
        raise RuntimeError("Vellum rescue produced empty geometry")
    deformed_geometry.saveToFile(str(output_obj))
    hou.hipFile.save(str(scene_path))
    if output_obj.stat().st_size < 1024:
        raise RuntimeError(f"OBJ export failed: {output_obj}")

    metadata = {
        "schemaVersion": 1,
        "createdAt": "2026-07-28",
        "objectId": args.object_id,
        "name": plan_item["name"],
        "status": "non-commercial-apprentice-pilot",
        "houdiniVersion": hou.applicationVersionString(),
        "licenseCategory": str(hou.licenseCategory()),
        "solver": "Houdini Vellum",
        "method": "clean garment-family proxy + material cloth constraints + surface struts + Cloth Capture/Deform",
        "proxyKind": kind,
        "materialClass": material_class,
        "structureMode": plan_item["structureMode"],
        "frame": SETTLED_FRAME,
        "source": plan_item["sourceModel"],
        "reductionPercentage": reduction_percentage,
        "counts": {
            "sourcePoints": len(source_geometry.points()),
            "sourcePrimitives": source_primitive_count,
            "renderPoints": len(deformed_geometry.points()),
            "renderPrimitives": len(deformed_geometry.prims()),
            "proxyPoints": len(simulated_proxy.points()),
            "proxyPrimitives": len(simulated_proxy.prims()),
        },
        "assets": {
            "scene": asset_url(scene_path),
            "model": asset_url(output_obj),
            "proxyRest": asset_url(proxy_rest_path),
            "proxySimulated": asset_url(proxy_sim_path),
        },
        "notes": [
            "Explicitly non-commercial Houdini Apprentice proof.",
            "No motion render was generated.",
            "The Meshy topology is a deformed render surface, never the simulated cloth surface.",
            review_item["note"],
        ],
    }
    metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
