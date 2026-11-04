"""Small task adapters. The existing image RecognitionProvider remains unchanged."""

from __future__ import annotations

import json
import math
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from .contract import QUESTION_TYPES

class ModelError(RuntimeError):
    """Safe, credential-free model failure."""


class MockTasks:
    """Explicit test fixture. Mock answers must never be mistaken for real AI output."""

    def __init__(self):
        self.provider_id = "mock"
        self.runs: list[dict[str, Any]] = []

    def structure(self, text: str) -> list[dict[str, str]]:
        return [{"stem": text, "question_type": ""}] if text.strip() else []

    def answer(self, stem: str) -> dict[str, str]:
        self.runs.append({"task": "answer_generation", "provider": "mock", "model": "fixture",
                          "duration_ms": 0, "attempts": 1, "input_tokens": 0,
                          "output_tokens": 0, "estimated_cost": None, "currency": None, "error": None})
        return {"answer": "MOCK：仅用于测试，不是经济学答案。", "analysis": "测试占位，禁止当作真实模型结果。"}

    def recommend(self, stem: str, topics: list[dict[str, str]]) -> dict[str, Any]:
        return {"topic_id": None, "question_type": None, "difficulty": None}

    def vision(self, image_bytes: bytes, mime_type: str) -> list[dict[str, Any]]:
        return []


class DisabledTasks:
    """No credential/no permission: leave each item pending instead of inventing output."""

    def __init__(self):
        self.runs: list[dict[str, Any]] = []

    def structure(self, text: str) -> list[dict[str, str]]:
        raise ModelError("structure model is not enabled")

    def answer(self, stem: str) -> dict[str, str]:
        raise ModelError("answer model is not enabled")

    def recommend(self, stem: str, topics: list[dict[str, str]]) -> dict[str, Any]:
        raise ModelError("tag model is not enabled")

    def vision(self, image_bytes: bytes, mime_type: str) -> list[dict[str, Any]]:
        raise ModelError("vision model is not enabled")


class _TextTasks:
    """Shared chat-completions transport; business task outputs stay provider-neutral."""

    def __init__(self, prefix: str, provider_id: str, default_url: str, *, json_mode: bool = False):
        self.prefix = prefix
        self.provider_id = provider_id
        self.json_mode = json_mode
        self.key = os.environ.get(prefix + "_API_KEY", "").strip()
        self.model = os.environ.get(prefix + "_MODEL", "").strip()
        self.base_url = os.environ.get(prefix + "_BASE_URL", default_url).rstrip("/")
        if not self.key or not self.model:
            raise ModelError(prefix + "_API_KEY and " + prefix + "_MODEL are required")
        if not self.base_url.startswith("https://"):
            raise ModelError(prefix + "_BASE_URL must use HTTPS")
        try:
            self.timeout = float(os.environ.get(prefix + "_TIMEOUT_SECONDS", "30"))
            self.retries = min(3, max(0, int(os.environ.get(prefix + "_RETRIES", "2"))))
        except ValueError as exc:
            raise ModelError(prefix + " timeout/retries configuration is invalid") from exc
        if self.timeout <= 0:
            raise ModelError(prefix + "_TIMEOUT_SECONDS must be positive")
        self.runs: list[dict[str, Any]] = []

    def _call(self, task: str, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 4000 if task == "answer_generation" else 2000,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
        )
        started = time.monotonic()
        last_error = ""
        input_tokens = None
        output_tokens = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                usage = payload.get("usage") or {}
                input_tokens = usage.get("prompt_tokens")
                output_tokens = usage.get("completion_tokens")
                choice = payload["choices"][0]
                if choice.get("finish_reason") == "length":
                    last_error = "OUTPUT_TRUNCATED"
                    break
                content = choice["message"]["content"]
                if not isinstance(content, str):
                    raise ModelError("model content is not text")
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                result = json.loads(cleaned)
                if not isinstance(result, dict):
                    raise ModelError("model output is not a JSON object")
                if task == "answer_generation" and (
                    not isinstance(result.get("answer"), str) or not result["answer"].strip()
                    or not isinstance(result.get("analysis"), str)
                ):
                    raise ModelError("answer result is incomplete")
                cost = self._cost(input_tokens, output_tokens)
                self.runs.append({"task": task, "provider": self.provider_id, "model": self.model,
                                  "duration_ms": round((time.monotonic() - started) * 1000),
                                  "attempts": attempt + 1, "input_tokens": input_tokens,
                                  "output_tokens": output_tokens, "estimated_cost": cost,
                                  "currency": os.environ.get(self.prefix + "_PRICE_CURRENCY") if cost is not None else None,
                                  "error": None})
                return result
            except urllib.error.HTTPError as exc:
                last_error = "HTTP_" + str(exc.code)
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError):
                last_error = "NETWORK_OR_TIMEOUT"
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, ModelError):
                last_error = "INVALID_STRUCTURED_RESPONSE"
                break
            if attempt < self.retries:
                time.sleep(min(4, 2 ** attempt))
        cost = self._cost(input_tokens, output_tokens)
        self.runs.append({"task": task, "provider": self.provider_id, "model": self.model,
                          "duration_ms": round((time.monotonic() - started) * 1000),
                          "attempts": attempt + 1, "input_tokens": input_tokens, "output_tokens": output_tokens,
                          "estimated_cost": cost,
                          "currency": os.environ.get(self.prefix + "_PRICE_CURRENCY") if cost is not None else None,
                          "error": last_error})
        raise ModelError(task + " failed: " + last_error)

    def _cost(self, input_tokens: Any, output_tokens: Any) -> float | None:
        try:
            input_rate = float(os.environ[self.prefix + "_INPUT_PRICE_PER_MILLION"])
            output_rate = float(os.environ[self.prefix + "_OUTPUT_PRICE_PER_MILLION"])
            if not os.environ.get(self.prefix + "_PRICE_CURRENCY") or not all(
                math.isfinite(rate) and rate >= 0 for rate in (input_rate, output_rate)
            ):
                return None
            return round((int(input_tokens) * input_rate + int(output_tokens) * output_rate) / 1_000_000, 8)
        except (KeyError, TypeError, ValueError):
            return None

    def structure(self, text: str) -> list[dict[str, str]]:
        result = self._call("question_structuring", "将以下经济学题目文本拆为独立题目及小问。只输出 JSON 对象 {\"questions\":[{\"stem\":\"...\",\"question_type\":\"...\"}]}；不编造缺失文字。\n" + text[:20000])
        questions = result.get("questions")
        if not isinstance(questions, list):
            raise ModelError("structure result missing questions")
        return [q for q in questions if isinstance(q, dict) and isinstance(q.get("stem"), str) and q["stem"].strip()]

    def answer(self, stem: str) -> dict[str, str]:
        prompt = ("你是初级和中级宏微观经济学解题助手，参考高鸿业、曼昆、布兰查德、平新乔、范里安、尼克尔森的通行理论。"
                  "仅输出 JSON 对象 {\"answer\":\"...\",\"analysis\":\"...\"}。不确定时明确写出不确定性，不冒充官方答案。\n题目：" + stem[:16000])
        result = self._call("answer_generation", prompt)
        return {"answer": result["answer"].strip(), "analysis": result["analysis"].strip()}

    def recommend(self, stem: str, topics: list[dict[str, str]]) -> dict[str, Any]:
        prompt = ("从给定知识点中推荐且只推荐一个最匹配 ID，一次返回 topic_id、question_type、difficulty。"
                  "题型只允许名词解释、选择/填空、简答题、论述题、计算题；难度须重新评估为 1-5。"
                  "不确定的字段为 null，不得照搬未核验的历史默认难度。"
                  "仅输出 JSON 对象 {\"topic_id\":null,\"question_type\":null,\"difficulty\":null}。\n知识点："
                  + json.dumps(topics[:200], ensure_ascii=False) + "\n题目：" + stem[:12000])
        result = self._call("tag_recommendation", prompt)
        allowed = {topic["id"] for topic in topics}
        topic_id = result.get("topic_id")
        difficulty = result.get("difficulty")
        return {"topic_id": topic_id if topic_id in allowed else None,
                "question_type": result.get("question_type") if result.get("question_type") in QUESTION_TYPES else None,
                "difficulty": difficulty if type(difficulty) is int and 1 <= difficulty <= 5 else None}

    def vision(self, image_bytes: bytes, mime_type: str) -> list[dict[str, Any]]:
        from api.recognition import configured_provider

        provider = configured_provider()
        if provider is None:
            raise ModelError("ECON_RECOGNITION_PROVIDER is required for scanned pages")
        started = time.monotonic()
        try:
            results = [candidate.model_dump() for candidate in provider.recognize(image_bytes, mime_type)]
        except Exception as exc:
            raise ModelError("vision recognition failed: " + type(exc).__name__) from exc
        self.runs.append({"task": "vision_recognition", "provider": "configured-recognition",
                          "model": self.model, "duration_ms": round((time.monotonic() - started) * 1000),
                          "attempts": 1, "input_tokens": None, "output_tokens": None,
                          "estimated_cost": None, "currency": None, "error": None})
        return results


class DoubaoTasks(_TextTasks):
    """Ark text tasks and the existing configured RecognitionProvider for vision."""

    def __init__(self):
        super().__init__("DOUBAO_ARK", "doubao-ark", "https://ark.cn-beijing.volces.com/api/v3")


class DeepSeekTasks(_TextTasks):
    """Text-only DeepSeek adapter; no vision or question-splitting capability."""

    def __init__(self):
        super().__init__("DEEPSEEK", "deepseek", "https://api.deepseek.com", json_mode=True)

    def structure(self, text: str) -> list[dict[str, str]]:
        raise ModelError("DeepSeek question structuring is not enabled")

    def vision(self, image_bytes: bytes, mime_type: str) -> list[dict[str, Any]]:
        raise ModelError("DeepSeek vision is not supported")


def make_tasks(provider: str, allow_model_call: bool = False):
    if provider == "mock":
        return MockTasks()
    if provider == "none":
        return DisabledTasks()
    if provider == "doubao" and allow_model_call:
        return DoubaoTasks()
    if provider == "deepseek" and allow_model_call:
        return DeepSeekTasks()
    if provider in ("doubao", "deepseek"):
        return DisabledTasks()
    raise ValueError("provider must be none, mock, doubao, or deepseek")
