import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_c4d_material_relink_manifest import (
    maxon_asset_cache_candidates,
    maxon_asset_id,
)
from scripts.c4d_relink_safety import (
    basename_only_semantics_match,
    safe_manifest_mappings,
    unsafe_relink_target_reason,
)


class C4DRelinkSafetyTests(unittest.TestCase):
    def test_maxon_asset_id_requires_exact_hashed_basename(self):
        self.assertEqual(
            maxon_asset_id(
                "asset:///file_a3c38ea46f18421c~.jpg"
            ),
            ("a3c38ea46f18421c", ".jpg"),
        )
        self.assertIsNone(maxon_asset_id("HairHead_Point.abc"))

    def test_maxon_asset_cache_resolution_is_id_and_extension_exact(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matching = (
                root
                / "MaxonAssets.db_test"
                / "file_a3c38ea46f18421c"
                / "1"
                / "asset.jpg"
            )
            matching.parent.mkdir(parents=True)
            matching.write_bytes(b"jpeg-payload")
            wrong_extension = matching.with_suffix(".png")
            wrong_extension.write_bytes(b"png-payload")
            other = (
                root
                / "MaxonAssets.db_test"
                / "file_bbbbbbbbbbbbbbbb"
                / "1"
                / "asset.jpg"
            )
            other.parent.mkdir(parents=True)
            other.write_bytes(b"other")
            self.assertEqual(
                maxon_asset_cache_candidates(
                    "asset:///file_a3c38ea46f18421c~.jpg",
                    [root],
                ),
                [matching],
            )

    def test_rejected_unproven_target_is_never_usable(self):
        target = (
            "/Absolutely/AS/0 Finishing/02 Projects/06 IJDKYY/"
            "_codex_072526/rejected_unproven_assets/"
            "Subdivision_Surface.2.abc"
        )
        self.assertEqual(
            unsafe_relink_target_reason(target),
            "rejected_unproven_target",
        )

    def test_quarantine_target_is_never_usable(self):
        self.assertEqual(
            unsafe_relink_target_reason(
                "/Absolutely/SG/C4D/_quarantine/hair.abc"
            ),
            "quarantined_target",
        )

    def test_manifest_filter_returns_only_safe_targets(self):
        manifest = {
            "mappings": [
                {
                    "requiredPath": "source/hair.abc",
                    "targetPath": "/package/tex/hair.abc",
                },
                {
                    "requiredPath": "source/rejected.abc",
                    "targetPath": (
                        "/package/rejected_unproven_assets/hair.abc"
                    ),
                },
            ]
        }
        mappings, violations = safe_manifest_mappings(manifest)
        self.assertEqual(
            mappings,
            {"source/hair.abc": "/package/tex/hair.abc"},
        )
        self.assertEqual(len(violations), 1)

    def test_basename_only_cache_cannot_cross_shot_folders(self):
        required = (
            "./Mainframe/ASSETS/MOCAP/ABSOLUTELY/Greece/FloatSpin/"
            "alembic/Subdivision_Surface.abc"
        )
        wrong_shot = (
            "/Absolutely/Paracosm_Mainframe_Recovery_20260730/ASSETS/"
            "MOCAP/ABSOLUTELY/Greece/TH_UNTIL ripping wallpaper v4/"
            "alembic/Subdivision_Surface.abc"
        )
        exact_recovery = (
            "/Absolutely/Paracosm_Mainframe_Recovery_20260730/ASSETS/"
            "MOCAP/ABSOLUTELY/Greece/FloatSpin/alembic/"
            "Subdivision_Surface.abc"
        )
        self.assertFalse(
            basename_only_semantics_match(required, wrong_shot)
        )
        self.assertTrue(
            basename_only_semantics_match(required, exact_recovery)
        )

    def test_basename_only_manifest_rejects_cross_shot_cache(self):
        manifest = {
            "mappings": [
                {
                    "requiredPath": (
                        "./Mainframe/ASSETS/MOCAP/ABSOLUTELY/Greece/"
                        "FloatSpin/alembic/Subdivision_Surface.abc"
                    ),
                    "targetPath": (
                        "/Absolutely/ASSETS/MOCAP/ABSOLUTELY/Greece/"
                        "TH/alembic/Subdivision_Surface.abc"
                    ),
                    "selectionBasis": "exact_basename_only",
                }
            ]
        }
        mappings, violations = safe_manifest_mappings(manifest)
        self.assertEqual(mappings, {})
        self.assertEqual(
            violations[0]["reason"],
            "basename_only_path_semantics_mismatch",
        )

    def test_preferred_folder_cannot_override_cache_shot_identity(self):
        manifest = {
            "mappings": [
                {
                    "requiredPath": (
                        "./Mainframe/ASSETS/MOCAP/ABSOLUTELY/Greece/"
                        "Teacup/alembic/Subdivision_Surface.abc"
                    ),
                    "targetPath": (
                        "/Absolutely/Paracosm_Mainframe_Recovery_20260730/"
                        "ASSETS/MOCAP/ABSOLUTELY/Greece/TH/alembic/"
                        "Subdivision_Surface.abc"
                    ),
                    "selectionBasis": "preferred_collected_texture_folder",
                }
            ]
        }
        mappings, violations = safe_manifest_mappings(manifest)
        self.assertEqual(mappings, {})
        self.assertEqual(
            violations[0]["reason"],
            "basename_only_path_semantics_mismatch",
        )

    def test_basename_only_mainframe_texture_keeps_full_authored_tail(self):
        required = (
            "./Mainframe/ASSETS/TEXTURES/3D/BRIDGE/Downloaded/surface/"
            "surface_misc_ugclegrn/ugclegrn_4K_AO.png"
        )
        target = (
            "/Absolutely/Paracosm_Mainframe_Recovery_20260730/ASSETS/"
            "TEXTURES/3D/BRIDGE/Downloaded/surface/"
            "surface_misc_ugclegrn/ugclegrn_4K_AO.png"
        )
        self.assertTrue(basename_only_semantics_match(required, target))


if __name__ == "__main__":
    unittest.main()
