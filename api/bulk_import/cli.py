"""Operator-controlled local PDF import CLI. No automatic publishing."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from .ai import ModelError, make_tasks
from .contract import canonical_digest, sha256_file, stem_fingerprint, validate_item
from .db import connect_existing, import_one, list_topics
from .legacy import audit as audit_legacy, normalize as normalize_legacy
from .pipeline import prepare
from .storage import atomic_json, read_items, read_json, write_items


def _show(item: dict) -> None:
    print("\n---", item["item_key"], "---")
    print("来源：", item["source"]["name"], "[", item["source"]["kind"], "]", "页码：", item["source"].get("pages"))
    print("原始题干：", item["content"]["stem_raw"])
    print("标准化题干：", item["content"]["stem_latex"])
    print("小问：", item["content"].get("subquestions"))
    print("来源答案：", item["source_answer"].get("text") or "（无）", "[", item["source_answer"].get("kind"), "]")
    print("答案证据：", item["source_answer"].get("evidence", []))
    print("AI 答案：", item["ai_answer"].get("answer") or "（待处理）", "[", item["ai_answer"]["status"], "]")
    print("AI 解析：", item["ai_answer"].get("analysis") or "（无）")
    print("知识点/题型/难度：", item["classification"])
    print("考试标签：", item["exam_scope"].get("target_id"))
    print("警告：", item["validation"].get("warnings", []))
    print("错误：", item["validation"].get("errors", []))


def validate_batch(batch_dir: Path, db_path: Path | None = None) -> tuple[int, int]:
    items = read_items(batch_dir)
    progress = read_json(batch_dir / "progress.json")
    con = connect_existing(db_path) if db_path else None
    manifest = read_json(batch_dir / "manifest.json")
    if not isinstance(manifest, dict):
        raise ValueError("批次 manifest 无效")
    source_sha = manifest.get("source_sha256", "")
    safe_sha = source_sha if isinstance(source_sha, str) and re.fullmatch(r"[0-9a-f]{64}", source_sha) else ""
    source_asset = batch_dir / "assets" / ("source-" + safe_sha + ".pdf")
    verified_source_hash = sha256_file(source_asset) if (
        safe_sha and source_asset.is_file()
    ) else None
    invalid = 0
    seen_fingerprints: dict[str, str] = {}
    try:
        for item in items:
            errors, warnings = validate_item(item, batch_dir, con, verified_source_hash=verified_source_hash)
            fingerprint = stem_fingerprint(item.get("content", {}).get("stem_latex", ""))
            if fingerprint in seen_fingerprints:
                warnings.append("疑似本批重复题：" + seen_fingerprints[fingerprint])
            else:
                seen_fingerprints[fingerprint] = item["item_key"]
            item["validation"] = {"errors": errors, "warnings": warnings,
                                  "duplicate_candidates": [warning.removeprefix("疑似重复题：")
                                                           for warning in warnings if warning.startswith("疑似重复题：")]}
            state = progress["items"].setdefault(item["item_key"], {"status": "PENDING", "attempts": 0})
            if state.get("confirmed_digest") != canonical_digest(item):
                state.pop("confirmed_digest", None)
                if state.get("status") != "IMPORTED":
                    state["status"] = "BLOCKED" if errors else "READY"
            elif state.get("status") != "IMPORTED":
                state["status"] = "BLOCKED" if errors else "CONFIRMED"
            state["errors"] = errors
            state["warnings"] = warnings
            invalid += bool(errors)
    finally:
        if con:
            con.close()
    write_items(batch_dir, items)
    atomic_json(batch_dir / "progress.json", progress)
    return len(items), invalid


def confirm_item(batch_dir: Path, item_key: str, acknowledgement: str) -> str:
    if acknowledgement != "CONFIRM " + item_key:
        raise ValueError("确认文本不匹配")
    items = read_items(batch_dir)
    item = next((x for x in items if x["item_key"] == item_key), None)
    if item is None:
        raise KeyError("题目不存在")
    progress = read_json(batch_dir / "progress.json")
    state = progress["items"][item_key]
    if state.get("status") != "READY" or state.get("errors"):
        raise ValueError("请先运行 validate，并修正所有错误")
    state["confirmed_digest"] = canonical_digest(item)
    state["status"] = "CONFIRMED"
    atomic_json(batch_dir / "progress.json", progress)
    return item_key


def retry_item(batch_dir: Path, item_key: str, tasks, topics: list[dict] | None = None) -> None:
    items = read_items(batch_dir)
    item = next((x for x in items if x["item_key"] == item_key), None)
    if item is None:
        raise KeyError("题目不存在")
    progress = read_json(batch_dir / "progress.json")
    state = progress["items"][item_key]
    if state.get("status") == "IMPORTED":
        raise ValueError("已导入题目不能通过重试覆盖")
    if item.get("processing_meta", {}).get("legacy_gate") == "BLOCKED":
        raise ValueError("历史候选需先人工核验并解除拆题/视觉/原件门槛，禁止直接调用模型")
    before = len(tasks.runs)
    if item["content"].get("assets"):
        item["ai_answer"] = {"status": "PENDING", "answer": "", "analysis": "", "provider": None,
                             "error": "题目含图表；答案模型未接收视觉信息"}
        state["status"] = "BLOCKED"
        state["error"] = item["ai_answer"]["error"]
    else:
        try:
            generated = tasks.answer(item["content"]["stem_latex"])
            item["ai_answer"] = {"status": "MOCK" if type(tasks).__name__ == "MockTasks" else "SUCCEEDED",
                                 "answer": generated["answer"], "analysis": generated["analysis"],
                                 "provider": "mock" if type(tasks).__name__ == "MockTasks" else "doubao-ark"}
            state["status"] = "PENDING"
            state.pop("error", None)
        except ModelError as exc:
            item["ai_answer"] = {"status": "PENDING", "answer": "", "analysis": "", "provider": None,
                                 "error": str(exc)}
            state["status"] = "BLOCKED"
            state["error"] = str(exc)
    classification = item["classification"]
    if not classification.get("topic_id") or not classification.get("question_type") or not classification.get("difficulty"):
        try:
            if topics:
                suggestion = tasks.recommend(item["content"]["stem_latex"], topics)
                classification["topic_id"] = classification.get("topic_id") or suggestion.get("topic_id")
                classification["question_type"] = classification.get("question_type") or (suggestion.get("question_type") if suggestion.get("question_type") in
                    {"名词解释", "选择/填空", "简答题", "论述题", "计算题"} else None)
                classification["difficulty"] = classification.get("difficulty") or suggestion.get("difficulty")
        except ModelError:
            pass
    item["processing_meta"].setdefault("model_runs", []).extend(tasks.runs[before:])
    state["attempts"] = state.get("attempts", 0) + 1
    state.pop("confirmed_digest", None)
    write_items(batch_dir, items)
    atomic_json(batch_dir / "progress.json", progress)


def import_batch(batch_dir: Path, db_path: Path) -> tuple[int, int]:
    items = read_items(batch_dir)
    progress = read_json(batch_dir / "progress.json")
    con = connect_existing(db_path, migrate_schema=True)
    created = 0
    failed = 0
    try:
        for item in items:
            state = progress["items"].setdefault(item["item_key"], {"status": "PENDING", "attempts": 0})
            if state.get("status") == "IMPORTED":
                continue
            if state.get("status") != "CONFIRMED" or not state.get("confirmed_digest"):
                continue
            try:
                question_id, inserted = import_one(con, batch_dir, item, state["confirmed_digest"])
                state.update({"status": "IMPORTED", "question_id": question_id, "attempts": state["attempts"] + 1})
                created += int(inserted)
            except (ValueError, sqlite3.Error) as exc:
                state.update({"status": "ERROR", "error": str(exc), "attempts": state["attempts"] + 1})
                failed += 1
            atomic_json(batch_dir / "progress.json", progress)
    finally:
        con.close()
    return created, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地 PDF 批量导题：人工确认后仅写入 DRAFT")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare", help="解析 PDF 并生成四件套；默认不真实调用模型")
    create.add_argument("pdf", type=Path)
    create.add_argument("--out", type=Path, required=True)
    create.add_argument("--source-name", required=True)
    create.add_argument("--source-kind", choices=["TARGET_PAST_EXAM", "RELATED_PAST_EXAM", "CURATED_EXERCISE"], required=True)
    create.add_argument("--target-id", required=True)
    create.add_argument("--exam-year", type=int)
    create.add_argument("--source-url")
    create.add_argument("--db", type=Path)
    create.add_argument("--provider", choices=["none", "mock", "doubao"], default="doubao")
    create.add_argument("--allow-model-call", action="store_true")
    for name in ("audit-legacy", "normalize-legacy"):
        legacy = sub.add_parser(name, help="只读审计历史 PDF 候选，或零 AI 导出 V0.1 批次")
        legacy.add_argument("--db", type=Path, required=True)
        legacy.add_argument("--target-id")
        legacy.add_argument("--source-contains")
        legacy.add_argument("--year", type=int, action="append")
        if name == "normalize-legacy":
            legacy.add_argument("--out", type=Path, required=True)
    for name in ("preview", "validate", "confirm", "import", "retry"):
        command = sub.add_parser(name)
        command.add_argument("batch_dir", type=Path)
        if name in ("validate", "import"):
            command.add_argument("--db", type=Path, required=name == "import")
        if name in ("confirm", "retry"):
            command.add_argument("--item-key", required=True)
        if name == "retry":
            command.add_argument("--db", type=Path)
            command.add_argument("--provider", choices=["none", "mock", "doubao"], default="doubao")
            command.add_argument("--allow-model-call", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit-legacy":
            print(json.dumps(audit_legacy(args.db, args.target_id, args.source_contains, args.year), ensure_ascii=False, indent=2))
        elif args.command == "normalize-legacy":
            print(json.dumps(normalize_legacy(args.db, args.out, args.target_id,
                                              args.source_contains, args.year), ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            tasks = make_tasks(args.provider, args.allow_model_call)
            topics = list_topics(args.db, args.target_id) if args.db else []
            print(json.dumps(prepare(args.pdf, args.out, source_name=args.source_name,
                                     source_kind=args.source_kind, target_id=args.target_id,
                                     exam_year=args.exam_year, source_url=args.source_url,
                                     tasks=tasks, topics=topics), ensure_ascii=False, indent=2))
        elif args.command == "preview":
            for item in read_items(args.batch_dir):
                _show(item)
        elif args.command == "validate":
            total, invalid = validate_batch(args.batch_dir, args.db)
            print(f"校验完成：{total} 题，{invalid} 题待处理")
        elif args.command == "confirm":
            item = next(x for x in read_items(args.batch_dir) if x["item_key"] == args.item_key)
            _show(item)
            acknowledgement = input("输入 CONFIRM <item_key> 才能确认：").strip()
            print("已确认：", confirm_item(args.batch_dir, args.item_key, acknowledgement))
        elif args.command == "retry":
            item = next(x for x in read_items(args.batch_dir) if x["item_key"] == args.item_key)
            topics = list_topics(args.db, item["exam_scope"]["target_id"]) if args.db else []
            retry_item(args.batch_dir, args.item_key, make_tasks(args.provider, args.allow_model_call), topics)
            print("重试完成；请重新 validate 和 confirm")
        elif args.command == "import":
            created, failed = import_batch(args.batch_dir, args.db)
            print(f"新建 DRAFT：{created}，失败：{failed}")
    except (OSError, ValueError, KeyError, ModelError, StopIteration) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
