#!/usr/bin/env hython

"""Build one floor-draped Houdini Vellum wardrobe proof.

Unlike the rejected generic-cage passes, the simulation proxy is reduced
directly from each garment's own mesh and retains its UVs. The rendered proof
uses that simulated surface directly: there is no secondary cage transfer that
can pull touching folds through the wrong neighboring points.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import hou

from build_houdini_wardrobe_vellum_pilot import (
    MATERIAL_SETTINGS,
    PLAN_PATH,
    ROOT,
    asset_url,
    proxy_kind,
    set_if_present,
)


REGISTRY_PATH = ROOT / "data/object-3d-versions.json"
SETTLED_FRAME = 72


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    return parser.parse_args()


def current_source_model(object_id: str, fallback: str) -> str:
    registry = json.loads(REGISTRY_PATH.read_text())
    record = next(
        (
            candidate
            for candidate in registry["objects"]
            if candidate["objectId"] == object_id
        ),
        None,
    )
    if record is None:
        return fallback
    primary_id = record.get("primaryVersionId")
    if primary_id:
        primary = next(
            (
                version
                for version in record["versions"]
                if version["id"] == primary_id
            ),
            None,
        )
        if primary:
            return primary["model"]
    ready_versions = [
        version
        for version in record["versions"]
        if version.get("status") == "ready"
    ]
    if ready_versions:
        return ready_versions[-1]["model"]
    return fallback


def configure_transform(
    node: hou.Node,
    *,
    center: hou.Vector3,
    lift: float,
    material_class: str,
) -> None:
    # A near-sideways start makes the first floor contact broad and prevents
    # the final pose from reading as a suspended upright garment.
    tilt_z = 68.0 if material_class != "rigid-corsetry" else 58.0
    tilt_x = -19.0 if material_class in {"knit-fuzzy", "satin-fluid"} else -13.0
    set_if_present(node, "px", center.x())
    set_if_present(node, "py", center.y())
    set_if_present(node, "pz", center.z())
    set_if_present(node, "rx", tilt_x)
    set_if_present(node, "rz", tilt_z)
    set_if_present(node, "ty", lift)


def main() -> None:
    args = parse_args()
    plan = json.loads(PLAN_PATH.read_text())
    plan_item = next(
        (item for item in plan["objects"] if item["objectId"] == args.object_id),
        None,
    )
    if plan_item is None:
        raise RuntimeError(f"{args.object_id} is not in the wardrobe cloth plan")

    material_class = plan_item["materialClass"]
    settings = MATERIAL_SETTINGS[material_class]
    kind = proxy_kind(args.object_id)
    source_public_path = current_source_model(
        args.object_id,
        plan_item["sourceModel"],
    )
    source_glb = ROOT / "public" / source_public_path.lstrip("/")
    output_dir = (
        ROOT
        / f"public/archive/objects/3d/simulations/{args.object_id}/houdini-floor-v3"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.object_id}-houdini-floor-v3"
    scene_path = output_dir / f"{stem}.hipnc"
    proxy_rest_path = output_dir / f"{stem}-rest.bgeo.sc"
    proxy_sim_path = output_dir / f"{stem}-frame{SETTLED_FRAME}.bgeo.sc"
    output_obj = output_dir / f"{stem}-frame{SETTLED_FRAME}.obj"
    metadata_path = output_dir / f"{stem}-metadata.json"

    hou.hipFile.clear(suppress_save_prompt=True)
    hou.setFps(24)
    hou.playbar.setFrameRange(1, 96)
    hou.playbar.setPlaybackRange(1, 96)

    object_context = hou.node("/obj")
    geometry_object = object_context.createNode(
        "geo",
        f"{args.object_id.upper().replace('-', '_')}_VELLUM_FLOOR_V3",
    )
    for child in geometry_object.children():
        child.destroy()

    source = geometry_object.createNode("gltf::2.0", "SOURCE_TEXTURED_GLTF")
    source.parm("gltffile").set(str(source_glb))
    source.parm("importnodegeometryas").set("flattenedgeometry")
    source_geometry = source.geometry()
    source_bounds = source_geometry.boundingBox()
    source_primitives = len(source_geometry.prims())
    proxy_reduction_percentage = min(
        42.0,
        max(2.0, 18000.0 / max(1, source_primitives) * 100.0),
    )

    size = source_bounds.sizevec()
    center = source_bounds.center()
    width = max(0.1, size.x())
    height = max(0.1, size.y())
    depth = max(0.08, size.z())
    largest_extent = max(width, height, depth)
    rest_lift = -source_bounds.minvec().y() + height * 0.68

    proxy_reduce = geometry_object.createNode(
        "polyreduce::2.0",
        "UV_PRESERVING_SIM_AND_RENDER_SURFACE",
    )
    proxy_reduce.setInput(0, source)
    proxy_reduce.parm("target").set("poly_percent")
    proxy_reduce.parm("percentage").set(proxy_reduction_percentage)
    set_if_present(proxy_reduce, "preserveuvseams", 1)
    set_if_present(proxy_reduce, "preservematerialboundaries", 1)
    proxy_rest = geometry_object.createNode("xform", "PROXY_FLOOR_DROP_REST")
    proxy_rest.setInput(0, proxy_reduce)
    configure_transform(
        proxy_rest,
        center=center,
        lift=rest_lift,
        material_class=material_class,
    )

    cloth_constraints = geometry_object.createNode(
        "vellumconstraints",
        "MATERIAL_CLOTH_NO_MANNEQUIN",
    )
    cloth_constraints.setInput(0, proxy_rest)
    cloth_constraints.parm("constrainttype").set("cloth")
    cloth_constraints.parm("domass").set("on")
    cloth_constraints.parm("mass").set(settings["mass"])
    cloth_constraints.parm("dothickness").set("on")
    cloth_constraints.parm("thickness").set(max(0.005, width * 0.0045))
    cloth_constraints.parm("stretchstiffness").set(2.25)
    cloth_constraints.parm("stretchstiffnessexp").set(settings["stretch_exp"])
    cloth_constraints.parm("stretchdampingratio").set(0.12)
    cloth_constraints.parm("bendstiffness").set(settings["bend"])
    cloth_constraints.parm("bendstiffnessexp").set(settings["bend_exp"])
    cloth_constraints.parm("benddampingratio").set(0.16)
    cloth_constraints.parm("dragnormal").set(settings["drag"] * 0.56)
    cloth_constraints.parm("dragtangent").set(0.10)

    floor = geometry_object.createNode("box", "ACTUAL_FLOOR_COLLIDER")
    floor_span = largest_extent * 9.0
    set_if_present(floor, "sizex", floor_span)
    set_if_present(floor, "sizey", max(0.04, largest_extent * 0.025))
    set_if_present(floor, "sizez", floor_span)
    set_if_present(floor, "ty", -max(0.02, largest_extent * 0.0125))

    # Side gates compress the garment after it hits the floor. Because their
    # faces are vertical they create a floor pile instead of supporting a
    # mannequin-like volume from underneath.
    compression_factor = {
        "rigid-corsetry": 0.78,
        "crisp-woven": 0.54,
        "tailored-heavy": 0.58,
        "structured-ruffle": 0.52,
    }.get(material_class, 0.43)
    compression_width = width * compression_factor
    gate_thickness = max(width * 0.06, largest_extent * 0.025)
    gate_height = height * 2.2
    gate_depth = max(width, depth) * 3.6
    left_gate_x = center.x() - compression_width * 0.5
    right_gate_start_x = center.x() + width * 1.45
    right_gate_end_x = center.x() + compression_width * 0.5

    stopper = geometry_object.createNode("box", "LEFT_COMPRESSION_GATE")
    set_if_present(stopper, "sizex", gate_thickness)
    set_if_present(stopper, "sizey", gate_height)
    set_if_present(stopper, "sizez", gate_depth)
    set_if_present(stopper, "tx", left_gate_x)
    set_if_present(stopper, "ty", gate_height * 0.5)
    set_if_present(stopper, "tz", center.z())

    pusher = geometry_object.createNode("box", "RIGHT_COMPRESSION_GATE")
    set_if_present(pusher, "sizex", gate_thickness)
    set_if_present(pusher, "sizey", gate_height)
    set_if_present(pusher, "sizez", gate_depth)
    set_if_present(pusher, "ty", gate_height * 0.5)
    set_if_present(pusher, "tz", center.z())
    pusher.parm("tx").setExpression(
        (
            f"if($F<26,{right_gate_start_x},"
            f"if($F<58,fit($F,26,58,{right_gate_start_x},{right_gate_end_x}),"
            f"{right_gate_end_x}))"
        ),
        language=hou.exprLanguage.Hscript,
    )

    collisions = geometry_object.createNode("merge", "FLOOR_AND_BUNCHING_COLLIDERS")
    collisions.setInput(0, floor)
    collisions.setInput(1, stopper)
    collisions.setInput(2, pusher)

    solver = geometry_object.createNode("vellumsolver", "VELLUM_FLOOR_SOLVER")
    solver.setInput(0, cloth_constraints, 0)
    solver.setInput(1, cloth_constraints, 1)
    solver.setInput(2, collisions)
    solver.parm("startframe").set(1)
    solver.parm("simulationtype").set("dynamic")
    solver.parm("substeps").set(4)
    solver.parm("niter").set(110)
    solver.parm("collisionsiter").set(10)
    solver.parm("postcollisioniter").set(5)
    solver.parm("resolveall").set(1)
    solver.parm("doselfcollisions").set(1)
    solver.parm("gravityy").set(-9.8)
    solver.parm("timescale").set(0.74)
    solver.parm("veldamping").set(0.11)
    solver.parm("angveldamping").set(0.08)
    solver.parm("cachemaxsize").set(8000)

    normals = geometry_object.createNode("normal", "RECOMPUTE_NORMALS")
    normals.setInput(0, solver, 0)
    set_if_present(normals, "cuspangle", 58.0)
    output_null = geometry_object.createNode("null", "OUT_FLOOR_DRAPE_V3")
    output_null.setInput(0, normals)
    output_null.setDisplayFlag(True)
    output_null.setRenderFlag(True)
    geometry_object.layoutChildren()

    hou.setFrame(1)
    rest_proxy_geometry = proxy_rest.geometry()
    if not rest_proxy_geometry.points():
        raise RuntimeError("Source-derived rest proxy is empty")
    rest_proxy_geometry.saveToFile(str(proxy_rest_path))

    hou.setFrame(SETTLED_FRAME)
    simulated_proxy = solver.geometry()
    deformed_geometry = output_null.geometry()
    if not deformed_geometry.points() or not simulated_proxy.points():
        raise RuntimeError("Vellum floor proof produced empty geometry")
    simulated_proxy.saveToFile(str(proxy_sim_path))
    deformed_geometry.saveToFile(str(output_obj))
    hou.hipFile.save(str(scene_path))
    if output_obj.stat().st_size < 1024:
        raise RuntimeError(f"OBJ export failed: {output_obj}")

    metadata = {
        "schemaVersion": 3,
        "createdAt": "2026-07-28",
        "objectId": args.object_id,
        "name": plan_item["name"],
        "status": "non-commercial-apprentice-floor-pilot",
        "houdiniVersion": hou.applicationVersionString(),
        "licenseCategory": str(hou.licenseCategory()),
        "solver": "Houdini Vellum",
        "method": (
            "UV-preserving source-derived cloth surface + tipped floor drop + "
            "self collision + lateral floor compression; direct simulated render"
        ),
        "proxyKind": kind,
        "materialClass": material_class,
        "structureMode": plan_item["structureMode"],
        "frame": SETTLED_FRAME,
        "source": source_public_path,
        "proxyReductionPercentage": proxy_reduction_percentage,
        "collision": "Actual floor plus lateral compression gates",
        "counts": {
            "sourcePoints": len(source_geometry.points()),
            "sourcePrimitives": source_primitives,
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
            "The proof frame is settled on a real floor collider.",
            "No volume struts or mannequin-like support are used.",
            "Vertical side gates bunch the cloth without supporting it from below.",
            "The simulation and render surface is reduced from this exact garment.",
            "No cage, Cloth Capture, or Point Deform transfer is used.",
            "UVs and source surface attributes stay on the simulated surface.",
        ],
    }
    metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
