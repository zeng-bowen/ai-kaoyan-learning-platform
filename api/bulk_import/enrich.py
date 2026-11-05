"""Resumable, text-only enhancement of an existing legacy JSONL batch.

The source batch and SQLite are read only. Every task result is checkpointed in
an independent item file before the next paid call starts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ai import ModelError, make_tasks
from .contract import QUESTION_TYPES, stem_fingerprint
from .db import list_topics
from .storage import atomic_json, read_items, read_json, write_items

ELIGIBLE_STATES = {"READY", "NORMALIZE_ONLY", "NEED_AI_ANSWER", "NEED_TAGGING"}
BLOCKED_STATES = {"NEED_VISION", "NEED_SPLIT", "NEED_AI_SPLIT", "MANUAL_REVIEW",
                  "INCOMPLETE_SOURCE", "SECTION_HEADING_ONLY"}
JSON_ERRORS = {"INVALID_STRUCTURED_RESPONSE", "OUTPUT_TRUNCATED"}
MODEL_NAME = "deepseek-flash"


def _eligible(item: dict) -> bool:
    meta = item.get("processing_meta", {})
    source = item.get("source", {})
    content = item.get("content", {})
    return (meta.get("legacy_gate") == "READY_FOR_ENRICHMENT"
            and meta.get("legacy_status") in ELIGIBLE_STATES
            and meta.get("legacy_reason") not in BLOCKED_STATES
            and not content.get("assets") and bool(content.get("stem_latex", "").strip())
            and bool(source.get("name") and source.get("file_sha256") and source.get("pages")
                     and source.get("exam_year") and item.get("exam_scope", {}).get("target_id")))


def _source_digest(source_batch: Path) -> str:
    return hashlib.sha256((source_batch / "questions.jsonl").read_bytes()).hexdigest()


def _load_source(source_batch: Path) -> list[dict]:
    items = read_items(source_batch)
    keys = [item["item_key"] for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("来源批次 item_key 重复")
    return [item for item in items if _eligible(item)]


def _item_path(out: Path, item_key: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", item_key):
        raise ValueError("不安全的 item_key")
    return out / "items" / (item_key + ".json")


def _task_state(item: dict, task: str) -> dict:
    return item["processing_meta"]["enrichment"][task]


def _create_output(source_batch: Path, out: Path, model: str, selected: list[dict]) -> None:
    source_root = source_batch.resolve()
    out_root = out.resolve()
    if out_root == source_root or source_root in out_root.parents or out_root in source_root.parents:
        raise ValueError("增强输出目录必须与原始批次分离")
    digest = _source_digest(source_batch)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if (manifest.get("input_digest") != digest or manifest.get("source_batch") != str(source_root)
                or manifest.get("provider") != "deepseek" or manifest.get("model") != model):
            raise ValueError("现有批次来源、Provider 或模型不匹配；禁止覆盖")
        return
    if out.exists() and any(out.iterdir()):
        raise ValueError("输出目录非空且无匹配 manifest；禁止覆盖")
    (out / "items").mkdir(parents=True, exist_ok=True)
    atomic_json(manifest_path, {"schema_version": "legacy-enrichment-0.1",
                                "source_batch": str(source_root), "input_digest": digest,
                                "provider": "deepseek", "model": model,
                                "eligible": len(selected), "created_at": datetime.now(timezone.utc).isoformat(),
                                "formal_database_write": False})
    for item in selected:
        entry = copy.deepcopy(item)
        entry["processing_meta"]["legacy_classification"] = copy.deepcopy(entry["classification"])
        entry["processing_meta"]["enrichment"] = {
            "answer_generation": {"status": "PENDING", "calls": 0, "error": None},
            "tag_recommendation": {"status": "PENDING", "calls": 0, "error": None}}
        atomic_json(_item_path(out, entry["item_key"]), entry)
    _snapshot(out, selected)


def plan(source_batch: Path, out: Path, db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError("指定 SQLite 不存在")
    selected = _load_source(source_batch)
    topic_counts = {target: len(list_topics(db_path, target)) for target in
                    {item["exam_scope"]["target_id"] for item in selected}}
    if any(count == 0 for count in topic_counts.values()):
        raise ValueError("考试标签缺少已绑定知识点；禁止调用模型")
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest.get("input_digest") != _source_digest(source_batch):
            raise ValueError("来源 JSONL 已变动；禁止沿用旧检查点")
        if manifest.get("provider") != "deepseek":
            raise ValueError("现有批次不是 DeepSeek")
        pending_answer = pending_tag = 0
        for item in selected:
            path = _item_path(out, item["item_key"])
            if not path.is_file():
                raise ValueError("现有批次缺少检查点：" + item["item_key"])
            saved = read_json(path)
            pending_answer += _task_state(saved, "answer_generation")["status"] != "SUCCEEDED"
            pending_tag += _task_state(saved, "tag_recommendation")["status"] != "SUCCEEDED"
    else:
        pending_answer = sum(item["ai_answer"].get("status") != "SUCCEEDED" for item in selected)
        pending_tag = len(selected)
    return {"source_total": len(read_items(source_batch)), "eligible": len(selected),
            "excluded": len(read_items(source_batch)) - len(selected),
            "answer_calls_pending": pending_answer, "tag_calls_pending": pending_tag,
            "topic_counts": topic_counts, "provider": "deepseek", "model": MODEL_NAME,
            "input_digest": _source_digest(source_batch), "model_call": False}


def _assignments(text: str) -> dict[str, set[str]]:
    compact = text.replace("$", "").replace("\\(", "").replace("\\)", "")
    found: dict[str, set[str]] = defaultdict(set)
    for match in re.finditer(r"(?<![A-Za-z])([A-Za-z][A-Za-z0-9_]{0,3})\s*=\s*(-?\d+(?:\.\d+)?)", compact):
        found[match.group(1).upper()].add(match.group(2))
    return found


def _answer_comparison(item: dict) -> str:
    source = item["source_answer"].get("text", "")
    answer = item["ai_answer"].get("answer", "")
    if not source or not answer:
        return "NOT_COMPARABLE"
    left, right = _assignments(source), _assignments(answer)
    comparable = set(left) & set(right)
    if any(len(left[key]) == len(right[key]) == 1 and left[key] != right[key]
           for key in comparable):
        return "POTENTIAL_CONFLICT"
    if comparable and all(left[key] == right[key] for key in comparable):
        return "NUMERIC_AGREEMENT"
    if re.sub(r"\s+", "", source) == re.sub(r"\s+", "", answer):
        return "TEXT_AGREEMENT"
    return "UNDETERMINED"


def _warning(item: dict, message: str) -> None:
    warnings = item["validation"].setdefault("warnings", [])
    if message not in warnings:
        warnings.append(message)


def _run_task(item: dict, task_name: str, tasks, topics: list[dict], out: Path) -> bool:
    state = _task_state(item, task_name)
    if state["status"] == "SUCCEEDED":
        return False
    for directed_retry in range(3):
        state["status"] = "RUNNING"
        atomic_json(_item_path(out, item["item_key"]), item)
        before = len(tasks.runs)
        try:
            if task_name == "answer_generation":
                result = tasks.answer(item["content"]["stem_latex"])
                item["ai_answer"] = {"status": "SUCCEEDED", "answer": result["answer"],
                                     "analysis": result["analysis"], "provider": tasks.provider_id}
                comparison = _answer_comparison(item)
                item["processing_meta"]["answer_comparison"] = comparison
                if comparison == "POTENTIAL_CONFLICT":
                    _warning(item, "ANSWER_CONFLICT：来源与 AI 数值结果可能不一致，需人工核对原件")
            else:
                result = tasks.recommend(item["content"]["stem_latex"], topics)
                item["classification"] = {
                    "topic_id": result["topic_id"], "question_type": result["question_type"],
                    "difficulty": result["difficulty"]}
                if any(value is None for value in item["classification"].values()):
                    _warning(item, "AI 标签不确定，留空待人工确认")
            state.update({"status": "SUCCEEDED", "error": None})
        except ModelError as exc:
            error = tasks.runs[-1]["error"] if len(tasks.runs) > before else str(exc)
            state.update({"status": "ERROR", "error": error})
            if task_name == "answer_generation":
                item["ai_answer"] = {"status": "PENDING", "answer": "", "analysis": "",
                                     "provider": None, "error": error}
            _warning(item, task_name + " 失败：" + error)
        finally:
            new_runs = tasks.runs[before:]
            state["calls"] += len(new_runs)
            item["processing_meta"].setdefault("model_runs", []).extend(new_runs)
            atomic_json(_item_path(out, item["item_key"]), item)
        if state["status"] == "SUCCEEDED":
            return False
        if state["error"] in {"HTTP_401", "HTTP_403"}:
            return True
        if state["error"] not in JSON_ERRORS or directed_retry == 2:
            return False
    return False


def _snapshot(out: Path, selected: list[dict]) -> list[dict]:
    items = [read_json(_item_path(out, source["item_key"])) for source in selected]
    write_items(out, items)
    progress = {item["item_key"]: item["processing_meta"]["enrichment"] for item in items}
    atomic_json(out / "progress.json", {"schema_version": "legacy-enrichment-0.1", "items": progress})
    return items


def run(source_batch: Path, out: Path, db_path: Path, *, allow_model_call: bool = False) -> dict:
    initial = plan(source_batch, out, db_path)
    if not allow_model_call:
        raise ModelError("真实批量调用需要 --allow-model-call")
    tasks = make_tasks("deepseek", True)
    if tasks.model != MODEL_NAME:
        raise ModelError("DEEPSEEK_MODEL 必须为已批准的 deepseek-flash")
    selected = _load_source(source_batch)
    _create_output(source_batch, out, tasks.model, selected)
    topics_by_target = {target: list_topics(db_path, target) for target in
                        {item["exam_scope"]["target_id"] for item in selected}}
    print(json.dumps({"preflight": initial}, ensure_ascii=False), flush=True)
    for index, source in enumerate(selected, 1):
        item = read_json(_item_path(out, source["item_key"]))
        target_topics = topics_by_target[item["exam_scope"]["target_id"]]
        halted = False
        for task_name in ("answer_generation", "tag_recommendation"):
            halted = _run_task(item, task_name, tasks, target_topics, out)
            if halted:
                break
        _snapshot(out, selected)
        states = item["processing_meta"]["enrichment"]
        print(json.dumps({"index": index, "eligible": len(selected), "item_key": item["item_key"],
                          "answer": states["answer_generation"]["status"],
                          "tag": states["tag_recommendation"]["status"],
                          "halted_auth": halted}, ensure_ascii=False), flush=True)
        if halted:
            raise ModelError("401/403 凭证或权限失败，批次已停止；已保存单题检查点")
    return summarize(out)


def summarize(out: Path) -> dict:
    items = read_items(out)
    runs = [run for item in items for run in item["processing_meta"].get("model_runs", [])]
    success = [run for run in runs if not run.get("error")]
    answers = [run for run in success if run["task"] == "answer_generation"]
    tags = [run for run in success if run["task"] == "tag_recommendation"]
    states = [(item["processing_meta"]["enrichment"]["answer_generation"]["status"],
               item["processing_meta"]["enrichment"]["tag_recommendation"]["status"]) for item in items]
    errors = Counter(run.get("error") for run in runs if run.get("error"))
    fingerprints = Counter(stem_fingerprint(item["content"]["stem_latex"]) for item in items)
    def json_retries(item: dict, task: str) -> int:
        task_runs = [run for run in item["processing_meta"].get("model_runs", []) if run.get("task") == task]
        return sum(run.get("error") in JSON_ERRORS for run in task_runs[:-1])
    summary = {
        "eligible": len(items), "answer_success": sum(a == "SUCCEEDED" for a, _ in states),
        "answer_failed": sum(a == "ERROR" for a, _ in states),
        "tag_success": sum(t == "SUCCEEDED" for _, t in states),
        "tag_failed": sum(t == "ERROR" for _, t in states),
        "topic_null": sum(item["classification"]["topic_id"] is None for item in items),
        "question_type_null": sum(item["classification"]["question_type"] is None for item in items),
        "difficulty_null": sum(item["classification"]["difficulty"] is None for item in items),
        "answer_json_retries": sum(json_retries(item, "answer_generation") for item in items),
        "tag_json_retries": sum(json_retries(item, "tag_recommendation") for item in items),
        "error_categories": dict(errors),
        "extra_transport_attempts": sum(max(0, run.get("attempts", 1) - 1) for run in runs),
        "total_input_tokens_known": sum(run.get("input_tokens") or 0 for run in runs),
        "total_output_tokens_known": sum(run.get("output_tokens") or 0 for run in runs),
        "average_success_tokens_per_item": round(sum((run.get("input_tokens") or 0) +
                                                      (run.get("output_tokens") or 0) for run in success) / len(items), 2) if items else 0,
        "average_answer_duration_ms": round(sum(run["duration_ms"] for run in answers) / len(answers)) if answers else None,
        "average_tag_duration_ms": round(sum(run["duration_ms"] for run in tags) / len(tags)) if tags else None,
        "answer_conflict": sum(item["processing_meta"].get("answer_comparison") == "POTENTIAL_CONFLICT" for item in items),
        "answer_agreement_strong": sum(item["processing_meta"].get("answer_comparison") in
                                       {"NUMERIC_AGREEMENT", "TEXT_AGREEMENT"} for item in items),
        "duplicate_groups": sum(count > 1 for count in fingerprints.values()),
        "duplicate_members": sum(count for count in fingerprints.values() if count > 1),
        "estimated_cost": (round(sum(run["estimated_cost"] for run in runs), 8)
                           if runs and all(run.get("estimated_cost") is not None for run in runs) else None),
        "currency": next((run.get("currency") for run in runs if run.get("currency")), None),
        "formal_database_write": False,
    }
    atomic_json(out / "summary.json", summary)
    return summary


def review_sample(out: Path, limit: int = 30) -> list[dict]:
    items = [item for item in read_items(out) if item["ai_answer"]["status"] == "SUCCEEDED"
             and item["processing_meta"]["enrichment"]["tag_recommendation"]["status"] == "SUCCEEDED"]
    chosen: list[dict] = []
    seen: set[str] = set()
    def add(item: dict, reason: str) -> None:
        if len(chosen) < limit and item["item_key"] not in seen:
            seen.add(item["item_key"])
            chosen.append({"item_key": item["item_key"], "year": item["source"]["exam_year"],
                           "source_pages": item["source"]["pages"],
                           "stem_excerpt": item["content"]["stem_latex"][:80],
                           "topic_id": item["classification"]["topic_id"],
                           "question_type": item["classification"]["question_type"],
                           "difficulty": item["classification"]["difficulty"],
                           "answer_comparison": item["processing_meta"].get("answer_comparison"),
                           "retry_count": sum(max(0, run.get("attempts", 1) - 1) for run in
                                              item["processing_meta"]["model_runs"]) +
                                          sum(bool(run.get("error")) for run in item["processing_meta"]["model_runs"]),
                           "reason": reason})
    for comparison in ("POTENTIAL_CONFLICT", "NUMERIC_AGREEMENT", "TEXT_AGREEMENT"):
        for item in [item for item in items if item["processing_meta"].get("answer_comparison") == comparison][:4]:
            add(item, comparison)
    retried = [item for item in items if any(run.get("error") or run.get("attempts", 1) > 1
                                              for run in item["processing_meta"]["model_runs"])]
    for item in retried[:4]:
        add(item, "RETRIED")
    fields = (("TYPE", lambda x: x["classification"]["question_type"], 5),
              ("DIFFICULTY", lambda x: x["classification"]["difficulty"], 4),
              ("YEAR", lambda x: x["source"]["exam_year"], 3),
              ("TOPIC", lambda x: x["classification"]["topic_id"], 2))
    covered = {name: {lookup(item) for item in items if item["item_key"] in seen}
               for name, lookup, _ in fields}
    while len(chosen) < min(limit, len(items)):
        remaining = [item for item in items if item["item_key"] not in seen]
        if not remaining:
            break
        def score(item: dict) -> int:
            return sum(weight for name, lookup, weight in fields
                       if lookup(item) is not None and lookup(item) not in covered[name])
        item = max(remaining, key=lambda candidate: (score(candidate), candidate["item_key"]))
        reason = "COVERAGE" if score(item) else "FILL"
        add(item, reason)
        for name, lookup, _ in fields:
            covered[name].add(lookup(item))
    atomic_json(out / "review-sample.json", {"schema_version": "legacy-review-sample-0.1",
                                               "count": len(chosen), "items": chosen,
                                               "no_ai_judging": True})
    return chosen
