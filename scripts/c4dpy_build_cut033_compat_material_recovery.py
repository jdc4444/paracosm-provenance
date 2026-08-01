"""Add current-renderer-compatible character materials to the dated CUT 33 copy.

The original project is never opened by this script. The target must already
be a Codex-dated recovery. Historical Redshift node graphs are retained for
forensics; only texture-tag assignments in the recovered character hierarchy
are redirected to new Cinema 4D standard materials, which current Redshift can
translate reliably.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


ROOT = "walks in snow while shivering in wind v2"


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def make_material(doc, name: str, color, texture: Path | None = None):
    material = c4d.BaseMaterial(c4d.Mmaterial)
    material.SetName(name)
    material[c4d.MATERIAL_USE_COLOR] = True
    material[c4d.MATERIAL_COLOR_COLOR] = color
    if texture is not None:
        if not texture.is_file():
            raise FileNotFoundError(texture)
        shader = c4d.BaseShader(c4d.Xbitmap)
        shader[c4d.BITMAPSHADER_FILENAME] = str(texture)
        material.InsertShader(shader)
        material[c4d.MATERIAL_COLOR_SHADER] = shader
    doc.InsertMaterial(material)
    material.Message(c4d.MSG_UPDATE)
    return material


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    if "_codex_" not in project.name.casefold() or not any(
        "_codex_" in parent.name.casefold() for parent in project.parents
    ):
        raise RuntimeError("Refusing to edit a non-Codex-dated project")

    texture_root = Path(
        "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
        "/JD/09 3D/03 Finishing/01 c4d/03TH/tex"
    )
    character_texture_root = Path(
        "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
        "/SG/CHARACTER_MODEL/tex"
    )
    texture_paths = {
        "skinBody": texture_root / "abby_skin_basecolor.1001.png",
        "skinFace": Path(
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
            "/SG/C4D/tex/"
            "abby_merged_for_painting_Abby_skin_texture_BaseColor.1002.png"
        ),
        "outfit": character_texture_root
        / "Outfit-colours_diffuse_1001.png",
        "shoe": texture_root / "abby_shoe_full_lp_full_BaseColor.png",
        "eye": texture_root / "Abby_eye.png",
    }
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report = {
        "project": str(project),
        "root": ROOT,
        "texturePaths": {key: str(value) for key, value in texture_paths.items()},
        "assignments": [],
        "saved": False,
    }
    try:
        materials = {
            "skinBody": make_material(
                doc,
                "PARACOSM CODEX SKIN BODY 072526",
                c4d.Vector(0.36, 0.18, 0.12),
                texture_paths["skinBody"],
            ),
            "skinFace": make_material(
                doc,
                "PARACOSM CODEX SKIN FACE 072526",
                c4d.Vector(0.36, 0.18, 0.12),
                texture_paths["skinFace"],
            ),
            "outfit": make_material(
                doc,
                "PARACOSM CODEX PATCHWORK OUTFIT 072526",
                c4d.Vector(0.5, 0.06, 0.08),
                texture_paths["outfit"],
            ),
            "shoe": make_material(
                doc,
                "PARACOSM CODEX SHOES 072526",
                c4d.Vector(0.13, 0.06, 0.04),
                texture_paths["shoe"],
            ),
            "eye": make_material(
                doc,
                "PARACOSM CODEX EYES 072526",
                c4d.Vector(0.04, 0.03, 0.02),
                texture_paths["eye"],
            ),
            "hair": make_material(
                doc,
                "PARACOSM CODEX COPPER HAIR 072526",
                c4d.Vector(0.18, 0.045, 0.025),
            ),
            "teeth": make_material(
                doc,
                "PARACOSM CODEX TEETH 072526",
                c4d.Vector(0.72, 0.68, 0.59),
            ),
            "eyelash": make_material(
                doc,
                "PARACOSM CODEX EYELASH 072526",
                c4d.Vector(0.015, 0.01, 0.008),
            ),
        }
        for op in walk_objects(doc.GetFirstObject()):
            path = object_path(op)
            if path != ROOT and not path.startswith(ROOT + "/"):
                continue
            tag = op.GetFirstTag()
            while tag:
                if not tag.CheckType(c4d.Ttexture):
                    tag = tag.GetNext()
                    continue
                restriction = str(tag[c4d.TEXTURETAG_RESTRICTION] or "")
                old_material = tag.GetMaterial()
                old_name = old_material.GetName() if old_material else None
                replacement = None
                reason = None
                if "HAIR_codex_recovery_072526" in path:
                    replacement = materials["hair"]
                    reason = "recovered hair geometry"
                elif op.GetName() == "cloth_parent":
                    replacement = materials["outfit"]
                    reason = "exact wardrobe cache"
                elif op.GetName() == "Shoes":
                    replacement = materials["shoe"]
                    reason = "character shoes"
                elif op.GetName() == "SKM_AbbyV2Character_BodyMesh":
                    replacement = materials["skinBody"]
                    reason = "body skin"
                elif op.GetName() == "SKM_NewMetaHumanCharacter_FaceMesh":
                    folded = restriction.casefold()
                    if "teeth" in folded:
                        replacement = materials["teeth"]
                        reason = "teeth"
                    elif "eye" in folded and "lash" not in folded:
                        replacement = materials["eye"]
                        reason = "eye"
                    elif "lash" in folded or "hide" in folded:
                        replacement = materials["eyelash"]
                        reason = "eyelash or hidden face shell"
                    else:
                        replacement = materials["skinFace"]
                        reason = "face skin"
                if replacement is not None:
                    tag.SetMaterial(replacement)
                    tag.Message(c4d.MSG_UPDATE)
                    report["assignments"].append(
                        {
                            "objectPath": path,
                            "restriction": restriction,
                            "oldMaterial": old_name,
                            "newMaterial": replacement.GetName(),
                            "reason": reason,
                        }
                    )
                tag = tag.GetNext()
        c4d.EventAdd()
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        saved = c4d.documents.SaveDocument(
            doc,
            str(project),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report["saved"] = bool(saved)
        if not saved:
            report["error"] = "Cinema 4D SaveDocument returned false"
        print(
            "PARACOSM_CUT033_COMPAT_MATERIAL_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_CUT033_COMPAT_MATERIAL_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
