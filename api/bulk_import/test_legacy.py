"""Legacy conversion fixture tests: isolated SQLite, no model and no DB writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.bulk_import.cli import retry_item
from api.bulk_import.legacy import _split_attempt, _text, _type, audit, normalize
from api.bulk_import.storage import read_items


class LegacyTests(unittest.TestCase):
    def setUp(self):
        test_data = Path(__file__).resolve().parents[2] / "data"
        test_data.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_data, ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.db = self.root / "platform.db"
        self.pdf = self.root / "pdf-imports" / "fixture.pdf"
        self.pdf.parent.mkdir()
        self.pdf.write_bytes(b"%PDF-1.4\nfixture only\n")
        self.sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        con = sqlite3.connect(self.db)
        try:
            con.executescript("""
                CREATE TABLE targets(id TEXT PRIMARY KEY,school TEXT,exam_label TEXT);
                CREATE TABLE topics(id TEXT PRIMARY KEY,name TEXT);
                CREATE TABLE topic_target_tags(topic_id TEXT,target_id TEXT);
                CREATE TABLE pdf_imports(id TEXT PRIMARY KEY,target_id TEXT,original_name TEXT,
                    stored_name TEXT,sha256 TEXT,page_count INTEGER);
                CREATE TABLE pdf_question_candidates(id TEXT PRIMARY KEY,import_id TEXT,target_id TEXT,
                    exam_year INTEGER,sequence INTEGER,question_number TEXT,stem TEXT,answer TEXT,
                    analysis TEXT,topic_id TEXT,question_type TEXT,difficulty INTEGER,
                    stem_segments_json TEXT,answer_segments_json TEXT);
                INSERT INTO targets VALUES ('ruc','中国人民大学','834 经济学');
                INSERT INTO topics VALUES ('micro','需求弹性');
                INSERT INTO topic_target_tags VALUES ('micro','ruc');
            """)
            con.execute("INSERT INTO pdf_imports VALUES (?,?,?,?,?,?)",
                        ("fixture", "ruc", "fixture.pdf", "fixture.pdf", self.sha, 3))
            rows = [
                ("one", "1.简述需求弹性的含义。", "来源参考答案", "来源参考答案", "micro", "选择 / 填空"),
                ("two", "2.关于某知识点的相关考题。", "", "", None, "未知题型"),
                ("three", "3.第一题\n二、计算题\n求均衡数量。", "", "", None, "计算题"),
            ]
            for sequence, (key, stem, answer, analysis, topic, kind) in enumerate(rows, 1):
                con.execute("INSERT INTO pdf_question_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (key, "fixture", "ruc", 2020, sequence, str(sequence), stem,
                             answer, analysis, topic, kind, 3,
                             json.dumps([{"page": 1, "top": 100, "bottom": 200}]), "[]"))
            con.commit()
        finally:
            con.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_audit_normalize_and_source_db_unchanged(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        summary = audit(self.db, "ruc", "fixture", [2020])
        self.assertEqual(summary["total"], 3)
        out = self.root / "batch"
        result = normalize(self.db, out, "ruc", "fixture", [2020])
        self.assertEqual(result["total"], 3)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        items = read_items(out)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["content"]["stem_latex"], "简述需求弹性的含义。")
        self.assertEqual(items[0]["classification"],
                         {"topic_id": "micro", "question_type": "选择/填空", "difficulty": None})
        self.assertEqual(items[0]["source_answer"]["kind"], "REFERENCE")
        self.assertEqual(items[0]["ai_answer"]["status"], "PENDING")
        self.assertEqual(items[1]["processing_meta"]["legacy_status"], "MANUAL_REVIEW")
        self.assertEqual(items[2]["processing_meta"]["legacy_status"], "NEED_SPLIT")
        self.assertEqual(result["split_attempts"][0]["result"], "NEED_AI_SPLIT")
        self.assertEqual(len((out / "pilot.jsonl").read_text(encoding="utf-8")), 0)
        with self.assertRaisesRegex(ValueError, "禁止直接调用模型"):
            retry_item(out, items[1]["item_key"], object())

    def test_rules_are_conservative(self):
        text, parts, _ = _text("12.第一段  内容\n\n（1）求解\n（2）解释")
        self.assertTrue(text.startswith("第一段 内容"))
        self.assertEqual([x["label"] for x in parts], ["1", "2"])
        self.assertIsNone(_type("图形分析题"))
        self.assertEqual(_split_attempt({"stem": "1.题目\n二、计算题\n求解", "answer": ""})["result"],
                         "NEED_AI_SPLIT")


if __name__ == "__main__":
    unittest.main()
