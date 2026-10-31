"""No paid calls, no user database: isolated regression tests for the import gate."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.bulk_import.cli import confirm_item, import_batch, validate_batch
from api.bulk_import.contract import validate_item
from api.bulk_import.pdf import normalize_formula, split_questions
from api.bulk_import.storage import atomic_json, read_json, write_items


def sample_item() -> dict:
    return {
        "schema_version": "0.1", "item_key": "test-p1-q1",
        "source": {"kind": "CURATED_EXERCISE", "name": "测试材料", "url": None,
                   "file_name": "test.pdf", "file_sha256": "a" * 64, "pages": [1],
                   "exam_year": None, "is_demo": False},
        "exam_scope": {"target_id": "target"},
        "content": {"stem_raw": "测试经济学题干，请解释需求弹性。",
                    "stem_latex": "测试经济学题干，请解释需求弹性。", "subquestions": [],
                    "latex_fragments": [], "assets": []},
        "source_answer": {"status": "ABSENT", "kind": "NONE", "text": "", "analysis": "",
                          "human_verified": False, "evidence": []},
        "ai_answer": {"status": "SUCCEEDED", "answer": "测试 AI 答案", "analysis": "测试 AI 解析",
                      "provider": "fixture"},
        "classification": {"topic_id": "topic", "question_type": "简答题", "difficulty": 2},
        "validation": {"errors": [], "warnings": [], "duplicate_candidates": []},
        "processing_meta": {"pipeline_version": "0.1", "method": "fixture", "question_number": "1",
                            "regions": [], "model_runs": [{"task": "answer_generation", "provider": "fixture",
                                                         "model": "test-double", "duration_ms": 0}]},
    }


class LocalImportTests(unittest.TestCase):
    def setUp(self):
        test_data = Path(__file__).resolve().parents[2] / "data"
        test_data.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_data, ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.batch = self.root / "batch"
        self.batch.mkdir()
        (self.batch / "assets").mkdir()
        self.db = self.root / "platform.db"
        con = sqlite3.connect(self.db)
        try:
            con.executescript("""
                CREATE TABLE targets(id TEXT PRIMARY KEY);
                CREATE TABLE topics(id TEXT PRIMARY KEY);
                CREATE TABLE topic_target_tags(topic_id TEXT,target_id TEXT);
                CREATE TABLE change_versions(scope TEXT PRIMARY KEY,version INTEGER);
                CREATE TABLE questions(
                    id TEXT PRIMARY KEY,catalog_number TEXT,target_id TEXT,topic_id TEXT,
                    source_type TEXT,source_name TEXT,source_url TEXT,source_verified INTEGER,
                    exam_year INTEGER,question_type TEXT,difficulty INTEGER,stem TEXT,
                    answer TEXT NOT NULL,analysis TEXT NOT NULL,review_status TEXT,updated_at TEXT);
                INSERT INTO targets VALUES ('target');
                INSERT INTO topics VALUES ('topic');
                INSERT INTO topic_target_tags VALUES ('topic','target');
                INSERT INTO change_versions VALUES ('content',0);
                INSERT INTO questions(id,catalog_number,target_id,topic_id,source_type,source_name,
                    source_url,source_verified,exam_year,question_type,difficulty,stem,answer,analysis,review_status)
                    VALUES ('legacy','Q-000001','target','topic','CURATED_EXERCISE','旧题','',0,NULL,
                    '简答题',2,'历史题目','历史答案','历史解析','APPROVED');
            """)
            con.commit()
        finally:
            con.close()
        self.item = sample_item()
        source_bytes = b"%PDF-1.4\n% test-only fixture\n"
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        self.item["source"]["file_sha256"] = source_sha
        (self.batch / "assets" / f"source-{source_sha}.pdf").write_bytes(source_bytes)
        atomic_json(self.batch / "manifest.json", {"schema_version": "0.1", "source_file": "test.pdf",
                                                   "source_sha256": source_sha,
                                                   "source_asset": f"assets/source-{source_sha}.pdf"})
        write_items(self.batch, [self.item])
        atomic_json(self.batch / "progress.json", {"schema_version": "0.1", "items": {
            self.item["item_key"]: {"status": "PENDING", "attempts": 0}}})

    def tearDown(self):
        self.temp.cleanup()

    def test_no_source_answer_is_separate_from_ai_and_import_is_idempotent(self):
        self.assertEqual(validate_batch(self.batch, self.db), (1, 0))
        confirm_item(self.batch, self.item["item_key"], "CONFIRM " + self.item["item_key"])
        self.assertEqual(import_batch(self.batch, self.db), (1, 0))
        self.assertEqual(import_batch(self.batch, self.db), (0, 0))
        con = sqlite3.connect(self.db)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM questions ORDER BY catalog_number").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["answer"], "历史答案")
            self.assertEqual(rows[0]["source_answer_kind"], "UNKNOWN")
            imported = rows[1]
            self.assertEqual(imported["review_status"], "DRAFT")
            self.assertEqual(imported["answer"], "")
            self.assertEqual(imported["source_answer_kind"], "NONE")
            self.assertEqual(json.loads(imported["ai_answer_json"])["answer"], "测试 AI 答案")
            self.assertEqual(json.loads(imported["import_meta_json"])["pages"], [1])
        finally:
            con.close()

    def test_modification_revokes_confirmation(self):
        validate_batch(self.batch, self.db)
        confirm_item(self.batch, self.item["item_key"], "CONFIRM " + self.item["item_key"])
        edited = sample_item()
        edited["content"]["stem_latex"] += " 修改"
        write_items(self.batch, [edited])
        self.assertEqual(import_batch(self.batch, self.db), (0, 1))
        self.assertEqual(read_json(self.batch / "progress.json")["items"][edited["item_key"]]["status"], "ERROR")
        validate_batch(self.batch, self.db)
        self.assertNotIn("confirmed_digest", read_json(self.batch / "progress.json")["items"][edited["item_key"]])

    def test_official_requires_evidence_and_human_verification(self):
        self.item["source_answer"].update({"status": "PRESENT", "kind": "OFFICIAL", "text": "答案"})
        errors, _ = validate_item(self.item, self.batch)
        self.assertTrue(any("官方答案" in error for error in errors))
        self.item["source_answer"].update({"human_verified": True, "evidence": [{
            "file_sha256": self.item["source"]["file_sha256"], "page": 1,
            "note": "人工核对：原 PDF 第 1 页明确标为官方答案"}]})
        errors, _ = validate_item(self.item, self.batch)
        self.assertFalse(any("官方答案" in error for error in errors))

    def test_missing_manifest_or_bad_hash_blocks_import(self):
        (self.batch / "manifest.json").unlink()
        errors, _ = validate_item(self.item, self.batch)
        self.assertTrue(any("manifest" in error for error in errors))
        self.item["source"]["file_sha256"] = "../unsafe"
        errors, _ = validate_item(self.item, self.batch)
        self.assertTrue(any("SHA-256" in error for error in errors))

    def test_ai_status_without_call_record_is_blocked(self):
        self.item["processing_meta"]["model_runs"] = []
        errors, _ = validate_item(self.item, self.batch)
        self.assertTrue(any("调用记录" in error for error in errors))

    def test_mock_answer_cannot_enter_formal_bank(self):
        self.item["ai_answer"]["status"] = "MOCK"
        errors, _ = validate_item(self.item, self.batch)
        self.assertTrue(any("真实 AI 答案" in error for error in errors))

    def test_duplicate_is_warning_not_blocker(self):
        self.item["content"]["stem_latex"] = "历史题目"
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            errors, warnings = validate_item(self.item, self.batch, con)
        finally:
            con.close()
        self.assertFalse(any("重复" in error for error in errors))
        self.assertTrue(any("疑似重复题" in warning for warning in warnings))


class PdfRulesTests(unittest.TestCase):
    def test_cross_page_subquestions_answer_mapping_and_order(self):
        pages = [
            {"page": 1, "height": 800, "assets": [], "scanned": False,
             "lines": [{"text": "1. 求消费者最优选择", "top": 100, "bottom": 110},
                       {"text": "(1) 写出预算约束", "top": 130, "bottom": 140}]},
            {"page": 2, "height": 800, "assets": [], "scanned": False,
             "lines": [{"text": "(2) 求最优值", "top": 70, "bottom": 80},
                       {"text": "2. 简述需求弹性", "top": 200, "bottom": 210},
                       {"text": "参考答案", "top": 500, "bottom": 510},
                       {"text": "1. x=30", "top": 530, "bottom": 540}]},
        ]
        questions, answers = split_questions(pages)
        self.assertEqual(len(questions), 2)
        self.assertEqual([part["label"] for part in questions[0]["subquestions"]], ["1", "2"])
        self.assertEqual([region["page"] for region in questions[0]["regions"]], [1, 2])
        self.assertEqual(questions[0]["regions"][1]["bottom"], 200)
        self.assertEqual(answers["1"]["lines"], ["x=30"])

    def test_formula_conversion_is_conservative(self):
        normalized, fragments = normalize_formula("x² ≤ 4，√x ≥ 0")
        self.assertIn("x^{2}", normalized)
        self.assertIn(r"\leq", normalized)
        self.assertTrue(fragments)


if __name__ == "__main__":
    unittest.main()
