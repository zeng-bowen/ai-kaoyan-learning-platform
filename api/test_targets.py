"""Regression checks for additive target migration and manual source review."""

import importlib
import base64
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient


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

    def test_local_admin_question_publication_cycle(self):
        client = TestClient(self.api.app)
        self.assertEqual(client.get('/api/admin/questions').status_code, 200)
        initial = client.get('/api/versions').json()['content']
        payload = {
            'id': 'q-review-test', 'target_id': 'legacy', 'topic_id': 'legacy-topic',
            'source_type': 'CURATED_EXERCISE', 'source_name': '本地测试来源',
            'question_type': '简答题', 'difficulty': 3, 'stem': '解释一个用于测试的经济学概念。',
            'answer': '测试参考答案', 'analysis': '测试解析',
        }
        created = client.post('/api/admin/questions', json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertRegex(created.json()['catalog_number'], r'^Q-\d{6}$')
        self.assertGreater(client.get('/api/versions').json()['content'], initial)
        self.assertFalse(any(q['id'] == payload['id'] for q in client.get('/api/questions').json()))
        self.assertTrue(any(q['id'] == payload['id'] for q in client.get('/api/admin/questions').json()))
        reviewed = client.post('/api/admin/questions/q-review-test/review', json={'decision': 'APPROVED'})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertTrue(any(q['id'] == payload['id'] for q in client.get('/api/questions').json()))
        edit = client.put('/api/admin/questions/q-review-test', json={**payload, 'catalog_number': created.json()['catalog_number'], 'stem': '修改后需要重新审核的测试题干。'})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertFalse(any(q['id'] == payload['id'] for q in client.get('/api/questions').json()))

    def test_presence_and_admin_metric_are_separate_from_correctness(self):
        client = TestClient(self.api.app)
        self.assertEqual(client.post('/api/study-presence', json={'session_id': 'test-session-1234567890', 'active': True}).status_code, 200)
        metrics = client.get('/api/admin/stats').json()
        self.assertGreaterEqual(metrics['active_training_sessions'], 1)
        self.assertIsNone(metrics['correct_rate'])

    def test_topic_review_and_image_queue(self):
        client = TestClient(self.api.app)
        topic = {'id': 'topic-review-test', 'subject': '微观经济学', 'module': '需求理论', 'name': '测试知识点',
                 'summary': '仅用于验证知识目录审核流程。', 'source_name': '本地测试来源', 'source_url': 'https://example.edu/topic'}
        created = client.post('/api/admin/topics', json=topic)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertFalse(any(item['id'] == topic['id'] for item in client.get('/api/topics').json()))
        self.assertEqual(client.post('/api/admin/topics/topic-review-test/approve').status_code, 200)
        self.assertTrue(any(item['id'] == topic['id'] for item in client.get('/api/topics').json()))
        image = base64.b64encode(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aXcAAAAASUVORK5CYII=')).decode()
        uploaded = client.post('/api/admin/intakes', json={'file_name': 'test.png', 'mime_type': 'image/png', 'base64_data': image})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        intake_id = uploaded.json()['id']
        self.assertEqual(client.get(f'/api/admin/intakes/{intake_id}/image').status_code, 200)
        self.assertEqual(client.post(f'/api/admin/intakes/{intake_id}/recognize').status_code, 501)


if __name__ == "__main__":
    unittest.main()
