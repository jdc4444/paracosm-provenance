#!/usr/bin/env hython

"""Build one source-faithful floor-draped Houdini Vellum wardrobe proof.

The simulation surface is a watertight VDB remesh derived from the garment's
own silhouette. It avoids both known failure modes: a generic tube that stretches
the source during capture/deform, and direct Vellum on disconnected Meshy
fragments. The default route Point Deforms the intact UV-textured source; the
proxy-UV route renders the stable Vellum surface with projected source UVs when
disconnected source components cannot survive deformation.
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
    set_if_present,
)


REGISTRY_PATH = ROOT / "data/object-3d-versions.json"
SETTLED_FRAME = 72


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    parser.add_argument(
        "--surface-mode",
        choices=("source-deform", "proxy-uv"),
        default="source-deform",
    )
    parser.add_argument(
        "--compression-mode",
        choices=("gates", "drop-only"),
        default="gates",
    )
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


def garment_kind(object_id: str, structure_mode: str) -> str:
    if any(
        token in object_id
        for token in ("trousers", "tights", "culottes", "gloves", "socks")
    ):
        return "legs"
    if "skirt" in object_id or structure_mode == "structured-waistband":
        return "skirt"
    if any(token in object_id for token in ("dress", "gown")):
        return "dress"
    if any(
        token in object_id
        for token in (
            "top",
            "corset",
            "vest",
            "jacket",
            "blouse",
            "sweater",
            "cape",
            "coat",
            "bodysuit",
        )
    ):
        return "torso"
    return "accessory"


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
    kind = garment_kind(args.object_id, plan_item["structureMode"])
    source_public_path = current_source_model(
        args.object_id,
        plan_item["sourceModel"],
    )
    source_glb = ROOT / "public" / source_public_path.lstrip("/")
    if args.surface_mode == "proxy-uv":
        variant = "houdini-floor-v4-proxy"
    elif args.compression_mode == "drop-only":
        variant = "houdini-floor-v4-drop"
    else:
        variant = "houdini-floor-v4"
    output_dir = (
        ROOT / f"public/archive/objects/3d/simulations/{args.object_id}/{variant}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.object_id}-{variant}"
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
        f"{args.object_id.upper().replace('-', '_')}_VELLUM_FLOOR_V4",
    )
    for child in geometry_object.children():
        child.destroy()

    source = geometry_object.createNode("gltf::2.0", "SOURCE_TEXTURED_GLTF")
    source.parm("gltffile").set(str(source_glb))
    source.parm("importnodegeometryas").set("flattenedgeometry")
    source_geometry = source.geometry()
    source_bounds = source_geometry.boundingBox()
    source_primitives = len(source_geometry.prims())
    render_reduction_percentage = min(
        100.0,
        max(12.0, 240000.0 / max(1, source_primitives) * 100.0),
    )

    size = source_bounds.sizevec()
    center = source_bounds.center()
    width = max(0.1, size.x())
    height = max(0.1, size.y())
    depth = max(0.08, size.z())
    largest_extent = max(width, height, depth)
    rest_lift = -source_bounds.minvec().y() + height * 0.68

    render_reduce = geometry_object.createNode(
        "polyreduce::2.0",
        "UV_PRESERVING_TEXTURED_SOURCE",
    )
    render_reduce.setInput(0, source)
    render_reduce.parm("target").set("poly_percent")
    render_reduce.parm("percentage").set(render_reduction_percentage)
    set_if_present(render_reduce, "preserveuvseams", 1)
    set_if_present(render_reduce, "preservematerialboundaries", 1)

    source_rest = geometry_object.createNode("xform", "TEXTURED_SOURCE_REST")
    source_rest.setInput(0, render_reduce)
    configure_transform(
        source_rest,
        center=center,
        lift=rest_lift,
        material_class=material_class,
    )

    voxel_size = largest_extent / 72.0
    proxy_vdb = geometry_object.createNode(
        "vdbfrompolygons",
        "GARMENT_SILHOUETTE_WATERTIGHT_SDF",
    )
    proxy_vdb.setInput(0, source)
    proxy_vdb.parm("voxelsize").set(voxel_size)
    proxy_vdb.parm("builddistance").set(1)
    proxy_vdb.parm("buildfog").set(0)
    proxy_vdb.parm("fillinterior").set(1)
    proxy_vdb.parm("preserveholes").set(0)
    proxy_vdb.parm("exteriorbandvoxels").set(4)
    proxy_vdb.parm("interiorbandvoxels").set(4)

    proxy_surface = geometry_object.createNode(
        "convertvdb",
        "WATERTIGHT_PROXY_SURFACE",
    )
    proxy_surface.setInput(0, proxy_vdb)
    proxy_surface.parm("conversion").set("poly")
    proxy_surface.parm("adaptivity").set(0.012)
    set_if_present(proxy_surface, "computenormals", 1)

    proxy_remesh = geometry_object.createNode(
        "remesh",
        "UNIFORM_SIMULATION_TOPOLOGY",
    )
    proxy_remesh.setInput(0, proxy_surface)
    proxy_remesh.parm("targetsize").set(largest_extent / 44.0)
    proxy_remesh.parm("iterations").set(3)
    set_if_present(proxy_remesh, "recomputenormals", 1)

    proxy_uv = geometry_object.createNode(
        "attribtransfer",
        "PROJECT_SOURCE_UV_TO_STABLE_PROXY",
    )
    proxy_uv.setInput(0, proxy_remesh)
    proxy_uv.setInput(1, source)
    proxy_uv.parm("primitiveattribs").set(0)
    proxy_uv.parm("pointattribs").set(1)
    proxy_uv.parm("pointattriblist").set("uv")
    proxy_uv.parm("maxsamplecount").set(1)
    proxy_uv.parm("threshold").set(0)

    proxy_rest = geometry_object.createNode("xform", "PROXY_FLOOR_DROP_REST")
    proxy_rest.setInput(
        0,
        proxy_uv if args.surface_mode == "proxy-uv" else proxy_remesh,
    )
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
    if args.compression_mode == "gates":
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

    deform_source = geometry_object.createNode(
        "pointdeform",
        "DEFORM_INTACT_TEXTURED_SOURCE",
    )
    deform_source.setInput(0, source_rest)
    deform_source.setInput(1, proxy_rest)
    deform_source.setInput(2, solver, 0)
    # Keep the deformation neighborhood close to the garment-derived proxy.
    # A broad radius crosses from one side of layered skirts to another and
    # creates the sharp transfer spikes seen in the rejected v4 dress pilot.
    deform_radius_ratio = (
        0.07
        if kind in {"dress", "skirt"}
        or material_class
        in {
            "structured-ruffle",
            "tulle-ruffle",
            "tailored-heavy",
            "sheer-lightweight",
        }
        else 0.18
    )
    deform_source.parm("radius").set(largest_extent * deform_radius_ratio)
    deform_source.parm("minpt").set(4)
    deform_source.parm("maxpt").set(10)
    set_if_present(deform_source, "updateaffectednmls", 1)

    normals = geometry_object.createNode("normal", "RECOMPUTE_OUTPUT_NORMALS")
    normals.setInput(
        0,
        solver if args.surface_mode == "proxy-uv" else deform_source,
    )
    set_if_present(normals, "cuspangle", 58.0)
    output_null = geometry_object.createNode("null", "OUT_FLOOR_DRAPE_V4")
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
        "schemaVersion": 4,
        "createdAt": "2026-07-29",
        "objectId": args.object_id,
        "name": plan_item["name"],
        "status": "non-commercial-apprentice-floor-pilot",
        "houdiniVersion": hou.applicationVersionString(),
        "licenseCategory": str(hou.licenseCategory()),
        "solver": "Houdini Vellum",
        "method": (
            "watertight garment-silhouette VDB proxy + uniform remesh + tipped "
            "floor drop + self collision + "
            + (
                "lateral floor compression + "
                if args.compression_mode == "gates"
                else "gravity-only floor settling + "
            )
            + (
                "source UV projection directly onto stable simulated proxy"
                if args.surface_mode == "proxy-uv"
                else "close-fit Point Deform transfer to intact UV-textured source"
            )
        ),
        "surfaceMode": args.surface_mode,
        "compressionMode": args.compression_mode,
        "proxyKind": kind,
        "materialClass": material_class,
        "structureMode": plan_item["structureMode"],
        "frame": SETTLED_FRAME,
        "source": source_public_path,
        "renderReductionPercentage": render_reduction_percentage,
        "proxyVoxelSize": voxel_size,
        "deformRadiusRatio": deform_radius_ratio,
        "collision": (
            "Actual floor plus lateral compression gates"
            if args.compression_mode == "gates"
            else "Actual floor only"
        ),
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
            (
                "Vertical side gates bunch the cloth without supporting it from below."
                if args.compression_mode == "gates"
                else "The tipped garment settles by gravity and self collision without side gates."
            ),
            "The Vellum proxy is a watertight VDB remesh of this exact garment silhouette.",
            (
                "Source UVs are projected onto the stable simulated proxy; disconnected "
                "Meshy fragments are not rendered."
                if args.surface_mode == "proxy-uv"
                else "The intact textured source is never simulated as disconnected fragments."
            ),
            (
                "The stable proxy itself is the proof surface."
                if args.surface_mode == "proxy-uv"
                else "Point Deform uses the close-fitting garment-derived proxy, not a generic tube."
            ),
            (
                "The source material is reapplied to projected proxy UVs."
                if args.surface_mode == "proxy-uv"
                else "UVs and source material attributes stay on the intact source surface."
            ),
        ],
    }
    metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
