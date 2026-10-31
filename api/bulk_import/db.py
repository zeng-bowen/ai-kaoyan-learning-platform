"""One-item-at-a-time, idempotent DRAFT import into the existing Question table."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.migrations.bulk_import_v01 import migrate
from .contract import canonical_digest, validate_item


def connect_existing(path: Path, *, migrate_schema: bool = False) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError("数据库不存在；请指向已有平台 SQLite 文件，禁止隐式创建")
    con = sqlite3.connect(path, timeout=10) if migrate_schema else sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='questions'").fetchone():
        con.close()
        raise ValueError("不是平台数据库：缺少 questions 表")
    if migrate_schema:
        migrate(con)
        con.commit()
    return con


def list_topics(path: Path, target_id: str) -> list[dict[str, str]]:
    con = connect_existing(path)
    try:
        return [dict(row) for row in con.execute(
            "SELECT t.id,t.name,t.subject,t.module FROM topics t JOIN topic_target_tags x ON x.topic_id=t.id "
            "WHERE x.target_id=? ORDER BY t.id", (target_id,))]
    finally:
        con.close()


def deterministic_question_id(item: dict[str, Any]) -> str:
    material = item["source"]["file_sha256"] + ":" + item["item_key"]
    return "imp-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:28]


def _preserve_file(source: Path, destination: Path, expected_sha: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected_sha:
            raise ValueError("已存在的题目资源哈希不匹配")
        return
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected_sha:
        temporary.unlink(missing_ok=True)
        raise ValueError("复制题目资源后哈希不匹配")
    temporary.replace(destination)


def import_one(con: sqlite3.Connection, batch_dir: Path, item: dict[str, Any], confirmed_digest: str) -> tuple[str, bool]:
    if canonical_digest(item) != confirmed_digest:
        raise ValueError("JSON 已修改，原确认失效；请重新校验并确认")
    errors, warnings = validate_item(item, batch_dir, con)
    if errors:
        raise ValueError("；".join(errors))
    question_id = deterministic_question_id(item)
    source = item["source"]
    answer = item["source_answer"]
    classification = item["classification"]
    db_dir = Path(con.execute("PRAGMA database_list").fetchone()[2]).parent
    source_storage = "question-sources/" + source["file_sha256"] + ".pdf"
    manifest_path = batch_dir / "manifest.json"
    if manifest_path.is_file():
        _preserve_file(batch_dir / "assets" / ("source-" + source["file_sha256"] + ".pdf"),
                       db_dir / source_storage, source["file_sha256"])
    stored_assets = []
    for asset in item["content"].get("assets", []):
        stored_path = "question-assets/" + asset["sha256"] + ".png"
        _preserve_file(batch_dir / asset["path"], db_dir / stored_path, asset["sha256"])
        stored_assets.append({**asset, "stored_path": stored_path})
    metadata = {"schema_version": item["schema_version"], "item_key": item["item_key"],
                "file_sha256": source["file_sha256"], "file_name": source["file_name"],
                "source_storage_path": source_storage if manifest_path.is_file() else None,
                "pages": source.get("pages", []),
                "content": {**item["content"], "assets": stored_assets},
                "source_answer_evidence": answer.get("evidence", []),
                "duplicate_warnings": [warning for warning in warnings if warning.startswith("疑似重复题")],
                "processing_meta": item["processing_meta"]}
    now = datetime.now(timezone.utc).isoformat()
    con.execute("BEGIN IMMEDIATE")
    try:
        existing = con.execute("SELECT import_meta_json FROM questions WHERE id=?", (question_id,)).fetchone()
        if existing:
            old = json.loads(existing["import_meta_json"] or "{}")
            if old.get("item_key") != item["item_key"] or old.get("file_sha256") != source["file_sha256"]:
                raise ValueError("确定性题目 ID 冲突，未覆盖旧题")
            con.commit()
            return question_id, False
        number = con.execute("SELECT MAX(CAST(SUBSTR(catalog_number,3) AS INTEGER)) FROM questions "
                             "WHERE catalog_number GLOB 'Q-[0-9]*'").fetchone()[0] or 0
        con.execute("""INSERT INTO questions(
            id,catalog_number,target_id,topic_id,source_type,source_name,source_url,source_verified,
            exam_year,question_type,difficulty,stem,answer,analysis,review_status,updated_at,
            source_answer_kind,ai_answer_json,import_meta_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'DRAFT',?,?,?,?)""",
            (question_id, f"Q-{number + 1:06d}", item["exam_scope"]["target_id"], classification["topic_id"],
             source["kind"], source["name"], source.get("url") or "", int(bool(source.get("human_verified"))),
             source.get("exam_year"), classification["question_type"], classification["difficulty"],
             item["content"]["stem_latex"], answer.get("text") or "", answer.get("analysis") or "",
             now, answer["kind"], json.dumps(item["ai_answer"], ensure_ascii=False),
             json.dumps(metadata, ensure_ascii=False)))
        con.execute("UPDATE change_versions SET version=version+1 WHERE scope='content'")
        con.commit()
        return question_id, True
    except Exception:
        con.rollback()
        raise
