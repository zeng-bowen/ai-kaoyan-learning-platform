"""Volcengine Ark / Doubao vision RecognitionProvider.

This module implements the ``RecognitionProvider`` contract defined in
``api/recognition.py`` using only the Python standard library (``urllib``), so no
extra third-party SDK is required. It calls the Ark Chat Completions endpoint
(OpenAI-compatible) with an inline base64 image and a constrained prompt, then
maps the model output into ``list[RecognitionCandidate]``.

Activation (on the backend process):

.. code-block:: text

    ECON_RECOGNITION_PROVIDER=api.providers.doubao:create_doubao_provider
    DOUBAO_ARK_API_KEY=<your-ark-api-key>            # required, never commit
    DOUBAO_ARK_MODEL=<model-id-or-endpoint-id>       # required
    DOUBAO_ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3  # optional
    DOUBAO_ARK_TIMEOUT_SECONDS=30                    # optional
    DOUBAO_ARK_MAX_TOKENS=1024                       # optional

Security boundaries (do not change without PO approval):

* The provider NEVER touches the database, never creates/updates a Question or
  an intake, never reviews or publishes content. It only returns candidates for
  an administrator to inspect.
* No API key, token, Authorization header or full request body is written to
  logs, exceptions or test fixtures.
* All exceptions raised here are safe to surface: they carry a category and a
  short reason, never secrets.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from typing import Any

from pydantic import ValidationError

from api.recognition import RecognitionCandidate

logger = logging.getLogger(__name__)

# MIME types accepted by the upstream upload pipeline (PNG/JPEG/WebP). We keep
# this in lockstep with the intake validation in api/main.py without importing
# it (this module must stay independent of the FastAPI app).
_ALLOWED_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_TOKENS = 1024
_MAX_BODY_BYTES = 64 * 1024 * 1024  # Ark hard limit per request body (64 MB)

# The prompt is intentionally constrained: the model must return ONLY a JSON
# array (no prose, no markdown fences we cannot strip). Each element maps to the
# RecognitionCandidate fields. We explicitly ask for uncertainty to be carried
# into confidence_note rather than invented as certainty.
_PROMPT = (
    "你是经济学考研题目识别助手。请识别这张题目截图中的题目，"
    "并严格只输出一个 JSON 数组（不要输出解释、不要输出 markdown 代码块围栏）。"
    "数组每个元素是一道题，字段如下：\n"
    "- stem: string，题干原文（必填，不得为空）\n"
    "- subject: string，所属科目，不确定留空字符串\n"
    "- difficulty: integer 或 null，难度 1-5（1 最易，5 最难），不确定用 null\n"
    "- answer: string，参考答案，不确定留空字符串\n"
    "- analysis: string，解析，不确定留空字符串\n"
    "- question_type: string，题型（如 名词解释/简答题/计算题/论述题/图形分析题），不确定留空字符串\n"
    "- confidence_note: string，识别置信度或不确定说明（例如“题干清晰，但答案被截断需人工核对”）\n"
    "要求：如果图片中没有清晰可读的题目，返回空数组 []。"
    "不要编造图片中不存在的内容。"
)


class DoubaoProviderError(Exception):
    """Base class for all provider-raised errors. Safe to surface; never contains the API key."""


class DoubaoProviderConfigError(DoubaoProviderError):
    """Raised when required environment variables are missing or invalid."""


class DoubaoProviderInputError(DoubaoProviderError):
    """Raised for empty images or unsupported MIME types before any network call."""


class DoubaoProviderAuthError(DoubaoProviderError):
    """Raised on HTTP 401/403 (bad/missing API key or model not enabled)."""


class DoubaoProviderRateLimitError(DoubaoProviderError):
    """Raised on HTTP 429."""


class DoubaoProviderUpstreamError(DoubaoProviderError):
    """Raised on HTTP 5xx from Ark."""


class DoubaoProviderTimeoutError(DoubaoProviderError):
    """Raised on connect/read timeout."""


class DoubaoProviderNetworkError(DoubaoProviderError):
    """Raised on other transport-level failures (DNS, connection reset, etc.)."""


class DoubaoProviderResponseError(DoubaoProviderError):
    """Raised when the HTTP response is not valid JSON or does not match the expected shape."""


class DoubaoVisionRecognitionProvider:
    """Concrete RecognitionProvider backed by the Volcengine Ark Chat API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        if not api_key:
            raise DoubaoProviderConfigError("DOUBAO_ARK_API_KEY is required")
        if not model:
            raise DoubaoProviderConfigError("DOUBAO_ARK_MODEL is required")
        if timeout_seconds <= 0:
            raise DoubaoProviderConfigError("timeout must be > 0")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout_seconds)
        self._max_tokens = int(max_tokens)

    # ------------------------------------------------------------------ public
    def recognize(self, image_bytes: bytes, mime_type: str) -> list[RecognitionCandidate]:
        if not image_bytes:
            raise DoubaoProviderInputError("image_bytes must not be empty")
        normalized_mime = (mime_type or "").strip().lower()
        if normalized_mime not in _ALLOWED_MIME_TYPES:
            raise DoubaoProviderInputError(
                f"unsupported mime_type: {mime_type!r}; allowed: {sorted(_ALLOWED_MIME_TYPES)}"
            )

        data_url = self._build_data_url(image_bytes, normalized_mime)
        body = self._build_request_body(data_url)
        raw = self._post(body)
        return self._parse_response(raw)

    # -------------------------------------------------------------- internal
    @staticmethod
    def _build_data_url(image_bytes: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _build_request_body(self, data_url: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
            "max_tokens": self._max_tokens,
        }

    def _post(self, body: dict[str, Any]) -> bytes:
        url = f"{self._base_url}/chat/completions"
        data = json.dumps(body).encode("utf-8")
        if len(data) > _MAX_BODY_BYTES:
            raise DoubaoProviderInputError(
                f"encoded request body exceeds {_MAX_BODY_BYTES} bytes"
            )
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            self._map_http_error(exc)
        except urllib.error.URLError as exc:
            self._map_url_error(exc)
        except socket.timeout as exc:  # defensive; usually wrapped by URLError
            raise DoubaoProviderTimeoutError(f"request timed out after {self._timeout}s") from exc
        # Unreachable in practice, but keeps type checkers honest.
        raise DoubaoProviderNetworkError("unknown transport failure")

    def _map_http_error(self, exc: urllib.error.HTTPError) -> None:
        code = exc.code
        # We deliberately do NOT include exc.read() payload here: upstream error
        # bodies can echo request snippets or internal ids, and the operator
        # already has the HTTP status to correlate logs.
        if code in (401, 403):
            raise DoubaoProviderAuthError(f"ark auth failed with HTTP {code}") from exc
        if code == 429:
            raise DoubaoProviderRateLimitError("ark rate limited (HTTP 429)") from exc
        if 500 <= code < 600:
            raise DoubaoProviderUpstreamError(f"ark upstream error HTTP {code}") from exc
        # Other 4xx (e.g. 400 bad request, 404 model not found) are surfaced as a
        # response/configuration error without leaking the body.
        raise DoubaoProviderResponseError(f"ark rejected request with HTTP {code}") from exc

    @staticmethod
    def _map_url_error(exc: urllib.error.URLError) -> None:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            raise DoubaoProviderTimeoutError("request timed out") from exc
        reason_text = str(reason).lower()
        if "timed out" in reason_text:
            raise DoubaoProviderTimeoutError("request timed out") from exc
        raise DoubaoProviderNetworkError(f"network error: {type(reason).__name__}") from exc

    def _parse_response(self, raw: bytes) -> list[RecognitionCandidate]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise DoubaoProviderResponseError("upstream returned non-JSON response") from exc

        try:
            content_text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DoubaoProviderResponseError("upstream response missing choices[0].message.content") from exc
        if not isinstance(content_text, str):
            raise DoubaoProviderResponseError("upstream content is not a string")

        items = self._extract_json_array(content_text)
        candidates: list[RecognitionCandidate] = []
        skipped = 0
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            try:
                candidates.append(self._build_candidate(item))
            except ValidationError:
                skipped += 1
        if skipped:
            logger.warning("doubao provider dropped %d malformed candidate(s)", skipped)
        return candidates

    @staticmethod
    def _extract_json_array(text: str) -> list[Any]:
        text = text.strip()
        # Tolerate ```json ... ``` fences even though the prompt forbids them.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            parsed = json.loads(text)
        except ValueError:
            # Fall back: grab the outermost [ ... ] span.
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end <= start:
                raise DoubaoProviderResponseError("upstream content is not a JSON array")
            try:
                parsed = json.loads(text[start : end + 1])
            except ValueError as exc:
                raise DoubaoProviderResponseError("upstream content is not a JSON array") from exc
        if not isinstance(parsed, list):
            raise DoubaoProviderResponseError("upstream content is not a JSON array")
        return parsed

    @staticmethod
    def _build_candidate(item: dict[str, Any]) -> RecognitionCandidate:
        # Coerce raw model output into the strict RecognitionCandidate shape.
        # Pydantic validation rejects empty stem and out-of-range difficulty.
        allowed = {
            "stem": item.get("stem", ""),
            "subject": item.get("subject", "") or "",
            "difficulty": item.get("difficulty"),
            "answer": item.get("answer", "") or "",
            "analysis": item.get("analysis", "") or "",
            "question_type": item.get("question_type", "") or "",
            "confidence_note": item.get("confidence_note", "") or "",
        }
        # Ensure string fields are strings (model sometimes returns numbers).
        for key in ("stem", "subject", "answer", "analysis", "question_type", "confidence_note"):
            if not isinstance(allowed[key], str):
                allowed[key] = str(allowed[key])
        if allowed["difficulty"] is not None:
            try:
                allowed["difficulty"] = int(allowed["difficulty"])
            except (TypeError, ValueError):
                allowed["difficulty"] = None
        return RecognitionCandidate(**allowed)


def create_doubao_provider() -> DoubaoVisionRecognitionProvider:
    """Factory used by ``ECON_RECOGNITION_PROVIDER=api.providers.doubao:create_doubao_provider``.

    Reads configuration from the process environment. Raises
    ``DoubaoProviderConfigError`` when required variables are missing so the
    backend can surface a clear "provider not configured" state instead of
    sending an unauthenticated request.
    """
    api_key = os.environ.get("DOUBAO_ARK_API_KEY", "").strip()
    model = os.environ.get("DOUBAO_ARK_MODEL", "").strip()
    base_url = os.environ.get("DOUBAO_ARK_BASE_URL", "").strip() or _DEFAULT_BASE_URL
    timeout_raw = os.environ.get("DOUBAO_ARK_TIMEOUT_SECONDS", "").strip()
    max_tokens_raw = os.environ.get("DOUBAO_ARK_MAX_TOKENS", "").strip()

    if not api_key:
        raise DoubaoProviderConfigError("missing DOUBAO_ARK_API_KEY")
    if not model:
        raise DoubaoProviderConfigError("missing DOUBAO_ARK_MODEL")

    timeout = _DEFAULT_TIMEOUT_SECONDS
    if timeout_raw:
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise DoubaoProviderConfigError("DOUBAO_ARK_TIMEOUT_SECONDS must be a number") from exc

    max_tokens = _DEFAULT_MAX_TOKENS
    if max_tokens_raw:
        try:
            max_tokens = int(max_tokens_raw)
        except ValueError as exc:
            raise DoubaoProviderConfigError("DOUBAO_ARK_MAX_TOKENS must be an integer") from exc

    logger.info(
        "doubao provider configured (model=%s, base_url=%s, timeout=%.1fs)",
        model,
        base_url,
        timeout,
    )
    return DoubaoVisionRecognitionProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout,
        max_tokens=max_tokens,
    )
