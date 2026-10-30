"""Unit tests for api.providers.doubao.

All HTTP calls are mocked; no real network, no real API key, no paid calls.
Run from the repo root:

    python -m unittest discover -s api -p 'test_*.py'
"""

from __future__ import annotations

import json
import socket
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from api.providers.doubao import (
    DoubaoProviderAuthError,
    DoubaoProviderConfigError,
    DoubaoProviderInputError,
    DoubaoProviderNetworkError,
    DoubaoProviderRateLimitError,
    DoubaoProviderResponseError,
    DoubaoProviderTimeoutError,
    DoubaoProviderUpstreamError,
    DoubaoVisionRecognitionProvider,
    create_doubao_provider,
)
from api.recognition import RecognitionCandidate


FAKE_KEY = "test-secret-key-abcdef123456"
FAKE_MODEL = "doubao-vision-test-model"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _make_http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://ark.example.test/api/v3/chat/completions",
        code=code,
        msg="status",
        hdrs=None,
        fp=None,
    )


def _fake_chat_response(content_text: str) -> bytes:
    payload = {
        "choices": [
            {"message": {"content": content_text}, "finish_reason": "stop"}
        ]
    }
    return json.dumps(payload).encode("utf-8")


def _mock_urlopen_returning(body: bytes):
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class FactoryConfigTests(unittest.TestCase):
    """Factory must fail loudly on missing config and never send a request."""

    def setUp(self):
        # Ensure a clean env for each factory test.
        for var in (
            "DOUBAO_ARK_API_KEY",
            "DOUBAO_ARK_MODEL",
            "DOUBAO_ARK_BASE_URL",
            "DOUBAO_ARK_TIMEOUT_SECONDS",
            "DOUBAO_ARK_MAX_TOKENS",
        ):
            self.addCleanup(self._restore_env, var)
            self._saved = getattr(self, "_saved", {})
            self._saved[var] = __import__("os").environ.get(var)

    def _restore_env(self, var: str) -> None:
        import os

        val = self._saved.get(var)
        if val is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = val

    def _set(self, **kwargs):
        import os

        for k, v in kwargs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_missing_key_raises_config_error(self):
        self._set(DOUBAO_ARK_API_KEY="", DOUBAO_ARK_MODEL=FAKE_MODEL)
        with self.assertRaises(DoubaoProviderConfigError):
            create_doubao_provider()

    def test_missing_model_raises_config_error(self):
        self._set(DOUBAO_ARK_API_KEY=FAKE_KEY, DOUBAO_ARK_MODEL="")
        with self.assertRaises(DoubaoProviderConfigError):
            create_doubao_provider()

    def test_invalid_timeout_raises(self):
        self._set(
            DOUBAO_ARK_API_KEY=FAKE_KEY,
            DOUBAO_ARK_MODEL=FAKE_MODEL,
            DOUBAO_ARK_TIMEOUT_SECONDS="not-a-number",
        )
        with self.assertRaises(DoubaoProviderConfigError):
            create_doubao_provider()

    def test_factory_builds_provider_with_defaults(self):
        self._set(
            DOUBAO_ARK_API_KEY=FAKE_KEY,
            DOUBAO_ARK_MODEL=FAKE_MODEL,
            DOUBAO_ARK_BASE_URL="",
            DOUBAO_ARK_TIMEOUT_SECONDS="",
            DOUBAO_ARK_MAX_TOKENS="",
        )
        p = create_doubao_provider()
        self.assertIsInstance(p, DoubaoVisionRecognitionProvider)


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        self.p = DoubaoVisionRecognitionProvider(api_key=FAKE_KEY, model=FAKE_MODEL)

    def test_empty_image_raises_input_error(self):
        with self.assertRaises(DoubaoProviderInputError):
            self.p.recognize(b"", "image/png")

    def test_unsupported_mime_raises_input_error(self):
        with self.assertRaises(DoubaoProviderInputError):
            self.p.recognize(PNG_BYTES, "image/gif")

    def test_uppercase_mime_is_normalized(self):
        # Should not raise; uppercase image/PNG is normalized to image/png.
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            return_value=_mock_urlopen_returning(_fake_chat_response("[]")),
        ) as m:
            self.p.recognize(PNG_BYTES, "IMAGE/PNG")
            m.assert_called_once()


class SuccessParseTests(unittest.TestCase):
    def setUp(self):
        self.p = DoubaoVisionRecognitionProvider(api_key=FAKE_KEY, model=FAKE_MODEL)

    def _recognize_with_content(self, content_text: str):
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            return_value=_mock_urlopen_returning(_fake_chat_response(content_text)),
        ):
            return self.p.recognize(PNG_BYTES, "image/png")

    def test_single_candidate_parsed(self):
        items = self._recognize_with_content(
            json.dumps(
                [
                    {
                        "stem": "什么是边际效用递减规律？",
                        "subject": "微观经济学",
                        "difficulty": 2,
                        "answer": "在一定时间内...",
                        "analysis": "随着消费数量增加...",
                        "question_type": "名词解释",
                        "confidence_note": "题干清晰",
                    }
                ]
            )
        )
        self.assertEqual(len(items), 1)
        c = items[0]
        self.assertIsInstance(c, RecognitionCandidate)
        self.assertEqual(c.stem, "什么是边际效用递减规律？")
        self.assertEqual(c.subject, "微观经济学")
        self.assertEqual(c.difficulty, 2)
        self.assertEqual(c.question_type, "名词解释")
        self.assertIn("题干清晰", c.confidence_note)

    def test_multiple_candidates_parsed(self):
        items = self._recognize_with_content(
            json.dumps(
                [
                    {"stem": "题一", "difficulty": 1},
                    {"stem": "题二", "difficulty": 5},
                ]
            )
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].stem, "题一")
        self.assertEqual(items[1].difficulty, 5)

    def test_empty_array_returns_empty_list(self):
        self.assertEqual(self._recognize_with_content("[]"), [])

    def test_markdown_fence_is_stripped(self):
        fenced = "```json\n" + json.dumps([{"stem": "题A"}]) + "\n```"
        items = self._recognize_with_content(fenced)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].stem, "题A")

    def test_non_dict_items_are_skipped(self):
        items = self._recognize_with_content(json.dumps([{"stem": "好题"}, "not-a-dict", 42]))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].stem, "好题")

    def test_empty_stem_is_rejected_not_silently_kept(self):
        # An item with empty stem fails RecognitionCandidate validation and must be dropped.
        items = self._recognize_with_content(
            json.dumps([{"stem": "", "difficulty": 2}, {"stem": "合法题干"}])
        )
        stems = [c.stem for c in items]
        self.assertNotIn("", stems)
        self.assertIn("合法题干", stems)

    def test_difficulty_out_of_range_is_dropped(self):
        items = self._recognize_with_content(
            json.dumps(
                [
                    {"stem": "超难", "difficulty": 9},
                    {"stem": "超易", "difficulty": 0},
                    {"stem": "合法", "difficulty": 3},
                ]
            )
        )
        stems = [c.stem for c in items]
        self.assertEqual(stems, ["合法"])

    def test_difficulty_null_is_accepted(self):
        items = self._recognize_with_content(json.dumps([{"stem": "无难度", "difficulty": None}]))
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0].difficulty)

    def test_non_string_fields_are_coerced(self):
        # Model sometimes returns numbers where strings expected; coercion must not crash.
        items = self._recognize_with_content(
            json.dumps([{"stem": 12345, "subject": 7}])
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].stem, "12345")
        self.assertEqual(items[0].subject, "7")


class TransportErrorMappingTests(unittest.TestCase):
    def setUp(self):
        self.p = DoubaoVisionRecognitionProvider(api_key=FAKE_KEY, model=FAKE_MODEL)

    def _expect(self, side_effect, expected_exc):
        with patch("api.providers.doubao.urllib.request.urlopen", side_effect=side_effect):
            with self.assertRaises(expected_exc):
                self.p.recognize(PNG_BYTES, "image/png")

    def test_401_maps_to_auth_error(self):
        self._expect(_make_http_error(401), DoubaoProviderAuthError)

    def test_403_maps_to_auth_error(self):
        self._expect(_make_http_error(403), DoubaoProviderAuthError)

    def test_429_maps_to_rate_limit(self):
        self._expect(_make_http_error(429), DoubaoProviderRateLimitError)

    def test_500_maps_to_upstream_error(self):
        self._expect(_make_http_error(500), DoubaoProviderUpstreamError)

    def test_503_maps_to_upstream_error(self):
        self._expect(_make_http_error(503), DoubaoProviderUpstreamError)

    def test_400_maps_to_response_error(self):
        self._expect(_make_http_error(400), DoubaoProviderResponseError)

    def test_timeout_maps_to_timeout_error(self):
        self._expect(urllib.error.URLError(socket.timeout()), DoubaoProviderTimeoutError)

    def test_network_error_maps_to_network_error(self):
        self._expect(
            urllib.error.URLError(ConnectionResetError("reset by peer")),
            DoubaoProviderNetworkError,
        )

    def test_invalid_json_response(self):
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            return_value=_mock_urlopen_returning(b"<html>502 bad gateway</html>"),
        ):
            with self.assertRaises(DoubaoProviderResponseError):
                self.p.recognize(PNG_BYTES, "image/png")

    def test_missing_choices_shape(self):
        bad = json.dumps({"error": {"message": "model overloaded"}}).encode("utf-8")
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            return_value=_mock_urlopen_returning(bad),
        ):
            with self.assertRaises(DoubaoProviderResponseError):
                self.p.recognize(PNG_BYTES, "image/png")

    def test_non_array_content(self):
        # content is a JSON object, not an array.
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            return_value=_mock_urlopen_returning(
                _fake_chat_response(json.dumps({"not": "an array"}))
            ),
        ):
            with self.assertRaises(DoubaoProviderResponseError):
                self.p.recognize(PNG_BYTES, "image/png")


class SecretLeakTests(unittest.TestCase):
    """No exception text or log record must contain the API key or 'Authorization'."""

    def test_auth_error_message_does_not_contain_key(self):
        p = DoubaoVisionRecognitionProvider(api_key=FAKE_KEY, model=FAKE_MODEL)
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            side_effect=_make_http_error(401),
        ):
            try:
                p.recognize(PNG_BYTES, "image/png")
                self.fail("expected DoubaoProviderAuthError")
            except DoubaoProviderAuthError as e:
                self.assertNotIn(FAKE_KEY, str(e))
                self.assertNotIn("Bearer", str(e))

    def test_network_error_message_does_not_contain_key(self):
        p = DoubaoVisionRecognitionProvider(api_key=FAKE_KEY, model=FAKE_MODEL)
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            side_effect=urllib.error.URLError(ConnectionResetError("reset")),
        ):
            try:
                p.recognize(PNG_BYTES, "image/png")
                self.fail("expected DoubaoProviderNetworkError")
            except DoubaoProviderNetworkError as e:
                self.assertNotIn(FAKE_KEY, str(e))

    def test_config_error_messages_are_safe(self):
        with self.assertRaises(DoubaoProviderConfigError) as ctx:
            DoubaoVisionRecognitionProvider(api_key="", model=FAKE_MODEL)
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_request_headers_do_not_leak_key_into_exception(self):
        # Even if urlopen raises, the exception must not carry the request headers.
        p = DoubaoVisionRecognitionProvider(api_key=FAKE_KEY, model=FAKE_MODEL)
        with patch(
            "api.providers.doubao.urllib.request.urlopen",
            side_effect=_make_http_error(429),
        ) as mocked:
            try:
                p.recognize(PNG_BYTES, "image/png")
            except DoubaoProviderRateLimitError as e:
                self.assertNotIn(FAKE_KEY, str(e))
                # The request that was built must contain the auth header internally
                # (otherwise the call would fail auth), but our exception text must
                # not echo it.
                sent_req = mocked.call_args.args[0]
                self.assertIn("Authorization", sent_req.headers)


if __name__ == "__main__":
    unittest.main()
