#!/usr/bin/env hython

"""Build a non-commercial Houdini Vellum static pilot for Navy Bubble Skirt."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import hou


ROOT = Path("/Users/alphaone/Documents/Code/paracosm-provenance")
OBJECT_ID = "navy-bubble-skirt"
SOURCE_GLB = ROOT / "public/archive/objects/3d/navy-bubble-skirt-v1.glb"
OUTPUT_DIR = (
    ROOT
    / "public/archive/objects/3d/simulations/navy-bubble-skirt/houdini-vellum-v1"
)
SCENE_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1.hipnc"
PROXY_REST_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-rest.bgeo.sc"
PROXY_SIM_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-frame28.bgeo.sc"
OUTPUT_OBJ = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-frame28.obj"
METADATA_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-metadata.json"
SETTLED_FRAME = 28


def set_if_present(node: hou.Node, parm_name: str, value) -> None:
    parm = node.parm(parm_name)
    if parm is not None:
        parm.set(value)


def build_proxy_geometry() -> hou.Geometry:
    """Create an open, continuous quad proxy matching the skirt's silhouette."""

    geometry = hou.Geometry()
    segments = 96
    rings = 25
    points: list[list[hou.Point]] = []

    for ring_index in range(rings):
        vertical_t = ring_index / (rings - 1)
        y = 0.61 - vertical_t * 1.22

        # A narrow, structured waistband expanding into a bubble silhouette,
        # then tucking inward at the hem.
        if vertical_t < 0.12:
            radius_x = 0.49 + vertical_t * 0.25
        else:
            body_t = (vertical_t - 0.12) / 0.88
            radius_x = (
                0.52
                + 0.44 * math.sin(min(1.0, body_t) * math.pi * 0.76)
                - 0.08 * max(0.0, (body_t - 0.78) / 0.22)
            )
        radius_z = radius_x * 0.63

        ring_points: list[hou.Point] = []
        for segment_index in range(segments):
            theta = 2.0 * math.pi * segment_index / segments
            pleat_weight = min(1.0, max(0.0, (vertical_t - 0.05) / 0.3))
            pleat = 1.0 + 0.027 * math.sin(theta * 16.0) * pleat_weight
            point = geometry.createPoint()
            point.setPosition(
                hou.Vector3(
                    math.cos(theta) * radius_x * pleat,
                    y,
                    math.sin(theta) * radius_z * pleat,
                )
            )
            ring_points.append(point)
        points.append(ring_points)

    for ring_index in range(rings - 1):
        for segment_index in range(segments):
            next_segment = (segment_index + 1) % segments
            polygon = geometry.createPolygon()
            polygon.addVertex(points[ring_index][segment_index])
            polygon.addVertex(points[ring_index][next_segment])
            polygon.addVertex(points[ring_index + 1][next_segment])
            polygon.addVertex(points[ring_index + 1][segment_index])
            polygon.setIsClosed(True)

    geometry.addAttrib(hou.attribType.Point, "rest", hou.Vector3())
    rest_attrib = geometry.findPointAttrib("rest")
    for point in geometry.points():
        point.setAttribValue(rest_attrib, point.position())
    geometry.saveToFile(str(PROXY_REST_PATH))
    return geometry


def asset_url(path: Path) -> str:
    return f"/{path.relative_to(ROOT / 'public').as_posix()}"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCE_GLB.exists():
        raise FileNotFoundError(SOURCE_GLB)

    hou.hipFile.clear(suppress_save_prompt=True)
    hou.setFps(24)
    hou.playbar.setFrameRange(1, 48)
    hou.playbar.setPlaybackRange(1, 48)

    build_proxy_geometry()

    object_context = hou.node("/obj")
    geometry_object = object_context.createNode("geo", "NAVY_BUBBLE_VELLUM_PILOT")
    for child in geometry_object.children():
        child.destroy()

    source = geometry_object.createNode("gltf::2.0", "SOURCE_MESHY_GLTF")
    source.parm("gltffile").set(str(SOURCE_GLB))
    source.parm("importnodegeometryas").set("flattenedgeometry")
    set_if_present(source, "bakedoutputmatnet", "/mat")

    source_reduce = geometry_object.createNode(
        "polyreduce::2.0", "PROOF_RENDER_REDUCTION"
    )
    source_reduce.setInput(0, source)
    source_reduce.parm("target").set("poly_percent")
    source_reduce.parm("percentage").set(28.0)
    set_if_present(source_reduce, "preservequads", 1)
    set_if_present(source_reduce, "preserveuvseams", 1)
    set_if_present(source_reduce, "preservematerialboundaries", 1)

    source_rest = geometry_object.createNode("xform", "RENDER_REST_POSITION")
    source_rest.setInput(0, source_reduce)
    source_rest.parm("ty").set(0.72)

    proxy_file = geometry_object.createNode("file", "CLEAN_BUBBLE_PROXY")
    proxy_file.parm("file").set(str(PROXY_REST_PATH))

    proxy_rest = geometry_object.createNode("xform", "PROXY_REST_POSITION")
    proxy_rest.setInput(0, proxy_file)
    proxy_rest.parm("ty").set(0.72)

    cloth_constraints = geometry_object.createNode(
        "vellumconstraints", "SATIN_CLOTH_CONSTRAINTS"
    )
    cloth_constraints.setInput(0, proxy_rest)
    cloth_constraints.parm("constrainttype").set("cloth")
    cloth_constraints.parm("domass").set("on")
    cloth_constraints.parm("mass").set(0.12)
    cloth_constraints.parm("dothickness").set("on")
    cloth_constraints.parm("thickness").set(0.012)
    cloth_constraints.parm("stretchstiffness").set(2.5)
    cloth_constraints.parm("stretchstiffnessexp").set(5)
    cloth_constraints.parm("stretchdampingratio").set(0.08)
    cloth_constraints.parm("bendstiffness").set(2.0)
    cloth_constraints.parm("bendstiffnessexp").set(-1)
    cloth_constraints.parm("benddampingratio").set(0.12)
    cloth_constraints.parm("dragnormal").set(3.0)
    cloth_constraints.parm("dragtangent").set(0.15)

    volume_struts = geometry_object.createNode(
        "vellumconstraints", "BUBBLE_VOLUME_STRUTS"
    )
    volume_struts.setInput(0, cloth_constraints, 0)
    volume_struts.setInput(1, cloth_constraints, 1)
    volume_struts.parm("constrainttype").set("surfacestruts")
    volume_struts.parm("strut_maxlen").set(1.65)
    volume_struts.parm("strut_constraintsperpt").set(2)
    volume_struts.parm("strut_testnormals").set(1)
    volume_struts.parm("strut_jitter").set(0.18)

    collider = geometry_object.createNode("sphere", "INVISIBLE_SPHERE_COLLIDER")
    collider.parm("type").set("poly")
    collider.parm("surftype").set("quads")
    collider.parm("radx").set(0.72)
    collider.parm("rady").set(0.72)
    collider.parm("radz").set(0.72)
    collider.parm("ty").set(-0.68)
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
    solver.parm("gravityy").set(-5.5)
    solver.parm("timescale").set(0.72)
    solver.parm("veldamping").set(0.12)
    solver.parm("angveldamping").set(0.08)
    solver.parm("cachemaxsize").set(8000)

    capture = geometry_object.createNode("clothcapture", "CAPTURE_RENDER_TO_PROXY")
    capture.setInput(0, source_rest)
    capture.setInput(1, proxy_rest)
    capture.parm("radius").set(0.72)

    deform = geometry_object.createNode("clothdeform", "DEFORM_RENDER_MESH")
    deform.setInput(0, capture)
    deform.setInput(1, proxy_rest)
    deform.setInput(2, solver, 0)

    normals = geometry_object.createNode("normal", "RECOMPUTE_NORMALS")
    normals.setInput(0, deform)
    set_if_present(normals, "type", 0)
    set_if_present(normals, "cuspangle", 60.0)

    output_null = geometry_object.createNode("null", "OUT_HOUDINI_VELLUM_PROOF")
    output_null.setInput(0, normals)
    output_null.setDisplayFlag(True)
    output_null.setRenderFlag(True)

    geometry_object.layoutChildren()

    hou.setFrame(SETTLED_FRAME)
    simulated_proxy = solver.geometry()
    simulated_proxy.saveToFile(str(PROXY_SIM_PATH))

    deformed_geometry = output_null.geometry()
    source_geometry = source.geometry()
    if not deformed_geometry.points() or not simulated_proxy.points():
        raise RuntimeError("Vellum pilot produced empty geometry")

    deformed_geometry.saveToFile(str(OUTPUT_OBJ))
    hou.hipFile.save(str(SCENE_PATH))
    if not OUTPUT_OBJ.exists() or OUTPUT_OBJ.stat().st_size < 1024:
        raise RuntimeError(f"OBJ export failed: {OUTPUT_OBJ}")

    rest_bounds = proxy_rest.geometry().boundingBox()
    sim_bounds = simulated_proxy.boundingBox()
    render_bounds = deformed_geometry.boundingBox()
    metadata = {
        "schemaVersion": 1,
        "createdAt": "2026-07-28",
        "objectId": OBJECT_ID,
        "status": "non-commercial-apprentice-pilot",
        "houdiniVersion": hou.applicationVersionString(),
        "licenseCategory": str(hou.licenseCategory()),
        "solver": "Houdini Vellum",
        "method": "clean quad proxy + cloth constraints + surface struts + Cloth Capture/Deform",
        "frame": SETTLED_FRAME,
        "source": asset_url(SOURCE_GLB),
        "counts": {
            "sourcePoints": len(source_geometry.points()),
            "sourcePrimitives": len(source_geometry.prims()),
            "renderPoints": len(deformed_geometry.points()),
            "renderPrimitives": len(deformed_geometry.prims()),
            "proxyPoints": len(simulated_proxy.points()),
            "proxyPrimitives": len(simulated_proxy.prims()),
        },
        "bounds": {
            "proxyRest": {
                "min": list(rest_bounds.minvec()),
                "max": list(rest_bounds.maxvec()),
            },
            "proxySimulated": {
                "min": list(sim_bounds.minvec()),
                "max": list(sim_bounds.maxvec()),
            },
            "renderSimulated": {
                "min": list(render_bounds.minvec()),
                "max": list(render_bounds.maxvec()),
            },
        },
        "assets": {
            "scene": asset_url(SCENE_PATH),
            "model": asset_url(OUTPUT_OBJ),
            "proxyRest": asset_url(PROXY_REST_PATH),
            "proxySimulated": asset_url(PROXY_SIM_PATH),
        },
        "notes": [
            "This is an explicitly non-commercial Houdini Apprentice proof.",
            "No motion render was generated.",
            "The high-detail source is deformed from a clean continuous proxy; the original Meshy topology is not used as the simulation surface.",
        ],
    }
    METADATA_PATH.write_text(f"{json.dumps(metadata, indent=2)}\n")

    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
