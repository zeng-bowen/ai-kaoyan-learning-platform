"""Legacy conversion fixture tests: isolated SQLite, no model and no DB writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.bulk_import.cli import retry_item
from api.bulk_import.ai import ModelError
from api.bulk_import.legacy import _split_attempt, _text, _type, audit, normalize
from api.bulk_import.enrich import (_answer_comparison, _create_output, _load_source,
                                    plan, review_pack, review_sample, run, summarize)
from api.bulk_import.storage import atomic_json, read_items, write_items


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
                CREATE TABLE questions(id TEXT PRIMARY KEY);
                CREATE TABLE topics(id TEXT PRIMARY KEY,name TEXT,subject TEXT,module TEXT);
                CREATE TABLE topic_target_tags(topic_id TEXT,target_id TEXT);
                CREATE TABLE pdf_imports(id TEXT PRIMARY KEY,target_id TEXT,original_name TEXT,
                    stored_name TEXT,sha256 TEXT,page_count INTEGER);
                CREATE TABLE pdf_question_candidates(id TEXT PRIMARY KEY,import_id TEXT,target_id TEXT,
                    exam_year INTEGER,sequence INTEGER,question_number TEXT,stem TEXT,answer TEXT,
                    analysis TEXT,topic_id TEXT,question_type TEXT,difficulty INTEGER,
                    stem_segments_json TEXT,answer_segments_json TEXT);
                INSERT INTO targets VALUES ('ruc','中国人民大学','834 经济学');
                INSERT INTO topics VALUES ('micro','需求弹性','微观经济学','消费者理论');
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

    def test_text_enrichment_is_resumable_and_never_writes_source_db(self):
        source = self.root / "batch"
        normalize(self.db, source, "ruc", "fixture", [2020])
        before_db = hashlib.sha256(self.db.read_bytes()).hexdigest()
        before_jsonl = hashlib.sha256((source / "questions.jsonl").read_bytes()).hexdigest()
        out = self.root / "enriched"
        self.assertEqual(plan(source, out, self.db)["eligible"], 1)
        self.assertEqual(plan(source, out, self.db)["answer_calls_pending"], 1)
        self.assertEqual(plan(source, out, self.db)["tag_calls_pending"], 1)

        class FakeTasks:
            provider_id = "deepseek"
            model = "deepseek-flash"

            def __init__(self):
                self.runs = []

            def answer(self, stem):
                self.runs.append({"task": "answer_generation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 10, "attempts": 1, "input_tokens": 10, "output_tokens": 20,
                                  "estimated_cost": None, "currency": None, "error": None})
                return {"answer": "需求弹性是相对变动之比", "analysis": "按定义计算"}

            def recommend(self, stem, topics):
                self.runs.append({"task": "tag_recommendation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 5, "attempts": 1, "input_tokens": 20, "output_tokens": 10,
                                  "estimated_cost": None, "currency": None, "error": None})
                return {"topic_id": "micro", "question_type": "简答题", "difficulty": 2}

        first = FakeTasks()
        with patch("api.bulk_import.enrich.make_tasks", return_value=first):
            summary = run(source, out, self.db, allow_model_call=True)
        self.assertEqual((summary["eligible"], summary["answer_success"], summary["tag_success"]), (1, 1, 1))
        self.assertEqual(len(first.runs), 2)
        enriched = read_items(out)[0]
        self.assertEqual(enriched["source_answer"]["text"], "来源参考答案")
        self.assertEqual(enriched["ai_answer"]["provider"], "deepseek")
        self.assertEqual(enriched["classification"]["difficulty"], 2)
        self.assertEqual(plan(source, out, self.db)["answer_calls_pending"], 0)
        second = FakeTasks()
        with patch("api.bulk_import.enrich.make_tasks", return_value=second):
            run(source, out, self.db, allow_model_call=True)
        self.assertEqual(len(second.runs), 0)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before_db)
        self.assertEqual(hashlib.sha256((source / "questions.jsonl").read_bytes()).hexdigest(), before_jsonl)
        self.assertEqual(len(review_sample(out)), 1)
        duplicate = json.loads(json.dumps(enriched))
        duplicate["item_key"] = "legacy-fixture-duplicate"
        atomic_json(out / "items" / (duplicate["item_key"] + ".json"), duplicate)
        write_items(out, [enriched, duplicate])
        duplicate_summary = summarize(out)
        self.assertEqual((duplicate_summary["duplicate_groups"], duplicate_summary["duplicate_members"]), (1, 2))
        self.assertTrue(all(item["validation"]["duplicate_candidates"] for item in read_items(out)))

    def test_conflict_is_warning_candidate_not_automatic_truth(self):
        item = {"source_answer": {"text": "最终 X=18，Y=10"},
                "ai_answer": {"answer": "由约束求得 X=24，Y=13"}}
        self.assertEqual(_answer_comparison(item), "POTENTIAL_CONFLICT")
        item["ai_answer"]["answer"] = "由约束求得 X=18，Y=10"
        self.assertEqual(_answer_comparison(item), "NUMERIC_AGREEMENT")
        item["ai_answer"]["answer"] = "最优需求为 X*=24，Y*=13"
        self.assertEqual(_answer_comparison(item), "POTENTIAL_CONFLICT")

    def test_invalid_json_is_retried_once_and_checkpointed(self):
        source = self.root / "batch"
        normalize(self.db, source, "ruc", "fixture", [2020])
        out = self.root / "enriched"

        class RetryTasks:
            provider_id = "deepseek"
            model = "deepseek-flash"

            def __init__(self):
                self.runs = []

            def answer(self, stem):
                error = "INVALID_STRUCTURED_RESPONSE" if not self.runs else None
                self.runs.append({"task": "answer_generation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 4, "attempts": 1, "input_tokens": 10, "output_tokens": 5,
                                  "estimated_cost": None, "currency": None, "error": error})
                if error:
                    raise ModelError("answer_generation failed: " + error)
                return {"answer": "合格答案", "analysis": "合格解析"}

            def recommend(self, stem, topics):
                self.runs.append({"task": "tag_recommendation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 3, "attempts": 1, "input_tokens": 15, "output_tokens": 4,
                                  "estimated_cost": None, "currency": None, "error": None})
                return {"topic_id": None, "question_type": None, "difficulty": None}

        tasks = RetryTasks()
        with patch("api.bulk_import.enrich.make_tasks", return_value=tasks):
            summary = run(source, out, self.db, allow_model_call=True)
        self.assertEqual(summary["answer_json_retries"], 1)
        self.assertEqual(summary["tag_success"], 1)
        self.assertEqual(summary["topic_null"], 1)
        self.assertEqual(len(tasks.runs), 3)
        self.assertEqual(read_items(out)[0]["ai_answer"]["status"], "SUCCEEDED")

    def test_auth_failure_stops_without_tag_call(self):
        source = self.root / "batch"
        normalize(self.db, source, "ruc", "fixture", [2020])
        out = self.root / "enriched"

        class AuthTasks:
            provider_id = "deepseek"
            model = "deepseek-flash"

            def __init__(self):
                self.runs = []

            def answer(self, stem):
                self.runs.append({"task": "answer_generation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 1, "attempts": 1, "input_tokens": None,
                                  "output_tokens": None, "estimated_cost": None, "currency": None,
                                  "error": "HTTP_401"})
                raise ModelError("answer_generation failed: HTTP_401")

            def recommend(self, stem, topics):
                self.fail("tag must not be called")

        tasks = AuthTasks()
        with patch("api.bulk_import.enrich.make_tasks", return_value=tasks):
            with self.assertRaisesRegex(ModelError, "401/403"):
                run(source, out, self.db, allow_model_call=True)
        self.assertEqual(len(tasks.runs), 1)
        self.assertEqual(read_items(out)[0]["ai_answer"]["status"], "PENDING")

    def test_truncated_answer_is_not_blindly_retried_on_resume(self):
        source = self.root / "batch"
        normalize(self.db, source, "ruc", "fixture", [2020])
        out = self.root / "enriched"

        class TruncatedTasks:
            provider_id = "deepseek"
            model = "deepseek-flash"

            def __init__(self):
                self.runs = []

            def answer(self, stem):
                self.runs.append({"task": "answer_generation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 5, "attempts": 1, "input_tokens": 20,
                                  "output_tokens": 4000, "estimated_cost": None, "currency": None,
                                  "error": "OUTPUT_TRUNCATED"})
                raise ModelError("answer_generation failed: OUTPUT_TRUNCATED")

            def recommend(self, stem, topics):
                self.runs.append({"task": "tag_recommendation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 2, "attempts": 1, "input_tokens": 20,
                                  "output_tokens": 10, "estimated_cost": None, "currency": None, "error": None})
                return {"topic_id": "micro", "question_type": "简答题", "difficulty": 2}

        first = TruncatedTasks()
        with patch("api.bulk_import.enrich.make_tasks", return_value=first):
            summary = run(source, out, self.db, allow_model_call=True)
        self.assertEqual((summary["answer_failed"], summary["tag_success"]), (1, 1))
        self.assertEqual(len(first.runs), 2)
        self.assertEqual(plan(source, out, self.db)["answer_calls_pending"], 0)
        second = TruncatedTasks()
        with patch("api.bulk_import.enrich.make_tasks", return_value=second):
            run(source, out, self.db, allow_model_call=True)
        self.assertEqual(len(second.runs), 0)
        self.assertEqual(plan(source, out, self.db, retry_failed=True)["answer_calls_pending"], 1)
        self.assertEqual(plan(source, out, self.db, retry_failed=True,
                              retry_errors={"INVALID_STRUCTURED_RESPONSE"})["answer_calls_pending"], 0)
        self.assertEqual(plan(source, out, self.db, retry_failed=True,
                              retry_errors={"OUTPUT_TRUNCATED"})["answer_calls_pending"], 1)

    def test_only_failed_answer_retries_with_compact_style_and_no_tag_call(self):
        source = self.root / "batch"
        normalize(self.db, source, "ruc", "fixture", [2020])
        selected = _load_source(source)

        class RetryOnlyTasks:
            provider_id = "deepseek"
            model = "deepseek-flash"

            def __init__(self):
                self.runs = []
                self.styles = []

            def answer(self, stem):
                self.styles.append("STANDARD")
                return self._record()

            def answer_compact(self, stem):
                self.styles.append("EXAM_CONCISE")
                return self._record()

            def _record(self):
                self.runs.append({"task": "answer_generation", "provider": "deepseek", "model": self.model,
                                  "duration_ms": 1, "attempts": 1, "input_tokens": 5,
                                  "output_tokens": 5, "estimated_cost": None, "currency": None, "error": None})
                return {"answer": "结论", "analysis": "推导"}

            def recommend(self, stem, topics):
                raise AssertionError("successful tags must not be called")

        for error, expected_style in (("OUTPUT_TRUNCATED", "EXAM_CONCISE"),
                                      ("INTERRUPTED_IN_FLIGHT", "STANDARD")):
            with self.subTest(error=error):
                out = self.root / ("enriched-" + error)
                _create_output(source, out, "deepseek-flash", selected)
                item = read_items(out)[0]
                item["processing_meta"]["enrichment"]["answer_generation"].update(
                    {"status": "UNCERTAIN" if error == "INTERRUPTED_IN_FLIGHT" else "ERROR",
                     "error": error})
                item["processing_meta"]["enrichment"]["tag_recommendation"]["status"] = "SUCCEEDED"
                atomic_json(out / "items" / (item["item_key"] + ".json"), item)
                write_items(out, [item])
                tasks = RetryOnlyTasks()
                with patch("api.bulk_import.enrich.make_tasks", return_value=tasks):
                    result = run(source, out, self.db, allow_model_call=True,
                                 retry_failed=True, retry_errors={error})
                self.assertEqual(result["answer_success"], 1)
                self.assertEqual(result["tag_success"], 1)
                self.assertEqual(tasks.styles, [expected_style])
                updated = read_items(out)[0]
                self.assertEqual(updated["processing_meta"]["model_runs"][-1]["prompt_style"], expected_style)

    def test_review_pack_preserves_existing_sample_and_full_fields(self):
        source = self.root / "batch"
        normalize(self.db, source, "ruc", "fixture", [2020])
        selected = _load_source(source)
        out = self.root / "enriched"
        _create_output(source, out, "deepseek-flash", selected)
        item = read_items(out)[0]
        item["ai_answer"].update({"status": "SUCCEEDED", "answer": "AI结论", "analysis": "AI推导"})
        item["classification"] = {"topic_id": "micro", "question_type": "简答题", "difficulty": 2}
        item["processing_meta"]["enrichment"]["answer_generation"]["status"] = "SUCCEEDED"
        item["processing_meta"]["enrichment"]["tag_recommendation"]["status"] = "SUCCEEDED"
        write_items(out, [item])
        sample = review_sample(out)
        path = review_pack(out)
        rendered = path.read_text(encoding="utf-8")
        self.assertEqual(len(sample), 1)
        for marker in (item["content"]["stem_latex"], item["source_answer"]["text"],
                       "AI结论", "AI推导", "micro", "简答题", "difficulty：2", "来源证据"):
            self.assertIn(marker, rendered)
        self.assertEqual(review_sample(out)[0]["item_key"], sample[0]["item_key"])


if __name__ == "__main__":
    unittest.main()
