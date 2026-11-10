"""HTTP-mocked text provider tests: no credentials or paid requests."""

from __future__ import annotations

import io
import http.client
import json
import os
import socket
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from api.bulk_import.ai import DeepSeekTasks, DoubaoTasks, ModelError, make_tasks
from api.bulk_import.cli import main


class FakeResponse:
    def __init__(self, content: str, usage: dict | None = None, finish_reason: str | None = None):
        self.payload = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                                   "usage": usage or {}}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class TextProviderTests(unittest.TestCase):
    def test_incomplete_http_response_is_bounded_network_error(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model",
               "DEEPSEEK_RETRIES": "0"}
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen",
                side_effect=http.client.IncompleteRead(b"", 1)) as send:
            tasks = DeepSeekTasks()
            with self.assertRaisesRegex(ModelError, "NETWORK_OR_TIMEOUT"):
                tasks.answer("测试题干")
            self.assertEqual(send.call_count, 1)
            self.assertEqual(tasks.runs[-1]["error"], "NETWORK_OR_TIMEOUT")

    def test_answer_output_limit_can_be_raised_without_changing_tag_limit(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model",
               "DEEPSEEK_ANSWER_MAX_TOKENS": "8192"}
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen",
                return_value=FakeResponse('{"answer":"ok","analysis":"ok"}')) as send:
            tasks = DeepSeekTasks()
            tasks.answer("测试题干")
            self.assertEqual(json.loads(send.call_args.args[0].data)["max_tokens"], 8192)
            self.assertEqual(tasks.runs[-1]["max_output_tokens"], 8192)
        with patch.dict(os.environ, {**env, "DEEPSEEK_ANSWER_MAX_TOKENS": "999999"}, clear=True):
            with self.assertRaisesRegex(ModelError, "ANSWER_MAX_TOKENS"):
                DeepSeekTasks()

    def test_compact_answer_uses_same_contract_without_source_answer(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model"}
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen",
                return_value=FakeResponse('{"answer":"结论","analysis":"必要推导"}')) as send:
            tasks = DeepSeekTasks()
            self.assertEqual(tasks.answer_compact("测试题干"),
                             {"answer": "结论", "analysis": "必要推导"})
            prompt = json.loads(send.call_args.args[0].data)["messages"][0]["content"]
            self.assertIn("经济学考研作答风格", prompt)
            self.assertIn("必要公式和推导", prompt)
            self.assertIn("测试题干", prompt)
            self.assertNotIn("来源参考答案", prompt)

    def test_default_gate_never_reads_credentials_or_calls_http(self):
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen") as send:
            self.assertEqual(make_tasks("doubao").__class__.__name__, "DisabledTasks")
            self.assertEqual(make_tasks("deepseek").__class__.__name__, "DisabledTasks")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["model-smoke", "--provider", "deepseek"]), 1)
            self.assertIn("--allow-model-call", stderr.getvalue())
            send.assert_not_called()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ModelError, "DEEPSEEK_API_KEY and DEEPSEEK_MODEL"):
                make_tasks("deepseek", True)

    def test_both_providers_share_answer_contract_and_usage_record(self):
        for provider, cls, prefix, url, provider_id in (
            ("doubao", DoubaoTasks, "DOUBAO_ARK", "https://ark.cn-beijing.volces.com/api/v3/chat/completions", "doubao-ark"),
            ("deepseek", DeepSeekTasks, "DEEPSEEK", "https://api.deepseek.com/chat/completions", "deepseek"),
        ):
            with self.subTest(provider=provider):
                env = {prefix + "_API_KEY": "fixture-secret", prefix + "_MODEL": "fixture-model",
                       prefix + "_RETRIES": "0", prefix + "_INPUT_PRICE_PER_MILLION": "1",
                       prefix + "_OUTPUT_PRICE_PER_MILLION": "2", prefix + "_PRICE_CURRENCY": "CNY"}
                response = FakeResponse('{"answer":"需求量与价格通常反向变动","analysis":"其他条件不变"}',
                                        {"prompt_tokens": 100, "completion_tokens": 50})
                with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=response) as send:
                    tasks = make_tasks(provider, True)
                    self.assertEqual(tasks.answer("测试题干"), {"answer": "需求量与价格通常反向变动", "analysis": "其他条件不变"})
                    request = send.call_args.args[0]
                    self.assertEqual(request.full_url, url)
                    self.assertEqual(json.loads(request.data)["model"], "fixture-model")
                    self.assertEqual(json.loads(request.data)["max_tokens"], 4000)
                    self.assertEqual(json.loads(request.data)["response_format"], {"type": "json_object"})
                    run = tasks.runs[-1]
                    self.assertEqual(run["provider"], provider_id)
                    self.assertEqual(run["task"], "answer_generation")
                    self.assertEqual((run["input_tokens"], run["output_tokens"]), (100, 50))
                    self.assertEqual((run["estimated_cost"], run["currency"]), (0.0002, "CNY"))
                    self.assertEqual(run["attempts"], 1)
                    self.assertIsNone(run["error"])
                    self.assertNotIn("fixture-secret", json.dumps(run))

    def test_tag_recommendation_rejects_unknown_ids_types_and_difficulty(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model"}
        response = FakeResponse('{"topic_id":"invented","question_type":"证明题","difficulty":9}')
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=response):
            tasks = DeepSeekTasks()
            self.assertEqual(tasks.recommend("测试题干", [{"id": "known", "name": "需求"}]),
                             {"topic_id": None, "question_type": None, "difficulty": None})
            self.assertIsNone(tasks.runs[-1]["estimated_cost"])
            self.assertIsNone(tasks.runs[-1]["currency"])

    def test_both_providers_accept_only_allowed_tag_contract(self):
        for cls, prefix in ((DoubaoTasks, "DOUBAO_ARK"), (DeepSeekTasks, "DEEPSEEK")):
            with self.subTest(prefix=prefix):
                env = {prefix + "_API_KEY": "fixture-secret", prefix + "_MODEL": "fixture-model"}
                response = FakeResponse('{"topic_id":"known","question_type":"计算题","difficulty":3}')
                with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=response):
                    tasks = cls()
                    self.assertEqual(tasks.recommend("求均衡", [{"id": "known", "name": "均衡"}]),
                                     {"topic_id": "known", "question_type": "计算题", "difficulty": 3})
                    self.assertEqual(tasks.runs[-1]["task"], "tag_recommendation")

    def test_output_limit_is_classified_without_json_retry(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model"}
        response = FakeResponse('{"answer":"partial', {"prompt_tokens": 130, "completion_tokens": 4000}, "length")
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=response) as send:
            tasks = DeepSeekTasks()
            with self.assertRaisesRegex(ModelError, "OUTPUT_TRUNCATED"):
                tasks.answer("测试题干")
            self.assertEqual(send.call_count, 1)
            self.assertEqual(tasks.runs[-1]["output_tokens"], 4000)
            self.assertEqual(tasks.runs[-1]["error"], "OUTPUT_TRUNCATED")

    def test_auth_failure_is_sanitized_and_never_retried(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model"}
        failure = urllib.error.HTTPError("https://api.deepseek.com/chat/completions", 401,
                                         "fixture-secret leaked by upstream", {}, io.BytesIO(b"fixture-secret"))
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", side_effect=failure) as send:
            tasks = DeepSeekTasks()
            with self.assertRaisesRegex(ModelError, "HTTP_401") as raised:
                tasks.answer("测试题干")
            self.assertEqual(send.call_count, 1)
            self.assertEqual(tasks.runs[-1]["attempts"], 1)
            self.assertEqual(tasks.runs[-1]["error"], "HTTP_401")
            self.assertNotIn("fixture-secret", str(raised.exception) + json.dumps(tasks.runs))

    def test_transient_429_retries_but_invalid_json_does_not(self):
        env = {"DOUBAO_ARK_API_KEY": "fixture-secret", "DOUBAO_ARK_MODEL": "fixture-model",
               "DOUBAO_ARK_RETRIES": "1"}
        failure = urllib.error.HTTPError("https://example.test", 429, "retry", {}, None)
        good = FakeResponse('{"answer":"ok","analysis":"because"}')
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", side_effect=[failure, good]) as send, patch("time.sleep"):
            tasks = DoubaoTasks()
            tasks.answer("测试题干")
            self.assertEqual(send.call_count, 2)
            self.assertEqual(tasks.runs[-1]["attempts"], 2)
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=FakeResponse("not json")) as send:
            tasks = DoubaoTasks()
            with self.assertRaisesRegex(ModelError, "INVALID_STRUCTURED_RESPONSE"):
                tasks.answer("测试题干")
            self.assertEqual(send.call_count, 1)
            self.assertEqual(tasks.runs[-1]["error"], "INVALID_STRUCTURED_RESPONSE")

    def test_invalid_answer_preserves_returned_usage_without_retry(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model"}
        response = FakeResponse('{"answer":"","analysis":""}',
                                {"prompt_tokens": 23, "completion_tokens": 5})
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=response) as send:
            tasks = DeepSeekTasks()
            with self.assertRaisesRegex(ModelError, "INVALID_STRUCTURED_RESPONSE"):
                tasks.answer("测试题干")
            self.assertEqual(send.call_count, 1)
            self.assertEqual((tasks.runs[-1]["input_tokens"], tasks.runs[-1]["output_tokens"]), (23, 5))
            self.assertIsNone(tasks.runs[-1]["estimated_cost"])

    def test_timeout_retry_and_text_only_scope(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model",
               "DEEPSEEK_RETRIES": "1"}
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", side_effect=socket.timeout()) as send, patch("time.sleep"):
            tasks = DeepSeekTasks()
            with self.assertRaisesRegex(ModelError, "NETWORK_OR_TIMEOUT"):
                tasks.answer("测试题干")
            self.assertEqual(send.call_count, 2)
            self.assertEqual(tasks.runs[-1]["attempts"], 2)
            with self.assertRaises(ModelError):
                tasks.vision(b"fixture", "image/png")
            with self.assertRaises(ModelError):
                tasks.structure("fixture")

    def test_unexpected_network_error_is_sanitized(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model",
               "DEEPSEEK_RETRIES": "0"}
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", side_effect=OSError("fixture-secret")):
            tasks = DeepSeekTasks()
            with self.assertRaises(ModelError) as raised:
                tasks.answer("测试题干")
            self.assertNotIn("fixture-secret", str(raised.exception) + json.dumps(tasks.runs))

    def test_smoke_uses_generic_prompt_and_prints_only_metadata(self):
        env = {"DEEPSEEK_API_KEY": "fixture-secret", "DEEPSEEK_MODEL": "fixture-model"}
        stdout = io.StringIO()
        response = FakeResponse('{"answer":"反向关系","analysis":"其他条件不变"}')
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", return_value=response) as send, redirect_stdout(stdout):
            self.assertEqual(main(["model-smoke", "--provider", "deepseek", "--allow-model-call"]), 0)
        sent_prompt = json.loads(send.call_args.args[0].data)["messages"][0]["content"]
        self.assertIn("需求曲线向右下方倾斜", sent_prompt)
        self.assertNotIn("fixture-secret", stdout.getvalue())
        self.assertNotIn("反向关系", stdout.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["format_valid"])


if __name__ == "__main__":
    unittest.main()
