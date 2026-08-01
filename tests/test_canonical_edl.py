import copy
import json
import unittest
from pathlib import Path

from scripts.canonical_edl import (
    DEFAULT_EDL,
    REGISTRY_PATH,
    EdlEvent,
    _assign_registry_ids,
    _chapter_ranges,
    _source_key,
    media_key,
    parse_edl,
)


ROOT = Path(__file__).resolve().parents[1]


class CanonicalEdlIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events, self.audio = parse_edl(DEFAULT_EDL)
        _chapter_ranges(self.events, self.audio)
        self.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        _assign_registry_ids(self.events, copy.deepcopy(self.registry))
        self.state = json.loads(
            (ROOT / "public" / "data" / "state.json").read_text(
                encoding="utf-8"
            )
        )

    def test_published_clean_conform_uses_registered_stable_ids(self) -> None:
        published = [cut["shotId"] for cut in self.state["cuts"]]
        registered = {
            shot["shotId"] for shot in self.registry["shots"]
        }
        self.assertEqual(len(published), 88)
        self.assertEqual(len(set(published)), 88)
        published_picture_ids = {
            cut["shotId"]
            for cut in self.state["cuts"]
            if not cut["isGap"]
        }
        self.assertTrue(published_picture_ids.issubset(registered))
        self.assertEqual(
            sum(1 for cut in self.state["cuts"] if not cut["isGap"]),
            self.registry["pictureShots"],
        )

    def test_insert_and_reorder_do_not_rename_existing_sources(self) -> None:
        original_by_source = {
            event.source_key: event.shot_id for event in self.events
        }
        modified = copy.deepcopy(self.events)
        modified[5], modified[6] = modified[6], modified[5]
        inserted = EdlEvent(
            event_number=999,
            reel="AX",
            track="V",
            source_in=0,
            source_out=48,
            record_in=0,
            record_out=48,
            clip_name="future_insert_v001_0000.tif",
            section_code="ND",
            section_name="Natural Disaster",
        )
        inserted.media_key = media_key(inserted.clip_name)
        inserted.source_key = _source_key(inserted)
        modified.insert(3, inserted)

        _, records = _assign_registry_ids(
            modified,
            copy.deepcopy(self.registry),
        )
        for event in modified:
            if event.source_key in original_by_source:
                self.assertEqual(
                    event.shot_id,
                    original_by_source[event.source_key],
                )
        self.assertIn(inserted.shot_id, records)
        self.assertNotIn(inserted.shot_id, original_by_source.values())

    def test_source_replacement_gets_a_new_identity(self) -> None:
        modified = copy.deepcopy(self.events)
        target = next(
            event for event in modified if event.clip_name.startswith("3m_horse")
        )
        old_id = target.shot_id
        target.clip_name = "3m_horse_replacement_v002_0000.tif"
        target.media_key = media_key(target.clip_name)
        target.source_key = _source_key(target)

        registry, _ = _assign_registry_ids(
            modified,
            copy.deepcopy(self.registry),
        )
        self.assertNotEqual(target.shot_id, old_id)
        old_record = next(
            shot for shot in registry["shots"] if shot["shotId"] == old_id
        )
        self.assertFalse(old_record["active"])

    def test_gaps_inherit_the_preceding_chapter(self) -> None:
        for index, event in enumerate(self.events):
            if not event.is_gap:
                continue
            previous = next(
                item
                for item in reversed(self.events[:index])
                if not item.is_gap
            )
            self.assertEqual(event.section_code, previous.section_code)
            self.assertEqual(event.section_name, previous.section_name)
            self.assertNotEqual(event.section_code, "GAP")


if __name__ == "__main__":
    unittest.main()
