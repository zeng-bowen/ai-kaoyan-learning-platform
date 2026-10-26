"""Local development API. Seed content is illustrative and never verified exam material."""

from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("ECON_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "platform.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
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
    """)
    if not con.execute("SELECT 1 FROM targets LIMIT 1").fetchone():
        con.executemany("INSERT INTO targets VALUES (?,?,?,?,?,?)", [
            ("demo-pku", "北京大学", "经济学相关专业（演示）", "专业课配置待核验", 2028, 0),
            ("demo-ruc", "中国人民大学", "经济学相关专业（演示）", "专业课配置待核验", 2028, 0),
            ("demo-sufe", "上海财经大学", "经济学相关专业（演示）", "专业课配置待核验", 2028, 0),
        ])
        con.executemany("INSERT INTO topics VALUES (?,?,?,?,?)", [
            ("consumer", "微观经济学", "消费者理论", "预算约束与最优选择", "用预算线与无差异曲线解释消费者的可行集合和内点最优条件。"),
            ("elasticity", "微观经济学", "需求理论", "价格弹性", "掌握弹性的定义、点弹性计算和经济含义。"),
            ("islm", "宏观经济学", "短期均衡", "IS–LM 模型", "识别商品市场与货币市场的均衡条件及政策冲击方向。"),
        ])
        con.executemany("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            ("q-consumer", "demo-pku", "consumer", "CURATED_EXERCISE", "平台原创演示题", "计算题", 2, "某消费者效用函数 U(x,y)=xy，收入为 120，x 与 y 的价格分别为 2 和 3。求最优消费组合。", "x=30，y=20。", "柯布–道格拉斯效用的支出份额各为 1/2：x=(120/2)/2=30，y=(120/2)/3=20。", "APPROVED"),
            ("q-elasticity", "demo-pku", "elasticity", "CURATED_EXERCISE", "平台原创演示题", "简答题", 2, "解释需求价格弹性的含义，并说明为什么它通常取负值。", "需求价格弹性衡量需求量对价格变化的敏感程度，通常因需求曲线向下倾斜而为负。", "可写出 E=(dQ/dP)·(P/Q)，并说明负号与其他条件不变的假设。", "APPROVED"),
            ("q-islm", "demo-ruc", "islm", "CURATED_EXERCISE", "平台原创演示题", "图形分析题", 3, "在 IS–LM 框架中，其他条件不变时，扩张性财政政策会如何影响 IS 曲线与均衡利率？", "IS 曲线右移，均衡利率一般上升。", "政府支出增加使给定利率下总需求提高，IS 右移。均衡产出和利率的变化取决于曲线斜率。", "APPROVED"),
        ])

app = FastAPI(title="经研 API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def rows(sql: str, params: tuple = ()):
    with db() as con:
        return [dict(row) for row in con.execute(sql, params).fetchall()]


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "local-development"}


@app.get("/api/targets")
def targets():
    return rows("SELECT * FROM targets ORDER BY school")


@app.get("/api/topics")
def topics():
    return rows("SELECT * FROM topics ORDER BY subject,module,name")


@app.get("/api/questions")
def questions(target_id: str | None = None, admin: bool = False):
    clause = "WHERE target_id=?" if target_id else "WHERE 1=1"
    params = (target_id,) if target_id else ()
    if not admin:
        clause += " AND review_status='APPROVED'"
    return rows(f"SELECT * FROM questions {clause} ORDER BY id", params)


class AttemptIn(BaseModel):
    question_id: str
    answer_text: str = Field(min_length=1, max_length=10000)
    self_rating: int = Field(ge=0, le=3)


@app.post("/api/attempts")
def create_attempt(payload: AttemptIn):
    question = rows("SELECT id,review_status FROM questions WHERE id=?", (payload.question_id,))
    if not question or question[0]["review_status"] != "APPROVED":
        raise HTTPException(404, "题目不可作答")
    with db() as con:
        cur = con.execute("INSERT INTO attempts(user_id,question_id,answer_text,self_rating,created_at) VALUES (?,?,?,?,?)", ("local-demo", payload.question_id, payload.answer_text, payload.self_rating, datetime.now(timezone.utc).isoformat()))
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


class QuestionIn(BaseModel):
    id: str = Field(min_length=3, max_length=100)
    target_id: str
    topic_id: str
    source_type: str
    source_name: str = Field(min_length=2)
    question_type: str
    difficulty: int = Field(ge=1, le=5)
    stem: str = Field(min_length=5)
    answer: str = Field(min_length=1)
    analysis: str = Field(min_length=1)


@app.post("/api/admin/questions")
def create_question(payload: QuestionIn):
    if payload.source_type not in {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM", "CURATED_EXERCISE", "AI_GENERATED"}:
        raise HTTPException(422, "无效的题目来源类型")
    if payload.source_type in {"TARGET_PAST_EXAM", "RELATED_PAST_EXAM"}:
        raise HTTPException(422, "真题须先建立可核验试卷来源；当前管理入口只收录练习题")
    if not rows("SELECT id FROM targets WHERE id=?", (payload.target_id,)) or not rows("SELECT id FROM topics WHERE id=?", (payload.topic_id,)):
        raise HTTPException(422, "目标或知识点不存在")
    try:
        with db() as con:
            con.execute("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                payload.id, payload.target_id, payload.topic_id, payload.source_type,
                payload.source_name, payload.question_type, payload.difficulty,
                payload.stem, payload.answer, payload.analysis, "DRAFT"
            ))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "题目 ID 已存在")
    return {"id": payload.id, "review_status": "DRAFT"}


@app.post("/api/admin/questions/{question_id}/approve")
def approve_question(question_id: str):
    with db() as con:
        cur = con.execute("UPDATE questions SET review_status='APPROVED' WHERE id=?", (question_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "题目不存在")
    return {"id": question_id, "review_status": "APPROVED"}
