"""Regression checks for additive exam-tag migration and manual content review."""

import importlib
import base64
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from api.recognition import RecognitionCandidate


class TargetCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Windows scanners may briefly keep the SQLite file open after close.
        test_data_dir = Path(__file__).resolve().parents[1] / "data"
        test_data_dir.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=test_data_dir, ignore_cleanup_errors=True)
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
        cls.old_provider = os.environ.pop("ECON_RECOGNITION_PROVIDER", None)
        os.environ["ECON_DB_PATH"] = str(cls.path)
        cls.api = importlib.import_module("api.main")

    @classmethod
    def tearDownClass(cls):
        if cls.old_path is None:
            os.environ.pop("ECON_DB_PATH", None)
        else:
            os.environ["ECON_DB_PATH"] = cls.old_path
        if cls.old_provider is not None:
            os.environ["ECON_RECOGNITION_PROVIDER"] = cls.old_provider
        cls.temp.cleanup()

    def upload_intake(self, client: TestClient, file_name: str = "test.png") -> str:
        image = base64.b64encode(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aXcAAAAASUVORK5CYII="
        )).decode()
        uploaded = client.post('/api/admin/intakes', json={
            'file_name': file_name, 'mime_type': 'image/png', 'base64_data': image,
        })
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        return uploaded.json()['id']

    def intake_record(self, intake_id: str) -> dict:
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT status,recognition_json FROM question_intakes WHERE id=?", (intake_id,)
            ).fetchone()
        self.assertIsNotNone(row)
        return dict(row)

    @staticmethod
    def candidate(stem: str = "用于识别回归测试的题干") -> RecognitionCandidate:
        return RecognitionCandidate(
            stem=stem,
            subject="微观经济学",
            difficulty=3,
            answer="测试答案",
            analysis="测试解析",
            question_type="简答题",
            confidence_note="演示候选，需人工审核",
        )

    def payload(self, **changes):
        fields = dict(school="测试大学", exam_label="901 经济学综合", note="测试备注")
        return self.api.TargetIn(**(fields | changes))

    def test_legacy_records_survive_migration(self):
        legacy = next(item for item in self.api.targets() if item["id"] == "legacy")
        self.assertEqual(legacy["exam_label"], "旧科目")
        self.assertEqual(legacy["target_year"], self.api.current_exam_year())
        self.assertEqual(self.api.topics("legacy")[0]["target_ids"], ["legacy"])
        self.assertEqual(len(self.api.attempts()), 1)

    def test_three_field_tag_create_edit_and_auto_year(self):
        client = TestClient(self.api.app)
        created = client.post('/api/admin/targets', json=self.payload().model_dump())
        self.assertEqual(created.status_code, 200, created.text)
        target_id = created.json()['id']
        self.assertEqual(created.json()['target_year'], self.api.current_exam_year())
        item = next(item for item in client.get('/api/targets').json() if item['id'] == target_id)
        self.assertEqual(item['exam_label'], '901 经济学综合')
        self.assertEqual(item['note'], '测试备注')
        self.assertEqual(client.post('/api/admin/targets', json=self.payload().model_dump()).status_code, 409)
        edit = client.put(f'/api/admin/targets/{target_id}', json=self.payload(exam_label='902 经济学').model_dump())
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(next(item for item in client.get('/api/targets').json() if item['id'] == target_id)['exam_label'], '902 经济学')
        self.assertEqual(client.post('/api/admin/targets', json={**self.payload().model_dump(), 'target_year': 2028}).status_code, 422)
        self.assertEqual(client.post('/api/admin/targets', json={**self.payload().model_dump(), 'source_url': 'https://example.edu'}).status_code, 422)

    def test_local_admin_question_publication_cycle(self):
        client = TestClient(self.api.app)
        self.assertEqual(client.get('/api/admin/questions').status_code, 200)
        remote = TestClient(self.api.app, client=('198.51.100.7', 50000))
        self.assertEqual(remote.get('/api/admin/questions').status_code, 403)
        self.assertEqual(client.get('/api/admin/questions', headers={'Host': 'untrusted.example'}).status_code, 400)
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

    def test_recognition_batch_boundaries_accept_one_to_fifty_items(self):
        client = TestClient(self.api.app)
        intake_id = self.upload_intake(client, "batch-boundary.png")
        provider = Mock()
        provider.recognize.return_value = [self.candidate()]
        with patch.object(self.api, "configured_provider", return_value=provider):
            lower = client.post('/api/admin/intakes/recognize-batch', json={'intake_ids': [intake_id]})
            upper = client.post('/api/admin/intakes/recognize-batch', json={'intake_ids': [intake_id] * 50})
            self.assertEqual(lower.status_code, 200, lower.text)
            self.assertEqual(len(lower.json()), 1)
            self.assertEqual(upper.status_code, 200, upper.text)
            self.assertEqual(len(upper.json()), 50)
        self.assertEqual(client.post('/api/admin/intakes/recognize-batch', json={'intake_ids': []}).status_code, 422)
        self.assertEqual(client.post('/api/admin/intakes/recognize-batch', json={'intake_ids': [intake_id] * 51}).status_code, 422)

    def test_recognition_batch_reports_item_failures_and_continues(self):
        client = TestClient(self.api.app)
        first_id = self.upload_intake(client, "batch-first.png")
        failed_id = self.upload_intake(client, "batch-failed.png")
        missing_id = "missing-intake"
        provider = Mock()
        provider.recognize.side_effect = [[self.candidate("批量成功候选")], RuntimeError("upstream secret")]
        before_questions = client.get('/api/admin/questions').json()
        with patch.object(self.api, "configured_provider", return_value=provider) as configured:
            response = client.post('/api/admin/intakes/recognize-batch', json={
                'intake_ids': [first_id, missing_id, failed_id],
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(configured.call_count, 1)
        self.assertEqual(response.json()[0]['status'], 'AI_DRAFT')
        self.assertEqual(response.json()[1], {
            'id': missing_id, 'status': 'ERROR',
            'error': {'status_code': 404, 'detail': '上传图片不存在'},
        })
        self.assertEqual(response.json()[2]['status'], 'ERROR')
        self.assertEqual(response.json()[2]['error']['status_code'], 502)
        self.assertNotIn('secret', response.text.lower())
        self.assertEqual(self.intake_record(first_id)['status'], 'AI_DRAFT')
        self.assertEqual(self.intake_record(failed_id)['status'], 'AWAITING_PROVIDER')
        self.assertEqual(client.get('/api/admin/questions').json(), before_questions)

    def test_recognition_configuration_errors_are_safe(self):
        client = TestClient(self.api.app)
        intake_id = self.upload_intake(client, "configuration.png")
        with patch.object(self.api, "configured_provider", return_value=None):
            missing = client.post('/api/admin/intakes/missing-intake/recognize')
            single = client.post(f'/api/admin/intakes/{intake_id}/recognize')
            batch = client.post('/api/admin/intakes/recognize-batch', json={'intake_ids': [intake_id]})
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(single.status_code, 501, single.text)
        self.assertEqual(batch.status_code, 501, batch.text)
        with patch.object(self.api, "configured_provider", side_effect=RuntimeError("api-key=do-not-leak")):
            single = client.post(f'/api/admin/intakes/{intake_id}/recognize')
            batch = client.post('/api/admin/intakes/recognize-batch', json={'intake_ids': [intake_id]})
        self.assertEqual(single.status_code, 503, single.text)
        self.assertEqual(batch.status_code, 503, batch.text)
        self.assertNotIn('do-not-leak', single.text)
        self.assertNotIn('do-not-leak', batch.text)
        self.assertEqual(self.intake_record(intake_id)['status'], 'AWAITING_PROVIDER')

    def test_recognition_failures_and_empty_candidates_preserve_intakes(self):
        client = TestClient(self.api.app)
        failed_id = self.upload_intake(client, "provider-failure.png")
        empty_id = self.upload_intake(client, "empty-candidates.png")
        provider = Mock()
        provider.recognize.side_effect = RuntimeError("Authorization: Bearer secret-token")
        with patch.object(self.api, "configured_provider", return_value=provider):
            failed = client.post(f'/api/admin/intakes/{failed_id}/recognize')
        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertNotIn('secret-token', failed.text)
        provider.recognize.side_effect = None
        provider.recognize.return_value = []
        with patch.object(self.api, "configured_provider", return_value=provider):
            empty = client.post(f'/api/admin/intakes/{empty_id}/recognize')
        self.assertEqual(empty.status_code, 502, empty.text)
        self.assertIn('未返回候选建议', empty.json()['detail'])
        for intake_id in (failed_id, empty_id):
            record = self.intake_record(intake_id)
            self.assertEqual(record['status'], 'AWAITING_PROVIDER')
            self.assertIsNone(record['recognition_json'])

    def test_recognition_success_is_only_a_reviewable_draft(self):
        client = TestClient(self.api.app)
        intake_id = self.upload_intake(client, "multi-candidates.png")
        before_admin_questions = client.get('/api/admin/questions').json()
        before_public_questions = client.get('/api/questions').json()
        provider = Mock()
        provider.recognize.return_value = [self.candidate("第一条候选题干"), self.candidate("第二条候选题干")]
        with patch.object(self.api, "configured_provider", return_value=provider):
            response = client.post(f'/api/admin/intakes/{intake_id}/recognize')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'AI_DRAFT')
        self.assertEqual(len(response.json()['suggestions']), 2)
        record = self.intake_record(intake_id)
        self.assertEqual(record['status'], 'AI_DRAFT')
        self.assertEqual(len(json.loads(record['recognition_json'])), 2)
        self.assertEqual(client.get('/api/admin/questions').json(), before_admin_questions)
        self.assertEqual(client.get('/api/questions').json(), before_public_questions)

        draft = {
            'id': 'q-ai-review-boundary', 'target_id': 'legacy', 'topic_id': 'legacy-topic',
            'source_type': 'CURATED_EXERCISE', 'source_name': '待人工核对来源',
            'question_type': '简答题', 'difficulty': 3, 'stem': '人工核对后保存的识别候选题干。',
            'answer': '待人工核对的答案', 'analysis': '待人工核对的解析', 'intake_id': intake_id,
        }
        created = client.post('/api/admin/questions', json=draft)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()['review_status'], 'DRAFT')
        review = client.post('/api/admin/questions/q-ai-review-boundary/review', json={'decision': 'APPROVED'})
        self.assertEqual(review.status_code, 422, review.text)
        self.assertFalse(any(item['id'] == draft['id'] for item in client.get('/api/questions').json()))

    def test_topic_and_question_must_share_exam_tag(self):
        client = TestClient(self.api.app)
        created_tag = client.post('/api/admin/targets', json={'school': '标签测试大学', 'exam_label': '834 经济学', 'note': '测试用'})
        self.assertEqual(created_tag.status_code, 200, created_tag.text)
        tag_id = created_tag.json()['id']
        topic = {'id': 'tagged-topic', 'subject': '微观经济学', 'module': '消费者理论', 'name': '考试标签测试知识点',
                 'summary': '用于检查考试标签筛选和发布约束。', 'source_name': '本地测试来源',
                 'source_url': 'https://example.edu/topic', 'target_ids': [tag_id]}
        self.assertEqual(client.post('/api/admin/topics', json=topic).status_code, 200)
        self.assertEqual(client.post('/api/admin/topics/tagged-topic/approve').status_code, 200)
        self.assertTrue(any(item['id'] == topic['id'] for item in client.get(f'/api/topics?target_id={tag_id}').json()))
        self.assertFalse(any(item['id'] == topic['id'] for item in client.get('/api/topics?target_id=legacy').json()))
        question = {'id': 'q-tagged-test', 'target_id': 'legacy', 'topic_id': topic['id'], 'source_type': 'CURATED_EXERCISE',
                    'source_name': '本地测试来源', 'question_type': '简答题', 'difficulty': 2,
                    'stem': '解释用于验证标签约束的经济学概念。', 'answer': '测试答案', 'analysis': '测试解析'}
        self.assertEqual(client.post('/api/admin/questions', json=question).status_code, 200)
        self.assertEqual(client.post('/api/admin/questions/q-tagged-test/review', json={'decision': 'APPROVED'}).status_code, 422)
        self.assertEqual(client.put('/api/admin/questions/q-tagged-test', json={**question, 'target_id': tag_id}).status_code, 200)
        self.assertEqual(client.post('/api/admin/questions/q-tagged-test/review', json={'decision': 'APPROVED'}).status_code, 200)
        self.assertTrue(any(item['id'] == question['id'] for item in client.get(f'/api/questions?target_id={tag_id}').json()))
        self.assertFalse(any(item['id'] == question['id'] for item in client.get('/api/questions?target_id=legacy').json()))
        self.assertEqual(client.put('/api/admin/topics/tagged-topic', json={**topic, 'target_ids': ['legacy']}).status_code, 200)
        self.assertFalse(any(item['id'] == question['id'] for item in client.get(f'/api/questions?target_id={tag_id}').json()))
        importlib.reload(self.api)
        self.assertFalse(any(item['id'] == question['id'] for item in TestClient(self.api.app).get(f'/api/questions?target_id={tag_id}').json()))

    def test_topic_review_and_image_queue(self):
        client = TestClient(self.api.app)
        topic = {'id': 'topic-review-test', 'subject': '微观经济学', 'module': '需求理论', 'name': '测试知识点',
                 'summary': '仅用于验证知识目录审核流程。', 'source_name': '本地测试来源', 'source_url': 'https://example.edu/topic', 'target_ids': ['legacy']}
        created = client.post('/api/admin/topics', json=topic)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertFalse(any(item['id'] == topic['id'] for item in client.get('/api/topics').json()))
        self.assertEqual(client.post('/api/admin/topics/topic-review-test/approve').status_code, 200)
        self.assertTrue(any(item['id'] == topic['id'] for item in client.get('/api/topics').json()))
        self.assertTrue(any(item['id'] == topic['id'] for item in client.get('/api/topics?target_id=legacy').json()))
        intake_id = self.upload_intake(client)
        self.assertEqual(client.get(f'/api/admin/intakes/{intake_id}/image').status_code, 200)
        self.assertEqual(client.post(f'/api/admin/intakes/{intake_id}/recognize').status_code, 501)


if __name__ == "__main__":
    unittest.main()
