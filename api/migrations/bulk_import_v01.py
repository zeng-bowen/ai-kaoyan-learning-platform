"""V0.1 PDF import metadata; legacy answers deliberately remain UNKNOWN."""


def migrate(con):
    columns = {row["name"] for row in con.execute("PRAGMA table_info(questions)")}
    if "source_answer_kind" not in columns:
        con.execute("ALTER TABLE questions ADD COLUMN source_answer_kind TEXT NOT NULL DEFAULT 'UNKNOWN'")
    if "ai_answer_json" not in columns:
        con.execute("ALTER TABLE questions ADD COLUMN ai_answer_json TEXT")
    if "import_meta_json" not in columns:
        con.execute("ALTER TABLE questions ADD COLUMN import_meta_json TEXT")
