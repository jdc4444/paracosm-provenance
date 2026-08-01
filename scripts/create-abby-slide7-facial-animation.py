"""Transfer the slide-7 Abby facial beat onto the derived 1:1 C4D look-match.

The input document is opened read-only. Only a named set of MetaHuman facial
joint tracks is replaced, and the result is always saved as a separate Cinema
4D project. The canonical Abby material master is never modified.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
from pathlib import Path

import c4d


FPS = 25
END_FRAME = 398
END_SECONDS = END_FRAME / FPS
MARKER_NAME = "SLIDE7_FACIAL_REFERENCE__CODEX_20260729"


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def component_desc_id(vector_parameter: int, component: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(vector_parameter, c4d.DTYPE_VECTOR, 0),
        c4d.DescLevel(component, c4d.DTYPE_REAL, 0),
    )


def find_control(doc, name: str):
    matches = [
        op
        for op in walk_objects(doc.GetFirstObject())
        if op.GetName() == name and "root.002/" in object_path(op)
    ]
    if len(matches) != 1:
        paths = [object_path(item) for item in matches]
        raise RuntimeError(
            f"Expected one root.002 control named {name}; found {paths}"
        )
    return matches[0]


def find_scene_object(doc, name: str):
    matches = [
        item for item in walk_objects(doc.GetFirstObject()) if item.GetName() == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one scene object named {name}, found {len(matches)}")
    return matches[0]


def coordinate_key(values, precision: int = 5) -> tuple[float, float, float]:
    return tuple(round(float(value), precision) for value in values)


def repair_facial_weights(doc, weight_path: Path) -> dict[str, object]:
    """Restore facial weights lost by the C4D export from Blender's source."""

    with gzip.open(weight_path, "rt", encoding="utf-8") as handle:
        source = json.load(handle)
    report = {
        "source": str(weight_path),
        "objects": {},
        "groupsImported": 0,
        "weightsImported": 0,
    }
    controls = {
        item.GetName(): item
        for item in walk_objects(doc.GetFirstObject())
        if "root.002/" in object_path(item)
    }
    for object_name, payload in source["objects"].items():
        mesh = find_scene_object(doc, object_name)
        if not isinstance(mesh, c4d.PointObject):
            raise RuntimeError(f"{object_name} is not a Cinema 4D point object")
        tag = mesh.GetTag(1019365)
        if tag is None:
            raise RuntimeError(f"{object_name} has no CA weight tag")

        blender_vertices = payload["vertices"]
        exact = {}
        for index, vertex in enumerate(blender_vertices):
            exact.setdefault(coordinate_key(vertex), []).append(index)
        blender_to_c4d: dict[int, list[int]] = {}
        unmatched = []
        for c4d_index, point in enumerate(mesh.GetAllPoints()):
            candidates = exact.get(coordinate_key((point.x, point.y, point.z)))
            if candidates:
                blender_to_c4d.setdefault(candidates[0], []).append(c4d_index)
            else:
                unmatched.append((c4d_index, point))

        # Coordinate identity covers the production meshes. The small fallback
        # handles harmless precision drift without hiding a topology mismatch.
        cell_size = 0.02
        spatial = {}
        for index, vertex in enumerate(blender_vertices):
            cell = tuple(round(value / cell_size) for value in vertex)
            spatial.setdefault(cell, []).append(index)
        fallback_matches = 0
        max_distance = 0.0
        for c4d_index, point in unmatched:
            cell = tuple(
                round(value / cell_size) for value in (point.x, point.y, point.z)
            )
            candidates = []
            for x in range(cell[0] - 1, cell[0] + 2):
                for y in range(cell[1] - 1, cell[1] + 2):
                    for z in range(cell[2] - 1, cell[2] + 2):
                        candidates.extend(spatial.get((x, y, z), []))
            if not candidates:
                continue
            closest = min(
                candidates,
                key=lambda index: (
                    (blender_vertices[index][0] - point.x) ** 2
                    + (blender_vertices[index][1] - point.y) ** 2
                    + (blender_vertices[index][2] - point.z) ** 2
                ),
            )
            squared_distance = (
                (blender_vertices[closest][0] - point.x) ** 2
                + (blender_vertices[closest][1] - point.y) ** 2
                + (blender_vertices[closest][2] - point.z) ** 2
            )
            distance = math.sqrt(squared_distance)
            if distance > 0.05:
                continue
            blender_to_c4d.setdefault(closest, []).append(c4d_index)
            fallback_matches += 1
            max_distance = max(max_distance, distance)

        imported_groups = 0
        imported_weights = 0
        for group_name, sparse_weights in payload["groups"].items():
            joint = controls.get(group_name)
            if joint is None:
                continue
            joint_index = tag.FindJoint(joint)
            if joint_index == c4d.NOTOK:
                continue
            weights = [0.0] * mesh.GetPointCount()
            assigned = 0
            for blender_index, value in sparse_weights:
                for c4d_index in blender_to_c4d.get(blender_index, ()):
                    weights[c4d_index] = float(value)
                    assigned += 1
            if assigned == 0:
                continue
            tag.SetWeightMap(joint_index, weights)
            imported_groups += 1
            imported_weights += assigned
        tag.WeightDirty()
        tag.Message(c4d.MSG_UPDATE)
        report["objects"][object_name] = {
            "c4dVertices": mesh.GetPointCount(),
            "blenderVertices": payload["vertexCount"],
            "exactMatches": mesh.GetPointCount() - len(unmatched),
            "fallbackMatches": fallback_matches,
            "unmatched": len(unmatched) - fallback_matches,
            "maxFallbackDistance": max_distance,
            "groupsImported": imported_groups,
            "weightsImported": imported_weights,
        }
        report["groupsImported"] += imported_groups
        report["weightsImported"] += imported_weights
    return report


def strip_baked_object_tracks(doc) -> int:
    """Bake the evaluated neutral pose and remove redundant static key data.

    The source contains a full set of frame-by-frame object tracks whose values
    never change. Retaining those tracks in a newly saved Cinema 4D document
    creates duplicate legacy description markers and makes Commandline repair
    tens of thousands of entries every time it opens the derived file.
    """

    removed = 0
    for item in walk_objects(doc.GetFirstObject()):
        position = item.GetRelPos()
        rotation = item.GetRelRot()
        scale = item.GetRelScale()
        tracks = list(item.GetCTracks())
        for track in tracks:
            track.Remove()
            removed += 1
        if tracks:
            item.SetRelPos(position)
            item.SetRelRot(rotation)
            item.SetRelScale(scale)
    return removed


def remove_track(item, desc_id: c4d.DescID) -> None:
    track = item.FindCTrack(desc_id)
    if track is not None:
        track.Remove()


def add_curve(
    item,
    desc_id: c4d.DescID,
    samples: list[tuple[float, float]],
    interpolation: int,
) -> int:
    remove_track(item, desc_id)
    track = c4d.CTrack(item, desc_id)
    track[c4d.ID_CTRACK_ANIMOFF] = True
    item.InsertTrackSorted(track)
    curve = track.GetCurve()
    if curve is None:
        raise RuntimeError(f"Could not create curve for {item.GetName()}")
    for seconds, value in samples:
        frame = round(seconds * FPS)
        added = curve.AddKey(c4d.BaseTime(frame, FPS))
        key = added["key"]
        key.SetValue(curve, value)
        key.SetInterpolation(curve, interpolation)
    return len(samples)


def radians(value: float) -> float:
    return math.radians(value)


def angular_samples(
    base_value: float, offsets: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    return [
        (seconds, base_value + radians(degrees))
        for seconds, degrees in offsets
    ]


def position_samples(
    base_value: float, offsets: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    return [
        (seconds, base_value + offset) for seconds, offset in offsets
    ]


def blink_offsets() -> list[tuple[float, float]]:
    """Return a restrained three-blink loop with two longer eye rests."""

    samples = [(0.0, 0.0)]
    shapes = (
        (
            (1.84, 0.0),
            (1.92, 0.52),
            (2.00, 1.0),
            (2.04, 1.0),
            (2.12, 0.45),
            (2.20, 0.0),
        ),
        (
            (7.52, 0.0),
            (7.64, 0.55),
            (7.76, 1.0),
            (7.96, 1.0),
            (8.08, 0.48),
            (8.24, 0.0),
        ),
        (
            (12.52, 0.0),
            (12.64, 0.55),
            (12.76, 1.0),
            (13.08, 1.0),
            (13.20, 0.48),
            (13.36, 0.0),
        ),
    )
    for shape in shapes:
        samples.extend(shape)
    samples.append((END_SECONDS, 0.0))
    return samples


def scaled_offsets(
    offsets: list[tuple[float, float]], scale: float
) -> list[tuple[float, float]]:
    return [(seconds, value * scale) for seconds, value in offsets]


def bake_eyelid_pla(
    doc,
    weighted_eyelids: tuple[str, ...],
    controls: dict[str, c4d.BaseObject],
    base_positions: dict[str, c4d.Vector],
) -> dict[str, object]:
    """Bake repaired joint deformation into reliable point-level blink keys."""

    meshes = {
        name: find_scene_object(doc, name)
        for name in ("Face.001", "Eye_Lashes.001")
    }
    base_points = {
        name: [c4d.Vector(point) for point in mesh.GetAllPoints()]
        for name, mesh in meshes.items()
    }

    def deformed_points(mesh):
        cache = mesh.GetDeformCache()
        if cache is None or not isinstance(cache, c4d.PointObject):
            raise RuntimeError(f"{mesh.GetName()} has no point deform cache")
        return [c4d.Vector(point) for point in cache.GetAllPoints()]

    for name in weighted_eyelids:
        controls[name].SetRelPos(base_positions[name])
        controls[name].Message(c4d.MSG_UPDATE)
    doc.ExecutePasses(None, True, True, True, 0)
    neutral = {
        name: deformed_points(mesh) for name, mesh in meshes.items()
    }

    for name in weighted_eyelids:
        position = c4d.Vector(base_positions[name])
        position.y += -1.35 if "Upper" in name else 0.25
        controls[name].SetRelPos(position)
        controls[name].Message(c4d.MSG_UPDATE)
    doc.ExecutePasses(None, True, True, True, 0)
    closed = {
        name: deformed_points(mesh) for name, mesh in meshes.items()
    }

    for name in weighted_eyelids:
        controls[name].SetRelPos(base_positions[name])
        controls[name].Message(c4d.MSG_UPDATE)
    doc.ExecutePasses(None, True, True, True, 0)

    report = {"type": "Baked PLA", "meshes": {}, "keys": 0}
    desc_id = c4d.DescID(c4d.DescLevel(c4d.CTpla, c4d.CTpla, 0))
    for name, mesh in meshes.items():
        deltas = [
            closed[name][index] - neutral[name][index]
            for index in range(len(base_points[name]))
        ]
        existing = mesh.FindCTrack(desc_id)
        if existing is not None:
            existing.Remove()
        track = c4d.CTrack(mesh, desc_id)
        track[c4d.ID_CTRACK_ANIMOFF] = True
        mesh.InsertTrackSorted(track)
        curve = track.GetCurve()
        for seconds, closure in blink_offsets():
            frame = round(seconds * FPS)
            mesh.SetAllPoints(
                [
                    base_points[name][index] + deltas[index] * closure
                    for index in range(len(deltas))
                ]
            )
            mesh.Message(c4d.MSG_UPDATE)
            added = curve.AddKey(c4d.BaseTime(frame, FPS))
            if not track.FillKey(doc, mesh, added["key"]):
                raise RuntimeError(f"Could not fill PLA key for {name} frame {frame}")
        mesh.SetAllPoints(base_points[name])
        mesh.Message(c4d.MSG_UPDATE)
        moved = [delta.GetLength() for delta in deltas]
        report["meshes"][name] = {
            "pointCount": len(deltas),
            "movedPoints": sum(value > 1.0e-6 for value in moved),
            "maxDelta": max(moved, default=0.0),
            "keys": len(blink_offsets()),
        }
        report["keys"] += len(blink_offsets())
    doc.ExecutePasses(None, True, True, True, 0)
    return report


def animation_driver_code(
    animated_names: tuple[str, ...],
    weighted_eyelids: tuple[str, ...],
    base_positions: dict[str, c4d.Vector],
) -> str:
    """Build the embedded driver that evaluates after the imported Unreal Take."""

    names = repr(tuple(animated_names))
    eyelids = repr(tuple(weighted_eyelids))
    positions = repr(
        {
            name: (
                float(base_positions[name].x),
                float(base_positions[name].y),
                float(base_positions[name].z),
            )
            for name in weighted_eyelids
        }
    )
    blinks = repr(tuple(blink_offsets()))
    return f'''import c4d

ANIMATED_NAMES = {names}
WEIGHTED_EYELIDS = {eyelids}
BASE_POSITIONS = {positions}
BLINK_SAMPLES = {blinks}


def walk_objects(item):
    while item:
        yield item
        child = item.GetDown()
        if child:
            yield from walk_objects(child)
        item = item.GetNext()


def object_path(item):
    names = []
    while item:
        names.insert(0, item.GetName())
        item = item.GetUp()
    return "/".join(names)


def sample_blink(seconds):
    if seconds <= BLINK_SAMPLES[0][0]:
        return BLINK_SAMPLES[0][1]
    for index in range(1, len(BLINK_SAMPLES)):
        right_time, right_value = BLINK_SAMPLES[index]
        if seconds <= right_time:
            left_time, left_value = BLINK_SAMPLES[index - 1]
            span = max(right_time - left_time, 1.0e-8)
            amount = (seconds - left_time) / span
            amount = amount * amount * (3.0 - 2.0 * amount)
            return left_value + (right_value - left_value) * amount
    return BLINK_SAMPLES[-1][1]


def main():
    current_time = doc.GetTime()
    seconds = current_time.Get()
    wanted = set(ANIMATED_NAMES) | set(WEIGHTED_EYELIDS)
    controls = {{}}
    for item in walk_objects(doc.GetFirstObject()):
        if item.GetName() in wanted and "root.002/" in object_path(item):
            controls[item.GetName()] = item

    for name in ANIMATED_NAMES:
        item = controls.get(name)
        if item is None:
            continue
        for track in item.GetCTracks():
            curve = track.GetCurve()
            if curve is None:
                continue
            item.SetParameter(
                track.GetDescriptionID(),
                curve.GetValue(current_time),
                c4d.DESCFLAGS_SET_0,
            )

    closure = sample_blink(seconds)
    for name in WEIGHTED_EYELIDS:
        item = controls.get(name)
        if item is None:
            continue
        x, y, z = BASE_POSITIONS[name]
        y += (-1.35 if "Upper" in name else 0.25) * closure
        item.SetRelPos(c4d.Vector(x, y, z))
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--blender-weights", type=Path)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if source == output:
        raise RuntimeError("The derived animation output cannot overwrite its source")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing derived scene: {output}")

    doc = c4d.documents.LoadDocument(
        str(source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {source}")

    report = {
        "source": str(source),
        "output": str(output),
        "masterUntouched": True,
        "fps": FPS,
        "durationSeconds": END_SECONDS,
        "lastFrame": END_FRAME,
        "controls": [],
        "curves": 0,
        "keys": 0,
        "redundantStaticTracksRemoved": 0,
        "weightRepair": None,
        "eyelidDriver": None,
        "takeOverrideDriver": None,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        source_fps = doc.GetFps()
        doc.SetTime(c4d.BaseTime(0, source_fps))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )

        weighted_eyelids = tuple(
            f"FACIAL_{side}_Eyelid{vertical}{row}{index}"
            for side in ("L", "R")
            for vertical in ("Upper", "Lower")
            for row in ("A", "B")
            for index in (1, 2, 3)
        )
        names = (
            "head",
            "FACIAL_L_Eye",
            "FACIAL_R_Eye",
            "FACIAL_L_EyelidUpperA",
            "FACIAL_R_EyelidUpperA",
            "FACIAL_L_EyelidLowerA",
            "FACIAL_R_EyelidLowerA",
            "FACIAL_C_Jaw",
            "FACIAL_C_LowerLipRotation",
            "FACIAL_C_MouthUpper",
            "FACIAL_L_LipCorner",
            "FACIAL_R_LipCorner",
        ) + weighted_eyelids
        controls = {name: find_control(doc, name) for name in names}
        bases = {name: item.GetRelRot() for name, item in controls.items()}
        base_positions = {
            name: item.GetRelPos() for name, item in controls.items()
        }
        report["redundantStaticTracksRemoved"] = strip_baked_object_tracks(doc)
        if args.blender_weights:
            report["weightRepair"] = repair_facial_weights(
                doc, args.blender_weights.expanduser().resolve()
            )

        doc.SetFps(FPS)
        doc.SetMinTime(c4d.BaseTime(0, FPS))
        doc.SetMaxTime(c4d.BaseTime(END_FRAME, FPS))
        doc.SetLoopMinTime(c4d.BaseTime(0, FPS))
        doc.SetLoopMaxTime(c4d.BaseTime(END_FRAME, FPS))
        report["eyelidDriver"] = bake_eyelid_pla(
            doc, weighted_eyelids, controls, base_positions
        )

        head_offsets = {
            c4d.VECTOR_X: [
                (0.0, 0.0),
                (0.8, -0.8),
                (1.6, -1.5),
                (2.4, 0.8),
                (3.2, 4.0),
                (4.2, 7.5),
                (5.4, 9.0),
                (6.5, 7.0),
                (7.6, 5.0),
                (8.6, 2.5),
                (9.6, -4.0),
                (10.6, -8.0),
                (11.6, -10.0),
                (12.6, -7.0),
                (13.6, -4.0),
                (14.6, -1.8),
                (15.3, 0.0),
                (END_SECONDS, 0.0),
            ],
            c4d.VECTOR_Y: [
                (0.0, 0.0),
                (1.6, 0.8),
                (2.4, -1.2),
                (4.2, -4.5),
                (5.4, -5.0),
                (7.6, -2.0),
                (8.6, -1.0),
                (10.6, -5.0),
                (11.6, -4.0),
                (12.6, -2.0),
                (14.6, 0.0),
                (END_SECONDS, 0.0),
            ],
            c4d.VECTOR_Z: [
                (0.0, 0.0),
                (1.6, -0.4),
                (2.4, 0.0),
                (4.2, 1.5),
                (5.4, 2.0),
                (8.6, 0.5),
                (10.6, -2.0),
                (11.6, -2.5),
                (12.6, -2.0),
                (14.6, -0.4),
                (END_SECONDS, 0.0),
            ],
        }
        for component, offsets in head_offsets.items():
            keys = add_curve(
                controls["head"],
                component_desc_id(c4d.ID_BASEOBJECT_REL_ROTATION, component),
                angular_samples(bases["head"][component - c4d.VECTOR_X], offsets),
                c4d.CINTERPOLATION_SPLINE,
            )
            report["curves"] += 1
            report["keys"] += keys

        eye_offsets = {
            c4d.VECTOR_X: [
                (0.0, 0.0),
                (0.42, -2.0),
                (0.82, 1.0),
                (1.18, -1.5),
                (1.58, 2.0),
                (2.15, 0.0),
                (2.48, 5.0),
                (2.86, -3.0),
                (3.22, 4.0),
                (3.62, 7.0),
                (4.05, 2.0),
                (4.42, 7.0),
                (4.86, 3.0),
                (5.28, -4.0),
                (5.72, -7.0),
                (6.18, -3.0),
                (6.62, 4.0),
                (7.08, -5.0),
                (7.48, 2.0),
                (8.18, 7.0),
                (8.58, -5.0),
                (8.96, 4.0),
                (9.38, 8.0),
                (9.82, 3.0),
                (10.25, -4.0),
                (10.72, 8.0),
                (11.18, 10.0),
                (11.62, 3.0),
                (12.08, -4.0),
                (12.52, 4.0),
                (13.18, -2.0),
                (13.72, 3.0),
                (14.18, -3.0),
                (14.62, 1.5),
                (15.18, -1.0),
                (END_SECONDS, 0.0),
            ],
            c4d.VECTOR_Y: [
                (0.0, 0.0),
                (0.42, 1.0),
                (0.82, -1.0),
                (1.18, 0.5),
                (1.58, -2.0),
                (2.15, 0.0),
                (2.48, -2.0),
                (2.86, -4.0),
                (3.22, -2.0),
                (3.62, -5.0),
                (4.05, -2.0),
                (4.42, -5.0),
                (4.86, -2.0),
                (5.28, 0.0),
                (5.72, -2.0),
                (6.18, 1.0),
                (6.62, -3.0),
                (7.08, -1.0),
                (7.48, -4.0),
                (8.18, -5.0),
                (8.58, -2.0),
                (8.96, -5.0),
                (9.38, -7.0),
                (9.82, -4.0),
                (10.25, -5.0),
                (10.72, -8.0),
                (11.18, -7.0),
                (11.62, -5.0),
                (12.08, -2.0),
                (12.52, -4.0),
                (13.18, -1.0),
                (13.72, -3.0),
                (14.18, 0.0),
                (14.62, -1.5),
                (15.18, 0.0),
                (END_SECONDS, 0.0),
            ],
        }
        for name in ("FACIAL_L_Eye", "FACIAL_R_Eye"):
            for component, offsets in eye_offsets.items():
                keys = add_curve(
                    controls[name],
                    component_desc_id(
                        c4d.ID_BASEOBJECT_REL_ROTATION, component
                    ),
                    angular_samples(
                        bases[name][component - c4d.VECTOR_X], offsets
                    ),
                    c4d.CINTERPOLATION_SPLINE,
                )
                report["curves"] += 1
                report["keys"] += keys

        blink = blink_offsets()
        jaw_offsets = [
            (0.0, 0.0),
            (0.35, 0.7),
            (0.72, 0.0),
            (1.08, 1.5),
            (1.46, 0.3),
            (1.78, 1.0),
            (2.18, 0.0),
            (2.68, 0.8),
            (3.12, 0.0),
            (3.58, 1.0),
            (4.18, 0.0),
            (4.72, 1.2),
            (5.22, 2.0),
            (5.68, 0.5),
            (6.02, 2.5),
            (6.34, 4.0),
            (6.68, 3.0),
            (7.02, 4.5),
            (7.34, 3.0),
            (7.66, 4.0),
            (8.02, 2.5),
            (8.38, 4.0),
            (8.78, 2.0),
            (9.16, 0.2),
            (9.58, 0.0),
            (10.36, 0.6),
            (10.82, 0.0),
            (11.78, 0.5),
            (12.38, 0.0),
            (12.88, 0.8),
            (13.28, 2.5),
            (13.62, 3.2),
            (13.98, 1.2),
            (14.38, 0.0),
            (14.98, 0.5),
            (15.38, 0.0),
            (END_SECONDS, 0.0),
        ]
        keys = add_curve(
            controls["FACIAL_C_Jaw"],
            component_desc_id(
                c4d.ID_BASEOBJECT_REL_ROTATION, c4d.VECTOR_Y
            ),
            angular_samples(bases["FACIAL_C_Jaw"].y, jaw_offsets),
            c4d.CINTERPOLATION_SPLINE,
        )
        report["curves"] += 1
        report["keys"] += keys

        lower_lip_offsets = [
            (0.0, 0.0),
            (0.32, 0.7),
            (0.70, 0.0),
            (1.06, 1.0),
            (1.42, 0.0),
            (1.76, 0.8),
            (2.18, 0.0),
            (2.96, 0.7),
            (3.46, 0.0),
            (4.76, 0.8),
            (5.22, 1.4),
            (5.62, 0.3),
            (6.00, 1.2),
            (6.30, 2.0),
            (6.66, 2.4),
            (7.00, 3.0),
            (7.38, 2.4),
            (7.76, 3.0),
            (8.12, 1.8),
            (8.44, 2.8),
            (8.82, 1.4),
            (9.20, 0.0),
            (10.30, 0.5),
            (10.78, 0.0),
            (12.78, 0.5),
            (13.18, 1.4),
            (13.50, 2.0),
            (13.82, 1.5),
            (14.18, 0.4),
            (14.48, 0.0),
            (15.18, 0.4),
            (15.48, 0.0),
            (END_SECONDS, 0.0),
        ]
        keys = add_curve(
            controls["FACIAL_C_LowerLipRotation"],
            component_desc_id(
                c4d.ID_BASEOBJECT_REL_ROTATION, c4d.VECTOR_Y
            ),
            angular_samples(
                bases["FACIAL_C_LowerLipRotation"].y,
                lower_lip_offsets,
            ),
            c4d.CINTERPOLATION_SPLINE,
        )
        report["curves"] += 1
        report["keys"] += keys

        upper_lip_offsets = [
            (0.0, 0.0),
            (1.06, 0.08),
            (1.42, 0.0),
            (2.96, 0.05),
            (3.46, 0.0),
            (5.22, 0.10),
            (5.62, 0.0),
            (6.30, 0.12),
            (6.66, 0.04),
            (7.00, 0.14),
            (7.38, 0.05),
            (7.76, 0.14),
            (8.12, 0.06),
            (8.44, 0.13),
            (9.20, 0.0),
            (13.18, 0.08),
            (13.50, 0.12),
            (13.82, 0.06),
            (14.48, 0.0),
            (END_SECONDS, 0.0),
        ]
        keys = add_curve(
            controls["FACIAL_C_MouthUpper"],
            component_desc_id(
                c4d.ID_BASEOBJECT_REL_POSITION, c4d.VECTOR_Y
            ),
            position_samples(
                base_positions["FACIAL_C_MouthUpper"].y,
                upper_lip_offsets,
            ),
            c4d.CINTERPOLATION_SPLINE,
        )
        report["curves"] += 1
        report["keys"] += keys

        lip_corner_offsets = [
            (0.0, 0.0),
            (0.34, -0.4),
            (0.72, 0.0),
            (1.08, -1.0),
            (1.46, 0.0),
            (2.96, 0.5),
            (3.46, 0.0),
            (4.76, -0.6),
            (5.22, 0.8),
            (5.62, 0.0),
            (6.30, -1.2),
            (6.66, 0.8),
            (7.00, -1.4),
            (7.38, 0.7),
            (7.76, -1.3),
            (8.12, 0.4),
            (8.44, -1.2),
            (9.20, 0.0),
            (10.30, 0.4),
            (10.78, 0.0),
            (13.18, -0.7),
            (13.50, -1.0),
            (13.82, 0.5),
            (14.48, 0.0),
            (END_SECONDS, 0.0),
        ]
        for name, direction in (
            ("FACIAL_L_LipCorner", 1.0),
            ("FACIAL_R_LipCorner", -1.0),
        ):
            keys = add_curve(
                controls[name],
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_ROTATION, c4d.VECTOR_X
                ),
                angular_samples(
                    bases[name].x,
                    scaled_offsets(lip_corner_offsets, direction),
                ),
                c4d.CINTERPOLATION_SPLINE,
            )
            report["curves"] += 1
            report["keys"] += keys

        marker = c4d.BaseObject(c4d.Onull)
        marker.SetName(MARKER_NAME)
        animated_track_names = (
            "head",
            "FACIAL_L_Eye",
            "FACIAL_R_Eye",
            "FACIAL_C_Jaw",
            "FACIAL_C_LowerLipRotation",
            "FACIAL_C_MouthUpper",
            "FACIAL_L_LipCorner",
            "FACIAL_R_LipCorner",
        )
        driver_tag = c4d.BaseTag(c4d.Tpython)
        driver_tag.SetName("Slide 7 Facial Animation Driver")
        driver_tag[c4d.TPYTHON_FRAME] = True
        driver_tag[c4d.TPYTHON_CODE] = animation_driver_code(
            animated_track_names,
            weighted_eyelids,
            base_positions,
        )
        driver_host = find_scene_object(doc, "root.002")
        driver_host.InsertTag(driver_tag)
        doc.InsertObject(marker)
        report["takeOverrideDriver"] = {
            "type": "Embedded Python expression",
            "host": driver_host.GetName(),
            "tag": driver_tag.GetName(),
            "animatedControls": len(animated_track_names),
            "blinkControls": len(weighted_eyelids),
        }

        render_data = doc.GetActiveRenderData()
        render_data[c4d.RDATA_XRES] = float(args.width)
        render_data[c4d.RDATA_YRES] = float(args.height)
        render_data[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_ALLFRAMES
        )
        render_data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(0, FPS)
        render_data[c4d.RDATA_FRAMETO] = c4d.BaseTime(END_FRAME, FPS)
        doc.SetTime(c4d.BaseTime(0, FPS))
        c4d.EventAdd()

        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved:
            raise RuntimeError(f"Cinema 4D could not save {output}")

        for name, item in controls.items():
            report["controls"].append(
                {"name": name, "path": object_path(item)}
            )
        print(
            "ABBY_SLIDE7_FACIAL_ANIMATION="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
