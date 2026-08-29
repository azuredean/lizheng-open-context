from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_public_corpus.py"
SPEC = importlib.util.spec_from_file_location("export_public_corpus", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ExportTests(unittest.TestCase):
    def test_html_conversion_keeps_structure_and_drops_unlabelled_image(self):
        source = '<h2>标题</h2><p>一段<strong>重要</strong>文字。</p><img src="secret.jpg"><ul><li>甲</li></ul>'
        result = MODULE.html_to_markdown(source)
        self.assertIn("## 标题", result)
        self.assertIn("**重要**", result)
        self.assertIn("- 甲", result)
        self.assertNotIn("secret.jpg", result)

    def test_timed_transcript_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.srt"
            path.write_text(
                "1\n00:00:03,000 --> 00:00:05,000\n你好 <b>世界</b>\n\n"
                "2\n00:00:08,000 --> 00:00:09,000\n下一句\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.parse_timed_transcript(path), [(3, "你好 世界"), (8, "下一句")])

    def test_video_filter_is_fail_closed(self):
        valid = {
            "youtube_privacy": "public",
            "content_class": "normal_video",
            "podcast_policy": "ready_public_normal",
            "local_status": "ok",
        }
        self.assertTrue(MODULE.eligible_video(valid))
        for key, invalid in (
            ("youtube_privacy", "private"),
            ("content_class", "member_only"),
            ("podcast_policy", "not_public"),
            ("local_status", "invalid"),
        ):
            candidate = dict(valid)
            candidate[key] = invalid
            self.assertFalse(MODULE.eligible_video(candidate))

    def test_video_transcript_requires_positive_allowlist(self):
        unreviewed = MODULE.classify_video_rights("abcdefghijk", "单人口播", set(), {}, set())
        self.assertEqual(unreviewed["rights_scope"], "metadata-only")
        approved = MODULE.classify_video_rights(
            "abcdefghijk", "单人口播", set(), {}, {"abcdefghijk"}
        )
        self.assertEqual(approved["speaker_classification"], "solo-yuzheng")
        self.assertEqual(approved["review_status"], "approved")

    def test_positive_allowlist_conflict_fails_closed(self):
        with self.assertRaises(ValueError):
            MODULE.classify_video_rights(
                "abcdefghijk",
                "嘉宾访谈",
                set(),
                {},
                {"abcdefghijk"},
            )


if __name__ == "__main__":
    unittest.main()
