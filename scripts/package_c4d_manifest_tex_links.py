#!/usr/bin/env python3
"""Expose exact relink-manifest targets through a C4D project tex directory.

Cinema 4D node assets can serialize as bare filenames even after an in-memory
absolute-path relink. A sibling ``tex`` directory is searched again when the
saved project reopens, so this creates non-destructive symlinks for every
manifest target after proving that no basename maps to conflicting content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--source-project",
        type=Path,
        help=(
            "Optional original project whose existing relative tex resources "
            "must remain visible after the sidecar is moved."
        ),
    )
    parser.add_argument("--report-json", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    project = args.project.expanduser().resolve()
    source_project = (
        args.source_project.expanduser().resolve()
        if args.source_project is not None
        else None
    )
    report_path = args.report_json.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mappings = manifest.get("mappings") or []
    if not project.is_file():
        raise FileNotFoundError(project)
    if not mappings:
        raise RuntimeError("Manifest contains no mappings")

    by_basename: dict[str, list[dict[str, object]]] = defaultdict(list)
    missing_targets: list[str] = []
    hash_mismatches: list[dict[str, str]] = []
    for mapping in mappings:
        target = Path(str(mapping.get("targetPath") or "")).expanduser()
        basename = str(mapping.get("basename") or target.name)
        expected_hash = str(mapping.get("targetSha256") or "")
        if not target.is_file():
            missing_targets.append(str(target))
            continue
        actual_hash = sha256(target)
        if expected_hash and actual_hash != expected_hash:
            hash_mismatches.append(
                {
                    "path": str(target),
                    "expected": expected_hash,
                    "actual": actual_hash,
                }
            )
        by_basename[basename].append(
            {
                "target": str(target.resolve()),
                "sha256": actual_hash,
            }
        )

    conflicts: list[dict[str, object]] = []
    selected: dict[str, dict[str, object]] = {}
    for basename, candidates in sorted(by_basename.items()):
        unique_by_hash = {
            str(candidate["sha256"]): candidate for candidate in candidates
        }
        if len(unique_by_hash) > 1:
            conflicts.append(
                {
                    "basename": basename,
                    "candidates": list(unique_by_hash.values()),
                }
            )
            continue
        selected[basename] = next(iter(unique_by_hash.values()))

    if missing_targets or hash_mismatches or conflicts:
        raise RuntimeError(
            json.dumps(
                {
                    "missingTargets": missing_targets,
                    "hashMismatches": hash_mismatches,
                    "basenameConflicts": conflicts,
                },
                indent=2,
            )
        )

    tex_dir = project.parent / "tex"
    tex_dir.mkdir(parents=True, exist_ok=True)
    created: list[dict[str, str]] = []
    retained: list[dict[str, str]] = []
    for basename, candidate in selected.items():
        target = Path(str(candidate["target"]))
        link = tex_dir / basename
        if link.is_symlink():
            current = link.resolve(strict=True)
            if current != target:
                raise RuntimeError(
                    f"Refusing to replace conflicting symlink: {link} -> {current}"
                )
            retained.append({"link": str(link), "target": str(target)})
            continue
        if link.exists():
            if sha256(link) != str(candidate["sha256"]):
                raise RuntimeError(f"Refusing to replace conflicting file: {link}")
            retained.append({"link": str(link), "target": str(link)})
            continue
        link.symlink_to(target)
        created.append({"link": str(link), "target": str(target)})

    mirrored_created: list[dict[str, str]] = []
    mirrored_retained: list[dict[str, str]] = []
    project_directory = project.parent.resolve()
    for mapping in mappings:
        required = str(mapping.get("requiredPath") or "")
        target = Path(str(mapping.get("targetPath") or "")).expanduser().resolve()
        relative_text = required
        while relative_text.startswith("./"):
            relative_text = relative_text[2:]
        # Maxon's URL representation can turn an authored ``./C:/...`` path
        # into ``/C:/...``. Mirror both forms within the project directory;
        # never create an absolute filesystem path.
        relative_text = relative_text.lstrip("/")
        relative = Path(relative_text)
        if not relative_text or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe authored relative path: {required!r}")
        # Keep the lexical package path here. Resolving it would follow a
        # retained symlink to its external target and falsely look like an
        # escape from the project directory on subsequent verification runs.
        link = project_directory / relative
        if project_directory not in link.parents:
            raise RuntimeError(f"Mirrored path escaped project: {required!r}")
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            current = link.resolve(strict=True)
            if current != target:
                raise RuntimeError(
                    f"Refusing to replace conflicting mirrored link: "
                    f"{link} -> {current}"
                )
            mirrored_retained.append(
                {"link": str(link), "target": str(target)}
            )
            continue
        if link.exists():
            if sha256(link) != sha256(target):
                raise RuntimeError(
                    f"Refusing to replace conflicting mirrored file: {link}"
                )
            mirrored_retained.append(
                {"link": str(link), "target": str(link)}
            )
            continue
        link.symlink_to(target)
        mirrored_created.append({"link": str(link), "target": str(target)})

    source_anchor_created: list[dict[str, str]] = []
    source_anchor_retained: list[dict[str, str]] = []
    if source_project is not None:
        if not source_project.is_file():
            raise FileNotFoundError(source_project)
        source_directory = source_project.parent
        source_resources = list((source_directory / "tex").rglob("*"))
        source_resources.extend(
            item
            for item in source_directory.iterdir()
            if item.is_file()
            and item != source_project
            and item.suffix.casefold() not in {".c4d", ".xml"}
        )
        for target in sorted(
            {item.resolve() for item in source_resources if item.is_file()}
        ):
            if (source_directory / "tex") in target.parents:
                relative = target.relative_to(source_directory)
            else:
                relative = Path(target.name)
            link = project_directory / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.is_symlink():
                current = link.resolve(strict=True)
                if current != target and sha256(current) != sha256(target):
                    raise RuntimeError(
                        f"Conflicting original resource link: {link}"
                    )
                source_anchor_retained.append(
                    {"link": str(link), "target": str(current)}
                )
                continue
            if link.exists():
                if sha256(link) != sha256(target):
                    raise RuntimeError(
                        f"Conflicting original resource file: {link}"
                    )
                source_anchor_retained.append(
                    {"link": str(link), "target": str(link)}
                )
                continue
            link.symlink_to(target)
            source_anchor_created.append(
                {"link": str(link), "target": str(target)}
            )

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "project": str(project),
        "texDirectory": str(tex_dir),
        "mappingCount": len(mappings),
        "uniqueBasenameCount": len(selected),
        "missingTargetCount": 0,
        "hashMismatchCount": 0,
        "basenameConflictCount": 0,
        "createdLinkCount": len(created),
        "retainedLinkCount": len(retained),
        "mirroredAuthoredPathCreatedCount": len(mirrored_created),
        "mirroredAuthoredPathRetainedCount": len(mirrored_retained),
        "sourceProject": (
            str(source_project) if source_project is not None else None
        ),
        "sourceAnchorCreatedCount": len(source_anchor_created),
        "sourceAnchorRetainedCount": len(source_anchor_retained),
        "createdLinks": created,
        "retainedLinks": retained,
        "mirroredAuthoredPathCreated": mirrored_created,
        "mirroredAuthoredPathRetained": mirrored_retained,
        "sourceAnchorCreated": source_anchor_created,
        "sourceAnchorRetained": source_anchor_retained,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
