"""Build C4D face and eyelash point caches from the Blender Spin shapes.

The source and target meshes have different topology but share the Abby facial
UV layout.  Each target face vertex is located on a source UV triangle, the
source shape displacement is barycentrically sampled, and a robust similarity
transform moves that displacement into the C4D face's local coordinate system.
The C4D base mesh and textures remain authoritative.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


def uv_candidates(payload: dict) -> list[list[np.ndarray]]:
    result: list[list[np.ndarray]] = [list() for _ in payload["points"]]
    for polygon, uvw in zip(payload["polygons"], payload["uvw"]):
        corners = 3 if polygon[2] == polygon[3] else 4
        for corner in range(corners):
            vertex_index = int(polygon[corner])
            value = np.asarray(uvw[corner][:2], dtype=np.float64)
            if not any(np.linalg.norm(value - prior) < 1.0e-7 for prior in result[vertex_index]):
                result[vertex_index].append(value)
    return result


def barycentric(point: np.ndarray, triangle: np.ndarray) -> np.ndarray | None:
    a, b, c = triangle
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = float(v0 @ v0)
    d01 = float(v0 @ v1)
    d11 = float(v1 @ v1)
    d20 = float(v2 @ v0)
    d21 = float(v2 @ v1)
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1.0e-14:
        return None
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    return np.asarray([1.0 - v - w, v, w], dtype=np.float64)


def locate_uvs(
    candidates: list[list[np.ndarray]],
    triangle_uvs: np.ndarray,
    flip_v: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    centroids = triangle_uvs.mean(axis=1)
    tree = cKDTree(centroids)
    triangle_index = np.full(len(candidates), -1, dtype=np.int32)
    bary = np.zeros((len(candidates), 3), dtype=np.float32)
    chosen_uv = np.zeros((len(candidates), 2), dtype=np.float32)
    for vertex_index, values in enumerate(candidates):
        best = None
        for original_uv in values:
            uv = original_uv.copy()
            if flip_v:
                uv[1] = 1.0 - uv[1]
            _distance, indices = tree.query(uv, k=min(48, len(centroids)))
            indices = np.atleast_1d(indices)
            for source_triangle in indices:
                weights = barycentric(uv, triangle_uvs[int(source_triangle)])
                if weights is None:
                    continue
                minimum = float(weights.min())
                if minimum >= -2.0e-4:
                    score = minimum
                    if best is None or score > best[0]:
                        best = (score, int(source_triangle), weights, uv)
                    break
        if best is not None:
            _score, source_triangle, weights, uv = best
            triangle_index[vertex_index] = source_triangle
            bary[vertex_index] = weights
            chosen_uv[vertex_index] = uv
    return triangle_index, bary, chosen_uv


def sample_triangles(
    points: np.ndarray,
    triangles: np.ndarray,
    triangle_index: np.ndarray,
    bary: np.ndarray,
) -> np.ndarray:
    selected = triangles[triangle_index]
    values = points[selected]
    return np.einsum("ni,nij->nj", bary, values)


def similarity(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    keep = np.ones(len(source), dtype=bool)
    linear = np.eye(3)
    translation = np.zeros(3)
    residual = np.zeros(len(source))
    for _iteration in range(5):
        x = source[keep]
        y = target[keep]
        mean_x = x.mean(axis=0)
        mean_y = y.mean(axis=0)
        centered_x = x - mean_x
        centered_y = y - mean_y
        covariance = centered_y.T @ centered_x / max(len(x), 1)
        u, singular, vt = np.linalg.svd(covariance)
        correction = np.eye(3)
        if np.linalg.det(u @ vt) < 0.0:
            correction[-1, -1] = -1.0
        rotation = u @ correction @ vt
        variance = float(np.sum(centered_x * centered_x) / max(len(x), 1))
        scale = float(np.sum(singular * np.diag(correction)) / max(variance, 1.0e-12))
        linear = scale * rotation
        translation = mean_y - mean_x @ linear.T
        predicted = source @ linear.T + translation
        residual = np.linalg.norm(predicted - target, axis=1)
        threshold = np.percentile(residual[keep], 72.0)
        keep = residual <= threshold
    return linear, translation, residual


def write_frames(path: Path, frames: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite {path}")
    np.asarray(frames, dtype="<f4").tofile(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-npz", type=Path, required=True)
    parser.add_argument("--target-face-json", type=Path, required=True)
    parser.add_argument("--target-lashes-json", type=Path, required=True)
    parser.add_argument("--output-face-bin", type=Path, required=True)
    parser.add_argument("--output-lashes-bin", type=Path, required=True)
    parser.add_argument("--output-map-npz", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument(
        "--linear-mode",
        choices=("blender-c4d", "fit"),
        default="blender-c4d",
    )
    args = parser.parse_args()
    paths = {
        key: value.expanduser().resolve()
        for key, value in {
            "source": args.source_npz,
            "face": args.target_face_json,
            "lashes": args.target_lashes_json,
            "faceBin": args.output_face_bin,
            "lashesBin": args.output_lashes_bin,
            "map": args.output_map_npz,
            "report": args.report_json,
        }.items()
    }
    for key in ("source", "face", "lashes"):
        if not paths[key].is_file():
            raise RuntimeError(f"Missing {key}: {paths[key]}")
    for key in ("faceBin", "lashesBin", "map", "report"):
        if paths[key].exists():
            raise RuntimeError(f"Refusing to overwrite {paths[key]}")
        paths[key].parent.mkdir(parents=True, exist_ok=True)

    source = np.load(paths["source"])
    face_payload = json.loads(paths["face"].read_text())
    lashes_payload = json.loads(paths["lashes"].read_text())
    target_face = np.asarray(face_payload["points"], dtype=np.float64)
    target_lashes = np.asarray(lashes_payload["points"], dtype=np.float64)
    candidates = uv_candidates(face_payload)

    choices = []
    for flip_v in (False, True):
        triangle_index, bary, chosen_uv = locate_uvs(
            candidates, source["triangle_uvs"].astype(np.float64), flip_v
        )
        choices.append((int(np.sum(triangle_index >= 0)), flip_v, triangle_index, bary, chosen_uv))
    mapped_count, flip_v, triangle_index, bary, chosen_uv = max(choices, key=lambda item: item[0])
    mapped = triangle_index >= 0
    if mapped_count < int(len(target_face) * 0.5):
        raise RuntimeError(f"UV mapping coverage is too low: {mapped_count}/{len(target_face)}")

    source_basis_mapped = sample_triangles(
        source["basis"].astype(np.float64),
        source["triangles"],
        triangle_index[mapped],
        bary[mapped].astype(np.float64),
    )
    if args.linear_mode == "blender-c4d":
        # Both meshes store their facial coordinates locally before the C4D
        # object's scene rotation. Blender uses meters with +Z up; the C4D face
        # uses centimeters with -Z up. Depth stays on local Y. The C4D object
        # matrix performs the later scene-axis conversion, so it must not be
        # applied here a second time.
        linear = np.asarray(
            [
                [100.0, 0.0, 0.0],
                [0.0, 100.0, 0.0],
                [0.0, 0.0, -100.0],
            ],
            dtype=np.float64,
        )
        translation = np.median(
            target_face[mapped] - source_basis_mapped @ linear.T,
            axis=0,
        )
        residual = np.linalg.norm(
            source_basis_mapped @ linear.T + translation - target_face[mapped],
            axis=1,
        )
    else:
        linear, translation, residual = similarity(
            source_basis_mapped, target_face[mapped]
        )

    frame_count = len(source["frames"])
    face_frames = np.repeat(target_face[None, :, :], frame_count, axis=0).astype(np.float32)
    source_triangles = source["triangles"]
    selected_triangles = source_triangles[triangle_index[mapped]]
    mapped_bary = bary[mapped].astype(np.float64)
    for frame_index in range(frame_count):
        source_frame_mapped = np.einsum(
            "ni,nij->nj",
            mapped_bary,
            source["positions"][frame_index][selected_triangles],
        )
        delta = (source_frame_mapped - source_basis_mapped) @ linear.T
        face_frames[frame_index, mapped] += delta.astype(np.float32)

    target_tree = cKDTree(target_face)
    lash_distance, lash_nearest = target_tree.query(target_lashes, k=1)
    face_delta = face_frames - target_face[None, :, :]
    lashes_frames = (
        target_lashes[None, :, :] + face_delta[:, lash_nearest, :]
    ).astype(np.float32)

    write_frames(paths["faceBin"], face_frames)
    write_frames(paths["lashesBin"], lashes_frames)
    np.savez_compressed(
        paths["map"],
        frames=source["frames"],
        triangle_index=triangle_index,
        bary=bary,
        chosen_uv=chosen_uv,
        mapped=mapped,
        linear=linear,
        translation=translation,
        residual=residual,
        lash_nearest=lash_nearest,
        lash_distance=lash_distance,
    )

    samples = []
    for frame in (0, 90, 170, 270, 365):
        index = int(np.where(source["frames"] == frame)[0][0])
        delta = np.linalg.norm(face_delta[index], axis=1)
        samples.append(
            {
                "frame": frame,
                "maxTargetDelta": float(delta.max()),
                "meanMappedTargetDelta": float(delta[mapped].mean()),
            }
        )
    report = {
        "source": str(paths["source"]),
        "targetFace": str(paths["face"]),
        "targetLashes": str(paths["lashes"]),
        "faceCache": str(paths["faceBin"]),
        "lashesCache": str(paths["lashesBin"]),
        "mapping": str(paths["map"]),
        "frames": [int(source["frames"][0]), int(source["frames"][-1])],
        "frameCount": frame_count,
        "facePoints": len(target_face),
        "lashPoints": len(target_lashes),
        "mappedFacePoints": mapped_count,
        "coverage": float(mapped_count / len(target_face)),
        "targetVFlipped": bool(flip_v),
        "linearMode": args.linear_mode,
        "alignmentLinear": linear.tolist(),
        "alignmentTranslation": translation.tolist(),
        "alignmentMedianResidual": float(np.median(residual)),
        "alignmentP90Residual": float(np.percentile(residual, 90.0)),
        "lashNearestMedianDistance": float(np.median(lash_distance)),
        "samples": samples,
        "faceCacheBytes": paths["faceBin"].stat().st_size,
        "lashesCacheBytes": paths["lashesBin"].stat().st_size,
    }
    paths["report"].write_text(json.dumps(report, indent=2))
    print("ABBY_SPIN_FACE_UV_CACHE=" + json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
