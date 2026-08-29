from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "search.py"
SPEC = importlib.util.spec_from_file_location("search", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SearchTests(unittest.TestCase):
    def test_long_context_is_split_on_sections(self):
        body = "简介\n\n## 第一节\n\n内容甲\n\n## 第二节\n\n内容乙"
        chunks = MODULE.chunk_markdown(body, "context")
        self.assertEqual([section for section, _ in chunks], ["", "第一节", "第二节"])

    def test_context_filter_includes_book_framework(self):
        doc = MODULE.Document(
            id="book#chunk-1",
            source_id="book",
            title="书",
            section="框架",
            source_type="book-framework",
            source_url="",
            published_at="",
            text="内容",
            path="context/book.md",
        )
        self.assertTrue(MODULE.type_matches(doc, "context"))


if __name__ == "__main__":
    unittest.main()
