"""Local development API. Seed content is illustrative and never verified exam material."""

from contextlib import contextmanager
from pathlib import Path
import base64
import binascii
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.recognition import configured_provider
from api.migrations.bulk_import_v01 import migrate as migrate_bulk_import_v01

DB_PATH = Path(os.environ.get("ECON_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "platform.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DB_PATH.parent / "question-intakes"


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


with db() as con:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS targets(id TEXT PRIMARY KEY, school TEXT NOT NULL, major TEXT NOT NULL, exam_subject TEXT NOT NULL, target_year INTEGER NOT NULL, verified INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS topics(id TEXT PRIMARY KEY, subject TEXT NOT NULL, module TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, target_id TEXT NOT NULL, topic_id TEXT NOT NULL, source_type TEXT NOT NULL, source_name TEXT NOT NULL, question_type TEXT NOT NULL, difficulty INTEGER NOT NULL, stem TEXT NOT NULL, answer TEXT NOT NULL, analysis TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'DRAFT', FOREIGN KEY(target_id) REFERENCES targets(id), FOREIGN KEY(topic_id) REFERENCES topics(id));
    CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, question_id TEXT NOT NULL, answer_text TEXT NOT NULL, self_rating INTEGER NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(question_id) REFERENCES questions(id));
    CREATE TABLE IF NOT EXISTS change_versions(scope TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS study_presence(session_id TEXT PRIMARY KEY, active INTEGER NOT NULL, last_seen TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS question_intakes(id TEXT PRIMARY KEY, original_name TEXT NOT NULL, stored_name TEXT NOT NULL, mime_type TEXT NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    # Additive migration: keep existing targets and all user learning records.
    target_columns = {row["name"] for row in con.execute("PRAGMA table_info(targets)")}
    for column, definition in {
        "college": "TEXT NOT NULL DEFAULT ''",
        "exam_code": "TEXT NOT NULL DEFAULT ''",
        "exam_label": "TEXT NOT NULL DEFAULT ''",
        "note": "TEXT NOT NULL DEFAULT ''",
        "source_url": "TEXT NOT NULL DEFAULT ''",
        "source_checked_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        if column not in target_columns:
            con.execute(f"ALTER TABLE targets ADD COLUMN {column} {definition}")
    question_columns = {row["name"] for row in con.execute("PRAGMA table_info(questions)")}
    for column, definition in {
        "catalog_number": "TEXT", "exam_year": "INTEGER", "source_url": "TEXT NOT NULL DEFAULT ''",
        "source_verified": "INTEGER NOT NULL DEFAULT 0", "intake_id": "TEXT", "reviewed_at": "TEXT",
        "review_note": "TEXT NOT NULL DEFAULT ''", "updated_at": "TEXT",
    }.items():
        if column not in question_columns:
            con.execute(f"ALTER TABLE questions ADD COLUMN {column} {definition}")
    migrate_bulk_import_v01(con)
    intake_columns = {row["name"] for row in con.execute("PRAGMA table_info(question_intakes)")}
    if "recognition_json" not in intake_columns:
        con.execute("ALTER TABLE question_intakes ADD COLUMN recognition_json TEXT")
    topic_columns = {row["name"] for row in con.execute("PRAGMA table_info(topics)")}
    for column, definition in {
        "source_name": "TEXT NOT NULL DEFAULT '演示内容'", "source_url": "TEXT NOT NULL DEFAULT ''",
        "review_status": "TEXT NOT NULL DEFAULT 'APPROVED'", "updated_at": "TEXT",
    }.items():
        if column not in topic_columns:
            con.execute(f"ALTER TABLE topics ADD COLUMN {column} {definition}")
    tag_table_exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='topic_target_tags'").fetchone() is not None
    con.execute("""CREATE TABLE IF NOT EXISTS topic_target_tags(
        topic_id TEXT NOT NULL REFERENCES topics(id),
        target_id TEXT NOT NULL REFERENCES targets(id),
        PRIMARY KEY(topic_id,target_id))""")
    for scope in ("content", "activity"):
        con.execute("INSERT OR IGNORE INTO change_versions(scope,version) VALUES (?,0)", (scope,))
    for row in con.execute("SELECT rowid,id FROM questions WHERE catalog_number IS NULL OR catalog_number='' ORDER BY rowid"):
        con.execute("UPDATE questions SET catalog_number=? WHERE id=?", (f"Q-{row['rowid']:06d}", row["id"]))
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS questions_catalog_number_unique ON questions(catalog_number)")
    if not con.execute("SELECT 1 FROM targets LIMIT 1").fetchone():
        con.executemany("INSERT INTO targets(id,school,major,exam_subject,target_year,verified) VALUES (?,?,?,?,?,?)", [
            ("demo-pku", "北京大学", "经济学相关专业（演示）", "专业课配置待核验", 2028, 0),
            ("demo-ruc", "中国人民大学", "经济学相关专业（演示）", "专业课配置待核验", 2028, 0),
            ("demo-sufe", "上海财经大学", "经济学相关专业（演示）", "专业课配置待核验", 2028, 0),
        ])
        con.executemany("INSERT INTO topics(id,subject,module,name,summary) VALUES (?,?,?,?,?)", [
            ("consumer", "微观经济学", "消费者理论", "预算约束与最优选择", "用预算线与无差异曲线解释消费者的可行集合和内点最优条件。"),
            ("elasticity", "微观经济学", "需求理论", "价格弹性", "掌握弹性的定义、点弹性计算和经济含义。"),
            ("islm", "宏观经济学", "短期均衡", "IS–LM 模型", "识别商品市场与货币市场的均衡条件及政策冲击方向。"),
        ])
        con.executemany("INSERT INTO questions(id,target_id,topic_id,source_type,source_name,question_type,difficulty,stem,answer,analysis,review_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            ("q-consumer", "demo-pku", "consumer", "CURATED_EXERCISE", "平台原创演示题", "计算题", 2, "某消费者效用函数 U(x,y)=xy，收入为 120，x 与 y 的价格分别为 2 和 3。求最优消费组合。", "x=30，y=20。", "柯布–道格拉斯效用的支出份额各为 1/2：x=(120/2)/2=30，y=(120/2)/3=20。", "APPROVED"),
            ("q-elasticity", "demo-pku", "elasticity", "CURATED_EXERCISE", "平台原创演示题", "简答题", 2, "解释需求价格弹性的含义，并说明为什么它通常取负值。", "需求价格弹性衡量需求量对价格变化的敏感程度，通常因需求曲线向下倾斜而为负。", "可写出 E=(dQ/dP)·(P/Q)，并说明负号与其他条件不变的假设。", "APPROVED"),
            ("q-islm", "demo-ruc", "islm", "CURATED_EXERCISE", "平台原创演示题", "图形分析题", 3, "在 IS–LM 框架中，其他条件不变时，扩张性财政政策会如何影响 IS 曲线与均衡利率？", "IS 曲线右移，均衡利率一般上升。", "政府支出增加使给定利率下总需求提高，IS 右移。均衡产出和利率的变化取决于曲线斜率。", "APPROVED"),
        ])
        for row in con.execute("SELECT rowid,id FROM questions ORDER BY rowid"):
            con.execute("UPDATE questions SET catalog_number=? WHERE id=?", (f"Q-{row['rowid']:06d}", row["id"]))
    # Preserve all legacy IDs, questions and attempts; expose a canonical tag label.
    for row in con.execute("SELECT id,exam_code,exam_subject FROM targets WHERE exam_label='' OR exam_label IS NULL"):
        code, subject = row["exam_code"].strip(), row["exam_subject"].strip()
        label = f"{code} {subject}" if code and subject and subject != code else code or subject
        con.execute("UPDATE targets SET exam_label=? WHERE id=?", (label, row["id"]))
    if not tag_table_exists:
        con.execute("""INSERT OR IGNORE INTO topic_target_tags(topic_id,target_id)
            SELECT DISTINCT topic_id,target_id FROM questions""")

app = FastAPI(title="经济学考研学习平台 API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def guard_admin(request: Request, call_next):
    if request.url.path.startswith("/api/admin/"):
        # This development-only API must never be reachable from a public interface.
        if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "管理员接口仅允许本机开发访问"}, status_code=403)
    return await call_next(request)


def rows(sql: str, params: tuple = ()):
    with db() as con:
        return [dict(row) for row in con.execute(sql, params).fetchall()]


def bump(con: sqlite3.Connection, scope: str):
    con.execute("UPDATE change_versions SET version=version+1 WHERE scope=?", (scope,))


def current_exam_year() -> int:
    """The upcoming exam cohort follows the current China calendar year."""
    return datetime.now(timezone(timedelta(hours=8))).year + 1


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "local-development"}


@app.get("/api/versions")
def versions():
    return {row["scope"]: row["version"] for row in rows("SELECT * FROM change_versions")}


@app.get("/api/targets")
def targets():
    return rows("SELECT id,school,exam_label,note,? AS target_year FROM targets ORDER BY school,exam_label", (current_exam_year(),))


class TargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    school: str = Field(min_length=2, max_length=100)
    exam_label: str = Field(min_length=2, max_length=120)
    note: str = Field(default="", max_length=1000)


def validated_target(payload: TargetIn) -> dict:
    data = {key: value.strip() for key, value in payload.model_dump().items()}
    if not data["school"] or not data["exam_label"]:
        raise HTTPException(422, "院校和考试科目代码不能为空")
    return data


@app.post("/api/admin/targets")
def create_target(payload: TargetIn):
    data = validated_target(payload)
    now = datetime.now(timezone.utc).isoformat()
    target_id = f"exam-{uuid.uuid4().hex}"
    with db() as con:
        if con.execute("SELECT 1 FROM targets WHERE school=? AND exam_label=?", (data["school"], data["exam_label"])).fetchone():
            raise HTTPException(409, "院校与考试科目代码标签已存在")
        con.execute("""INSERT INTO targets(id,school,major,exam_subject,target_year,verified,exam_label,note,updated_at)
            VALUES (?,?, '', ?, ?,0,?,?,?)""", (target_id, data["school"], data["exam_label"], current_exam_year(), data["exam_label"], data["note"], now))
        bump(con, "content")
    return {"id": target_id, "target_year": current_exam_year()}


@app.put("/api/admin/targets/{target_id}")
def update_target(target_id: str, payload: TargetIn):
    data = validated_target(payload)
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        if con.execute("SELECT 1 FROM targets WHERE school=? AND exam_label=? AND id<>?", (data["school"], data["exam_label"], target_id)).fetchone():
            raise HTTPException(409, "院校与考试科目代码标签已存在")
        cur = con.execute("""UPDATE targets SET school=?,exam_label=?,note=?,target_year=?,updated_at=?
            WHERE id=?""", (data["school"], data["exam_label"], data["note"], current_exam_year(), now, target_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "目标考试不存在")
        bump(con, "content")
    return {"id": target_id, "target_year": current_exam_year()}


def tagged_topics(approved_only: bool, target_id: str | None = None):
    clauses = []
    params: list[str] = []
    if approved_only:
        clauses.append("t.review_status='APPROVED'")
    if target_id:
        clauses.append("EXISTS (SELECT 1 FROM topic_target_tags x WHERE x.topic_id=t.id AND x.target_id=?)")
        params.append(target_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    items = rows(f"SELECT t.* FROM topics t {where} ORDER BY t.subject,t.module,t.name", tuple(params))
    tags = rows("SELECT topic_id,target_id FROM topic_target_tags")
    by_topic: dict[str, list[str]] = {}
    for tag in tags:
        by_topic.setdefault(tag["topic_id"], []).append(tag["target_id"])
    return [{**item, "target_ids": by_topic.get(item["id"], [])} for item in items]


@app.get("/api/topics")
def topics(target_id: str | None = None):
    return tagged_topics(True, target_id)


@app.get("/api/admin/topics")
def admin_topics():
    return tagged_topics(False)


class TopicIn(BaseModel):
    id: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")
    subject: str = Field(min_length=2, max_length=100)
    module: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=100)
    summary: str = Field(min_length=5)
    source_name: str = Field(min_length=2, max_length=200)
    source_url: str = Field(default="", max_length=1000)
    target_ids: list[str] = Field(min_length=1)


def validated_topic(payload: TopicIn):
    data = payload.model_dump()
    for key in ("id", "subject", "module", "name", "summary", "source_name", "source_url"):
        data[key] = data[key].strip()
    data["target_ids"] = list(dict.fromkeys(item.strip() for item in data["target_ids"] if item.strip()))
    if not data["target_ids"]:
        raise HTTPException(422, "知识点至少绑定一个院校考试标签")
    with db() as con:
        existing = con.execute(f"SELECT COUNT(*) FROM targets WHERE id IN ({','.join('?' for _ in data['target_ids'])})", data["target_ids"]).fetchone()[0]
    if existing != len(data["target_ids"]):
        raise HTTPException(422, "所选院校考试标签不存在")
    if data["source_url"]:
        parsed = urlparse(data["source_url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422, "来源链接必须是有效的 HTTPS 地址")
    return data


@app.post("/api/admin/topics")
def create_topic(payload: TopicIn):
    data = validated_topic(payload)
    try:
        with db() as con:
            con.execute("""INSERT INTO topics(id,subject,module,name,summary,source_name,source_url,review_status,updated_at)
                VALUES (:id,:subject,:module,:name,:summary,:source_name,:source_url,'DRAFT',:updated_at)""", {**data, "updated_at": datetime.now(timezone.utc).isoformat()})
            con.executemany("INSERT INTO topic_target_tags(topic_id,target_id) VALUES (?,?)", [(data["id"], target_id) for target_id in data["target_ids"]])
            bump(con, "content")
    except sqlite3.IntegrityError:
        raise HTTPException(409, "知识点 ID 已存在")
    return {"id": data["id"], "review_status": "DRAFT"}


@app.put("/api/admin/topics/{topic_id}")
def update_topic(topic_id: str, payload: TopicIn):
    data = validated_topic(payload)
    if topic_id != data["id"]:
        raise HTTPException(422, "知识点 ID 不可修改")
    with db() as con:
        cur = con.execute("""UPDATE topics SET subject=:subject,module=:module,name=:name,summary=:summary,
            source_name=:source_name,source_url=:source_url,review_status='DRAFT',updated_at=:updated_at WHERE id=:id""", {**data, "updated_at": datetime.now(timezone.utc).isoformat()})
        if cur.rowcount == 0:
            raise HTTPException(404, "知识点不存在")
        con.execute("DELETE FROM topic_target_tags WHERE topic_id=?", (topic_id,))
        con.executemany("INSERT INTO topic_target_tags(topic_id,target_id) VALUES (?,?)", [(topic_id, target_id) for target_id in data["target_ids"]])
        con.execute("UPDATE questions SET review_status='DRAFT',reviewed_at=NULL,review_note='关联知识点已修改，需重新审核' WHERE topic_id=? AND review_status='APPROVED'", (topic_id,))
        bump(con, "content")
    return {"id": topic_id, "review_status": "DRAFT"}


@app.post("/api/admin/topics/{topic_id}/approve")
def approve_topic(topic_id: str):
    with db() as con:
        topic = con.execute("SELECT source_name,source_url FROM topics WHERE id=?", (topic_id,)).fetchone()
        if not topic:
            raise HTTPException(404, "知识点不存在")
        if not topic["source_url"]:
            raise HTTPException(422, "知识点发布前须填写并人工核对来源链接")
        if not con.execute("SELECT 1 FROM topic_target_tags WHERE topic_id=?", (topic_id,)).fetchone():
            raise HTTPException(422, "知识点须绑定院校考试标签")
        con.execute("UPDATE topics SET review_status='APPROVED',updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), topic_id))
        bump(con, "content")
    return {"id": topic_id, "review_status": "APPROVED"}


@app.get("/api/questions")
def questions(target_id: str | None = None):
    clause = "WHERE q.review_status='APPROVED' AND t.review_status='APPROVED'"
    params = (target_id,) if target_id else ()
    if target_id:
        clause += " AND q.target_id=?"
    return rows(f"""SELECT q.* FROM questions q JOIN topics t ON t.id=q.topic_id
        JOIN topic_target_tags x ON x.topic_id=q.topic_id AND x.target_id=q.target_id
        {clause} ORDER BY q.catalog_number""", params)


@app.get("/api/admin/questions")
def admin_questions(target_id: str | None = None, exam_year: int | None = None, topic_id: str | None = None, source_type: str | None = None, review_status: str | None = None):
    filters = []
    params = []
    for column, value in (("target_id", target_id), ("exam_year", exam_year), ("topic_id", topic_id), ("source_type", source_type), ("review_status", review_status)):
        if value is not None and value != "":
            filters.append(f"{column}=?")
            params.append(value)
    where = "WHERE " + " AND ".join(filters) if filters else ""
    return rows(f"SELECT * FROM questions {where} ORDER BY catalog_number", tuple(params))


class AttemptIn(BaseModel):
    question_id: str
    answer_text: str = Field(min_length=1, max_length=10000)
    self_rating: int = Field(ge=0, le=3)


@app.post("/api/attempts")
def create_attempt(payload: AttemptIn):
    question = rows("""SELECT q.id,q.review_status,t.review_status AS topic_status FROM questions q
        JOIN topics t ON t.id=q.topic_id JOIN topic_target_tags x ON x.topic_id=q.topic_id AND x.target_id=q.target_id
        WHERE q.id=?""", (payload.question_id,))
    if not question or question[0]["review_status"] != "APPROVED" or question[0]["topic_status"] != "APPROVED":
        raise HTTPException(404, "题目不可作答")
    with db() as con:
        cur = con.execute("INSERT INTO attempts(user_id,question_id,answer_text,self_rating,created_at) VALUES (?,?,?,?,?)", ("local-demo", payload.question_id, payload.answer_text, payload.self_rating, datetime.now(timezone.utc).isoformat()))
        bump(con, "activity")
        return {"id": cur.lastrowid, "saved": True}


@app.get("/api/attempts")
def attempts():
    return rows("SELECT * FROM attempts WHERE user_id='local-demo' ORDER BY id DESC")


@app.get("/api/stats")
def stats(target_id: str | None = None):
    query = "SELECT a.*,q.topic_id,q.question_type,t.name AS topic_name FROM attempts a JOIN questions q ON q.id=a.question_id JOIN topics t ON t.id=q.topic_id WHERE a.user_id='local-demo'"
    params = ()
    if target_id:
        query += " AND q.target_id=?"
        params = (target_id,)
    items = rows(query + " ORDER BY a.id DESC", params)
    by_topic = {}
    for item in items:
        key = item["topic_id"]
        slot = by_topic.setdefault(key, {"topic_id": key, "name": item["topic_name"], "attempts": 0, "ratings": 0})
        slot["attempts"] += 1
        slot["ratings"] += item["self_rating"]
    return {"attempt_count": len(items), "topic_stats": [{**v, "average_self_rating": round(v["ratings"] / v["attempts"], 2)} for v in by_topic.values()], "method": "用户自评 0–3；不代表自动判分或目标院校适配度"}


class PresenceIn(BaseModel):
    session_id: str = Field(min_length=16, max_length=100)
    active: bool


@app.post("/api/study-presence")
def study_presence(payload: PresenceIn):
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        con.execute("INSERT INTO study_presence(session_id,active,last_seen) VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET active=excluded.active,last_seen=excluded.last_seen", (payload.session_id, int(payload.active), now))
        bump(con, "activity")
    return {"saved": True}


@app.get("/api/admin/stats")
def admin_stats():
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    with db() as con:
        active = con.execute("SELECT COUNT(*) FROM study_presence WHERE active=1 AND last_seen>=?", (cutoff,)).fetchone()[0]
        attempts = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        published = con.execute("""SELECT COUNT(*) FROM questions q JOIN topics t ON t.id=q.topic_id
            JOIN topic_target_tags x ON x.topic_id=q.topic_id AND x.target_id=q.target_id
            WHERE q.review_status='APPROVED' AND t.review_status='APPROVED'""").fetchone()[0]
        difficulty = [dict(row) for row in con.execute("""SELECT q.difficulty, COUNT(*) AS attempts, ROUND(AVG(a.self_rating),2) AS average_self_rating
            FROM attempts a JOIN questions q ON q.id=a.question_id GROUP BY q.difficulty ORDER BY q.difficulty""")]
    return {"active_training_sessions": active, "attempt_count": attempts, "published_questions": published, "difficulty_stats": difficulty,
            "correct_rate": None, "method": "在线人数为近 30 秒内发送训练心跳的本地会话数；题目表现为 0–3 自评均值。当前无客观判分，正确率暂不计算。"}


class QuestionIn(BaseModel):
    id: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")
    catalog_number: str = Field(default="", max_length=40)
    target_id: str
    topic_id: str
    source_type: str
    source_name: str = Field(min_length=2)
    source_url: str = Field(default="", max_length=1000)
    source_verified: bool = False
    exam_year: int | None = Field(default=None, ge=1990, le=2100)
    question_type: str
    difficulty: int = Field(ge=1, le=5)
    stem: str = Field(min_length=5)
    # Incomplete source answers are permitted in DRAFT only; approval still checks both.
    answer: str = ""
    analysis: str = ""
    intake_id: str | None = None


SOURCE_TYPES = {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM", "CURATED_EXERCISE", "AI_GENERATED"}


def validated_question(payload: QuestionIn) -> dict:
    data = payload.model_dump()
    for key in ("id", "catalog_number", "target_id", "topic_id", "source_type", "source_name", "source_url", "question_type", "stem", "answer", "analysis"):
        data[key] = data[key].strip()
    if data["source_type"] not in SOURCE_TYPES:
        raise HTTPException(422, "无效的题目来源类型")
    if data["source_type"] in {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM"} and (not data["exam_year"] or not data["source_url"]):
        raise HTTPException(422, "真题必须填写年份与可核验来源链接")
    if data["source_url"]:
        parsed = urlparse(data["source_url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422, "来源链接必须是有效的 HTTPS 地址")
    if not rows("SELECT id FROM targets WHERE id=?", (data["target_id"],)) or not rows("SELECT id FROM topics WHERE id=?", (data["topic_id"],)):
        raise HTTPException(422, "目标或知识点不存在")
    if data["intake_id"] and not rows("SELECT id FROM question_intakes WHERE id=?", (data["intake_id"],)):
        raise HTTPException(422, "上传图片不存在")
    return data


def next_number(con: sqlite3.Connection) -> str:
    numbers = [int(row[0][2:]) for row in con.execute("SELECT catalog_number FROM questions WHERE catalog_number GLOB 'Q-[0-9]*'") if row[0][2:].isdigit()]
    return f"Q-{max(numbers, default=0) + 1:06d}"


@app.post("/api/admin/questions")
def create_question(payload: QuestionIn):
    data = validated_question(payload)
    try:
        with db() as con:
            data["catalog_number"] = data["catalog_number"] or next_number(con)
            con.execute("""INSERT INTO questions(id,target_id,topic_id,source_type,source_name,question_type,difficulty,stem,answer,analysis,review_status,catalog_number,exam_year,source_url,source_verified,intake_id,updated_at)
                VALUES (:id,:target_id,:topic_id,:source_type,:source_name,:question_type,:difficulty,:stem,:answer,:analysis,'DRAFT',:catalog_number,:exam_year,:source_url,:source_verified,:intake_id,:updated_at)""", {**data, "updated_at": datetime.now(timezone.utc).isoformat()})
            if data["intake_id"]:
                con.execute("UPDATE question_intakes SET status='DRAFT_LINKED' WHERE id=?", (data["intake_id"],))
            bump(con, "content")
    except sqlite3.IntegrityError:
        raise HTTPException(409, "题目 ID 或管理编号已存在")
    return {"id": data["id"], "catalog_number": data["catalog_number"], "review_status": "DRAFT"}


@app.put("/api/admin/questions/{question_id}")
def update_question(question_id: str, payload: QuestionIn):
    data = validated_question(payload)
    if question_id != data["id"]:
        raise HTTPException(422, "题目 ID 不可修改")
    try:
        with db() as con:
            current = con.execute("SELECT catalog_number,answer,analysis FROM questions WHERE id=?", (question_id,)).fetchone()
            if not current:
                raise HTTPException(404, "题目不存在")
            data["catalog_number"] = data["catalog_number"] or current["catalog_number"]
            answer_changed = data["answer"] != current["answer"] or data["analysis"] != current["analysis"]
            con.execute("""UPDATE questions SET catalog_number=:catalog_number,target_id=:target_id,topic_id=:topic_id,
                source_type=:source_type,source_name=:source_name,source_url=:source_url,source_verified=:source_verified,
                exam_year=:exam_year,question_type=:question_type,difficulty=:difficulty,stem=:stem,answer=:answer,
                analysis=:analysis,intake_id=:intake_id,source_answer_kind=CASE WHEN :answer_changed THEN 'UNKNOWN' ELSE source_answer_kind END,
                review_status='DRAFT',reviewed_at=NULL,review_note='',updated_at=:updated_at
                WHERE id=:id""", {**data, "answer_changed": answer_changed, "updated_at": datetime.now(timezone.utc).isoformat()})
            if data["intake_id"]:
                con.execute("UPDATE question_intakes SET status='DRAFT_LINKED' WHERE id=?", (data["intake_id"],))
            bump(con, "content")
    except sqlite3.IntegrityError:
        raise HTTPException(409, "管理编号已存在")
    return {"id": question_id, "review_status": "DRAFT"}


class ReviewIn(BaseModel):
    decision: str
    note: str = Field(default="", max_length=1000)


@app.post("/api/admin/questions/{question_id}/review")
def review_question(question_id: str, payload: ReviewIn):
    if payload.decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(422, "审核决定无效")
    with db() as con:
        question = con.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if not question:
            raise HTTPException(404, "题目不存在")
        if payload.decision == "APPROVED":
            required = ("catalog_number", "source_name", "topic_id", "target_id", "question_type", "stem", "answer", "analysis")
            if any(not question[key] for key in required):
                raise HTTPException(422, "题目来源、标签、编号、答案和解析需完整填写")
            if question["source_type"] in {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM"} and (not question["source_verified"] or not question["exam_year"] or not question["source_url"]):
                raise HTTPException(422, "真题来源须人工核验并填写年份后才能发布")
            if question["intake_id"] and not question["source_verified"]:
                raise HTTPException(422, "识图录题需人工核对来源后才能发布")
            topic = con.execute("SELECT review_status FROM topics WHERE id=?", (question["topic_id"],)).fetchone()
            if not topic or topic["review_status"] != "APPROVED":
                raise HTTPException(422, "关联知识点须先审核发布")
            if not con.execute("SELECT 1 FROM topic_target_tags WHERE topic_id=? AND target_id=?", (question["topic_id"], question["target_id"])).fetchone():
                raise HTTPException(422, "题目与知识点必须绑定相同的院校考试标签")
        now = datetime.now(timezone.utc).isoformat()
        con.execute("UPDATE questions SET review_status=?,review_note=?,reviewed_at=?,updated_at=? WHERE id=?", (payload.decision, payload.note.strip(), now, now, question_id))
        if question["intake_id"] and payload.decision == "APPROVED":
            con.execute("UPDATE question_intakes SET status='REVIEWED' WHERE id=?", (question["intake_id"],))
        bump(con, "content")
    return {"id": question_id, "review_status": payload.decision}


@app.post("/api/admin/questions/{question_id}/approve")
def approve_question(question_id: str):
    return review_question(question_id, ReviewIn(decision="APPROVED"))


class IntakeIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str
    base64_data: str = Field(min_length=1, max_length=12_000_000)


@app.post("/api/admin/intakes")
def upload_intake(payload: IntakeIn):
    formats = {"image/png": (b"\x89PNG\r\n\x1a\n", ".png"), "image/jpeg": (b"\xff\xd8\xff", ".jpg"), "image/webp": (b"RIFF", ".webp")}
    if payload.mime_type not in formats:
        raise HTTPException(422, "只支持 PNG、JPEG、WebP 图片")
    try:
        raw = base64.b64decode(payload.base64_data, validate=True)
    except binascii.Error:
        raise HTTPException(422, "图片数据无效")
    if not raw or len(raw) > 8 * 1024 * 1024 or not raw.startswith(formats[payload.mime_type][0]):
        raise HTTPException(422, "图片格式不符或超过 8 MB")
    if payload.mime_type == "image/webp" and (raw[8:12] != b"WEBP" or int.from_bytes(raw[4:8], "little") != len(raw) - 8):
        raise HTTPException(422, "WebP 图片格式无效")
    if payload.mime_type == "image/png" and (len(raw) < 45 or raw[12:16] != b"IHDR" or raw[-8:-4] != b"IEND"):
        raise HTTPException(422, "PNG 图片格式无效")
    if payload.mime_type == "image/jpeg" and (len(raw) < 12 or not raw.endswith(b"\xff\xd9")):
        raise HTTPException(422, "JPEG 图片格式无效")
    intake_id = str(uuid.uuid4())
    stored_name = intake_id + formats[payload.mime_type][1]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / stored_name).write_bytes(raw)
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        con.execute("INSERT INTO question_intakes(id,original_name,stored_name,mime_type,sha256,status,created_at) VALUES (?,?,?,?,?,?,?)", (intake_id, Path(payload.file_name).name, stored_name, payload.mime_type, hashlib.sha256(raw).hexdigest(), "AWAITING_PROVIDER", now))
        bump(con, "content")
    return {"id": intake_id, "file_name": Path(payload.file_name).name, "status": "AWAITING_PROVIDER"}


@app.get("/api/admin/intakes")
def list_intakes():
    return rows("SELECT id,original_name,mime_type,status,created_at FROM question_intakes ORDER BY created_at DESC")


@app.get("/api/admin/intakes/{intake_id}/image")
def intake_image(intake_id: str):
    item = rows("SELECT stored_name,mime_type FROM question_intakes WHERE id=?", (intake_id,))
    if not item:
        raise HTTPException(404, "上传图片不存在")
    return FileResponse(UPLOAD_DIR / item[0]["stored_name"], media_type=item[0]["mime_type"])


@app.post("/api/admin/intakes/{intake_id}/recognize")
def recognize_intake(intake_id: str):
    if not rows("SELECT 1 FROM question_intakes WHERE id=?", (intake_id,)):
        raise HTTPException(404, "上传图片不存在")
    return recognize_intake_with_provider(intake_id, recognition_provider())


def recognition_provider():
    """Load the configured provider without exposing local configuration details."""
    try:
        provider = configured_provider()
    except Exception:
        raise HTTPException(503, "识别提供方配置无效，请检查本机配置")
    if provider is None:
        raise HTTPException(501, "国产模型尚未配置；图片已保存，可人工录题并提交审核")
    return provider


def recognize_intake_with_provider(intake_id: str, provider):
    item = rows("SELECT stored_name,mime_type FROM question_intakes WHERE id=?", (intake_id,))
    if not item:
        raise HTTPException(404, "上传图片不存在")
    try:
        candidates = provider.recognize((UPLOAD_DIR / item[0]["stored_name"]).read_bytes(), item[0]["mime_type"])
        suggestions = [candidate.model_dump() for candidate in candidates]
        recognition_json = json.dumps(suggestions, ensure_ascii=False)
    except Exception:
        raise HTTPException(502, "识别服务失败，请稍后重试或人工录题")
    # 空候选是 Provider 正常执行的结果，仍保存为 AI_DRAFT，由管理员决定重新识别或人工录题。
    with db() as con:
        con.execute("UPDATE question_intakes SET status='AI_DRAFT',recognition_json=? WHERE id=?", (recognition_json, intake_id))
        bump(con, "content")
    return {"id": intake_id, "status": "AI_DRAFT", "suggestions": suggestions}


class BatchRecognizeIn(BaseModel):
    intake_ids: list[str] = Field(min_length=1, max_length=50)


@app.post("/api/admin/intakes/recognize-batch")
def recognize_batch(payload: BatchRecognizeIn):
    provider = recognition_provider()
    results = []
    for item_id in payload.intake_ids:
        try:
            results.append(recognize_intake_with_provider(item_id, provider))
        except HTTPException as error:
            results.append({
                "id": item_id,
                "status": "ERROR",
                "error": {"status_code": error.status_code, "detail": error.detail},
            })
    return results
