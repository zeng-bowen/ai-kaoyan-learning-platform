"""Regression checks for additive target migration and manual source review."""

import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException


class TargetCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Windows scanners may briefly keep the SQLite file open after close.
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.path = Path(cls.temp.name) / "platform.db"
        with sqlite3.connect(cls.path) as con:
            con.executescript("""
                CREATE TABLE targets(id TEXT PRIMARY KEY, school TEXT NOT NULL, major TEXT NOT NULL, exam_subject TEXT NOT NULL, target_year INTEGER NOT NULL, verified INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE topics(id TEXT PRIMARY KEY, subject TEXT NOT NULL, module TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL);
                CREATE TABLE questions(id TEXT PRIMARY KEY, target_id TEXT NOT NULL, topic_id TEXT NOT NULL, source_type TEXT NOT NULL, source_name TEXT NOT NULL, question_type TEXT NOT NULL, difficulty INTEGER NOT NULL, stem TEXT NOT NULL, answer TEXT NOT NULL, analysis TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'DRAFT');
                CREATE TABLE attempts(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, question_id TEXT NOT NULL, answer_text TEXT NOT NULL, self_rating INTEGER NOT NULL, created_at TEXT NOT NULL);
                INSERT INTO targets VALUES ('legacy','旧院校','旧专业','旧科目',2028,0);
                INSERT INTO topics VALUES ('legacy-topic','微观','模块','知识点','摘要');
                INSERT INTO questions VALUES ('legacy-question','legacy','legacy-topic','CURATED_EXERCISE','演示','简答题',2,'测试题干','答案','解析','APPROVED');
                INSERT INTO attempts(user_id,question_id,answer_text,self_rating,created_at) VALUES ('local-demo','legacy-question','我的回答',2,'2026-01-01');
            """)
        cls.old_path = os.environ.get("ECON_DB_PATH")
        os.environ["ECON_DB_PATH"] = str(cls.path)
        cls.api = importlib.import_module("api.main")

    @classmethod
    def tearDownClass(cls):
        if cls.old_path is None:
            os.environ.pop("ECON_DB_PATH", None)
        else:
            os.environ["ECON_DB_PATH"] = cls.old_path
        cls.temp.cleanup()

    def payload(self, **changes):
        fields = dict(id="school-test-2028", school="测试大学", college="经济学院", major="经济学", exam_subject="经济学综合", exam_code="901", target_year=2028, source_url="https://example.edu/admission")
        return self.api.TargetIn(**(fields | changes))

    def test_legacy_records_survive_migration(self):
        legacy = next(item for item in self.api.targets() if item["id"] == "legacy")
        self.assertEqual(legacy["college"], "")
        self.assertEqual(len(self.api.attempts()), 1)

    def test_create_verify_and_edit_resets_review(self):
        self.api.create_target(self.payload())
        verified = self.api.verify_target("school-test-2028")
        self.assertEqual(verified["verified"], 1)
        self.assertIsNotNone(verified["source_checked_at"])
        self.api.update_target("school-test-2028", self.payload(exam_code="902"))
        item = next(item for item in self.api.targets() if item["id"] == "school-test-2028")
        self.assertEqual(item["exam_code"], "902")
        self.assertEqual(item["verified"], 0)
        self.assertIsNone(item["source_checked_at"])

    def test_missing_or_insecure_source_cannot_be_verified(self):
        self.api.create_target(self.payload(id="no-source", source_url=""))
        with self.assertRaises(HTTPException) as missing:
            self.api.verify_target("no-source")
        self.assertEqual(missing.exception.status_code, 422)
        with self.assertRaises(HTTPException) as insecure:
            self.api.create_target(self.payload(id="bad-source", source_url="http://example.edu"))
        self.assertEqual(insecure.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
