"""Stable V0.1 JSON contract and pure validation helpers."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "0.1"
SOURCE_TYPES = {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM", "CURATED_EXERCISE", "AI_GENERATED"}
ANSWER_KINDS = {"NONE", "REFERENCE", "OFFICIAL", "UNKNOWN"}


def canonical_digest(value: dict[str, Any]) -> str:
    clean = {key: val for key, val in value.items() if key != "validation"}
    return hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def stem_fingerprint(stem: str) -> str:
    normalized = unicodedata.normalize("NFKC", stem).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_item(item: dict[str, Any], batch_dir: Path, con=None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = [warning for warning in item.get("validation", {}).get("warnings", [])
                           if not warning.startswith(("疑似重复题：", "疑似本批重复题："))]
    required = {"schema_version", "item_key", "source", "exam_scope", "content", "source_answer",
                "ai_answer", "classification", "validation", "processing_meta"}
    if not required <= item.keys():
        return ["缺少字段：" + ", ".join(sorted(required - item.keys()))], warnings
    if item["schema_version"] != SCHEMA_VERSION:
        errors.append("不支持的 schema_version")
    source, scope, content = item["source"], item["exam_scope"], item["content"]
    answer, ai, classification = item["source_answer"], item["ai_answer"], item["classification"]
    if source.get("kind") not in SOURCE_TYPES:
        errors.append("无效来源类型")
    if not source.get("name") or not source.get("file_name") or not source.get("file_sha256"):
        errors.append("来源名称、文件名或哈希缺失")
    if not item.get("item_key") or not isinstance(item["item_key"], str):
        errors.append("单题 item_key 缺失")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("file_sha256", ""))):
        errors.append("来源文件 SHA-256 格式无效")
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.is_file():
        errors.append("批次 manifest.json 缺失")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if source.get("file_sha256") != manifest.get("source_sha256") or source.get("file_name") != manifest.get("source_file"):
                errors.append("单题来源文件与批次 manifest 不一致")
            source_asset = "assets/source-" + str(source.get("file_sha256")) + ".pdf"
            if manifest.get("source_asset") != source_asset or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("file_sha256", ""))):
                errors.append("原始 PDF 资源位置无效")
            elif not (batch_dir / source_asset).is_file() or hashlib.sha256((batch_dir / source_asset).read_bytes()).hexdigest() != source.get("file_sha256"):
                errors.append("原始 PDF 缺失或哈希不匹配")
        except (OSError, ValueError):
            errors.append("批次 manifest 无效")
    if source.get("is_demo"):
        errors.append("演示资料不得导入正式题库")
    if source.get("kind") in {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM"}:
        url = urlparse(source.get("url") or "")
        if not source.get("exam_year") or url.scheme != "https" or not url.hostname:
            errors.append("真题必须填写年份和 HTTPS 来源链接")
    if not scope.get("target_id"):
        errors.append("适用考试标签待确认")
    if not isinstance(source.get("pages"), list) or not source["pages"] or any(
        type(page) is not int or page < 1 for page in source["pages"]
    ):
        errors.append("来源页码无效")
    if not content.get("stem_latex") or len(content["stem_latex"].strip()) < 5:
        errors.append("题干缺失或过短")
    if answer.get("kind") not in ANSWER_KINDS:
        errors.append("来源答案类型无效")
    if answer.get("status") not in {"ABSENT", "PRESENT"}:
        errors.append("来源答案状态无效")
    evidence = answer.get("evidence") or []
    valid_evidence = any(
        isinstance(entry, dict) and entry.get("file_sha256") == source.get("file_sha256")
        and type(entry.get("page")) is int and entry["page"] > 0 and entry.get("note", "").strip()
        for entry in evidence
    )
    if answer.get("kind") == "OFFICIAL" and (not valid_evidence or not answer.get("human_verified")):
        errors.append("官方答案必须有明确证据并经人工确认")
    if answer.get("status") == "ABSENT" and answer.get("text"):
        errors.append("无来源答案状态不得含答案文字")
    if answer.get("status") == "PRESENT" and not answer.get("text"):
        errors.append("来源答案标记存在但正文为空")
    if answer.get("kind") == "NONE" and answer.get("text"):
        errors.append("来源答案类型 NONE 不得含答案文字")
    if ai.get("status") != "SUCCEEDED" or not ai.get("answer") or not ai.get("analysis"):
        errors.append("真实 AI 答案尚未成功生成，保持待处理")
    successful_runs = [run for run in item.get("processing_meta", {}).get("model_runs", [])
                       if isinstance(run, dict) and run.get("task") == "answer_generation"
                       and run.get("provider") == ai.get("provider") and run.get("model")
                       and not run.get("error") and run.get("provider") != "mock"]
    if ai.get("status") == "SUCCEEDED" and not successful_runs:
        errors.append("AI 答案缺少非 Mock 模型调用记录")
    if not classification.get("topic_id"):
        errors.append("主知识点待确认")
    if not classification.get("question_type"):
        errors.append("题型待确认")
    if type(classification.get("difficulty")) is not int or not 1 <= classification["difficulty"] <= 5:
        errors.append("难度须为 1–5")
    for asset in content.get("assets", []):
        relative = asset.get("path", "")
        path = (batch_dir / relative).resolve()
        if not relative.startswith("assets/") or not path.is_relative_to((batch_dir / "assets").resolve()) or not path.is_file():
            errors.append("图片资源缺失或路径无效：" + relative)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != asset.get("sha256"):
            errors.append("图片资源哈希不匹配：" + relative)
    if con is not None:
        target_id, topic_id = scope.get("target_id"), classification.get("topic_id")
        if target_id and not con.execute("SELECT 1 FROM targets WHERE id=?", (target_id,)).fetchone():
            errors.append("考试标签在数据库中不存在")
        if topic_id and not con.execute("SELECT 1 FROM topics WHERE id=?", (topic_id,)).fetchone():
            errors.append("主知识点在数据库中不存在")
        if target_id and topic_id and not con.execute(
            "SELECT 1 FROM topic_target_tags WHERE topic_id=? AND target_id=?", (topic_id, target_id)
        ).fetchone():
            errors.append("主知识点未绑定该考试标签")
        fingerprint = stem_fingerprint(content.get("stem_latex", ""))
        for row in con.execute("SELECT id,stem FROM questions"):
            if stem_fingerprint(row["stem"]) == fingerprint:
                warnings.append("疑似重复题：" + row["id"])
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))
