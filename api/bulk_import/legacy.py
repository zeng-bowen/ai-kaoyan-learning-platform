"""Read-only legacy candidate audit and V0.1 export; never updates the source DB."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import struct
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract import SCHEMA_VERSION, sha256_file, stem_fingerprint, validate_item
from .pdf import normalize_formula
from .storage import atomic_json, write_items

KINDS = ("READY", "NORMALIZE_ONLY", "NEED_SPLIT", "NEED_AI_ANSWER",
         "NEED_TAGGING", "NEED_VISION", "MANUAL_REVIEW")
QUESTION_TYPES = {"名词解释", "选择/填空", "简答题", "论述题", "计算题"}
PILOT = {
    "TEXT": [(2023, 1), (2023, 7), (2023, 9), (2022, 1), (2022, 8),
             (2021, 6), (2022, 10), (2012, 11)],
    "VISION": [(2019, 15), (2016, 8), (2014, 21), (2011, 17), (2004, 10)],
    "NEGATIVE": [(2019, 5), (2017, 4), (2014, 12)],
}
# Source-specific, evidence-checked triage from the first read-only audit. These
# annotations are warnings, not reconstructed exam questions or automatic truth.
RUC_SHA = "bc00984c4448bc77b9bddb70da83343360b19366dfe183cac77f8841110e0893"
RUC_SPLIT = {(2020, 15), (2019, 14), (2019, 26)}
RUC_DIAGRAM = {(2019, 15), (2016, 8), (2014, 21), (2012, 22), (2011, 17), (2004, 10)}
RUC_CONTEXT = {(2017, 4), (2014, 12)}
RUC_SUMMARY = {(2019, n) for n in (*range(5, 14), *range(20, 26))}
OCR_MINUS = re.compile(r"(?<=[A-Za-z0-9])一(?=[A-Za-z0-9])")
LEADING_NUMBER = re.compile(r"^\s*(?:第\s*)?(\d{1,3})\s*(?:题)?[、．.。]\s*")
SUBQUESTION = re.compile(r"(?m)^\s*[（(](\d{1,2})[）)]\s*")
SECTION = re.compile(r"(?m)^\s*[一二三四五六七八九十]+[、．.]\s*(?:名词解释|简答|论述|计算|分析|选择|多项选择)")


def _read_legacy(db_path: Path, target_id: str | None, source_contains: str | None,
                 years: list[int] | None) -> tuple[list[dict], dict[str, dict], set[tuple[str, str]]]:
    if not db_path.is_file():
        raise FileNotFoundError("指定 SQLite 不存在")
    con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        needed = {"pdf_imports", "pdf_question_candidates", "targets"}
        present = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not needed <= present:
            raise ValueError("数据库缺少历史 PDF 候选表")
        sql = ("SELECT c.*,i.original_name,i.stored_name,i.sha256,i.page_count,t.school,t.exam_label "
               "FROM pdf_question_candidates c JOIN pdf_imports i ON i.id=c.import_id "
               "JOIN targets t ON t.id=c.target_id WHERE 1=1")
        params: list[Any] = []
        if target_id:
            sql += " AND c.target_id=?"
            params.append(target_id)
        if source_contains:
            sql += " AND i.original_name LIKE ?"
            params.append("%" + source_contains + "%")
        if years:
            sql += " AND c.exam_year IN (" + ",".join("?" for _ in years) + ")"
            params.extend(years)
        sql += " ORDER BY c.exam_year DESC,c.sequence,c.id"
        rows = [dict(row) for row in con.execute(sql, params)]
        imports = {row["id"]: dict(row) for row in con.execute("SELECT * FROM pdf_imports")}
        topics = {(row[0], row[1]) for row in con.execute(
            "SELECT topic_id,target_id FROM topic_target_tags")}
        return rows, imports, topics
    finally:
        con.close()


def _segments(raw: str) -> list[dict]:
    try:
        segments = json.loads(raw or "[]")
    except ValueError:
        return []
    return [part for part in segments if isinstance(part, dict) and type(part.get("page")) is int]


def _text(stem: str) -> tuple[str, list[dict], list[str]]:
    text = (stem or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = LEADING_NUMBER.sub("", text, count=1)
    text = SUBQUESTION.sub(lambda m: "（" + m.group(1) + "）", text)
    latex, fragments = normalize_formula(text)
    subquestions = []
    matches = list(re.finditer(r"(?:^|\n)（(\d{1,2})）", latex))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(latex)
        subquestions.append({"label": match.group(1), "text": latex[match.end():end].strip()})
    return latex, subquestions, fragments


def _type(value: str | None) -> str | None:
    value = (value or "").strip()
    if value in QUESTION_TYPES:
        return value
    if re.sub(r"\s+", "", value) == "选择/填空":
        return "选择/填空"
    return None


def _triage(row: dict) -> tuple[str, str]:
    key = (row["exam_year"], row["sequence"])
    ruc = row["sha256"] == RUC_SHA
    stem = row["stem"] or ""
    answer = (row["answer"] or "").strip()
    if (ruc and key in RUC_SUMMARY) or (ruc and key in RUC_CONTEXT):
        return "MANUAL_REVIEW", "INCOMPLETE_SOURCE"
    if not ruc and not answer and len(stem) < 45 and ("相关考题" in stem or "相关题" in stem):
        return "MANUAL_REVIEW", "INCOMPLETE_SOURCE"
    if not answer and re.match(r"^\s*[一二三四五六七八九十]+[、．.]", stem):
        return "MANUAL_REVIEW", "SECTION_HEADING_ONLY"
    if ruc and key in RUC_SPLIT:
        return "NEED_SPLIT", "MIXED_BOUNDARY_OR_ANSWER"
    if not ruc and any(match.start() > 0 for match in SECTION.finditer(stem)):
        return "NEED_SPLIT", "MIXED_BOUNDARY_OR_ANSWER"
    if (ruc and key in RUC_DIAGRAM) or OCR_MINUS.search(stem):
        return "NEED_VISION", "VISUAL_OR_FORMULA_CONTEXT"
    normalized, subs, fragments = _text(stem)
    if "\n" in stem or "  " in stem or subs or fragments:
        return "NORMALIZE_ONLY", "LOCAL_FORMAT"
    if not row["topic_id"] or not _type(row["question_type"]):
        return "NEED_TAGGING", "MISSING_OR_UNKNOWN_TAG"
    return "NEED_AI_ANSWER", "NO_INDEPENDENT_AI_ANSWER"


def _split_attempt(row: dict) -> dict:
    stem = row["stem"] or ""
    headings = [m for m in SECTION.finditer(stem) if m.start() > 0]
    if not headings and SECTION.search(row["answer"] or ""):
        return {"result": "NEED_AI_SPLIT", "reason": "题目/答案混入下一节；答案归属不可靠"}
    if headings:
        return {"result": "NEED_AI_SPLIT", "reason": "找到下一节标题，但题干与来源答案归属不可靠",
                "boundary_offset": headings[0].start()}
    return {"result": "NEED_AI_SPLIT", "reason": "未找到可高置信自动拆分的独立题号与答案"}


def audit(db_path: Path, target_id: str | None = None, source_contains: str | None = None,
          years: list[int] | None = None) -> dict:
    rows, _, _ = _read_legacy(db_path, target_id, source_contains, years)
    classes = Counter(_triage(row)[0] for row in rows)
    fingerprints = Counter(stem_fingerprint(_text(row["stem"])[0]) for row in rows)
    return {"total": len(rows), "by_year": dict(sorted(Counter(row["exam_year"] for row in rows).items(), reverse=True)),
            "classes": {kind: classes[kind] for kind in KINDS},
            "duplicate_groups": sum(count > 1 for count in fingerprints.values()),
            "duplicate_members": sum(count for count in fingerprints.values() if count > 1),
            "source_answer_present": sum(bool((row["answer"] or "").strip()) for row in rows),
            "topic_present": sum(bool(row["topic_id"]) for row in rows),
            "type_present": sum(bool(_type(row["question_type"])) for row in rows),
            "difficulty_default_three": sum(row["difficulty"] == 3 for row in rows),
            "difficulty_other_unverified": sum(row["difficulty"] != 3 for row in rows),
            "ai_answer_present": 0,
            "source_database_read_only": str(db_path.resolve())}


def _source_path(db_path: Path, imp: dict) -> Path:
    path = db_path.parent / "pdf-imports" / imp["stored_name"]
    if not path.is_file():
        raise FileNotFoundError("原始 PDF 缺失：" + str(path))
    if sha256_file(path) != imp["sha256"]:
        raise ValueError("原始 PDF 哈希与数据库记录不一致")
    return path


def _visual_assets(pdf: Path, out: Path, segments: list[dict], cache: dict[int, Path]) -> list[dict]:
    assets = []
    for index, part in enumerate(segments):
        page = part["page"]
        if page not in cache:
            prefix = out / "assets" / f"legacy-page-{page:04d}"
            subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-scale-to", "1500",
                            "-png", "-singlefile", str(pdf), str(prefix)], check=True,
                           capture_output=True, timeout=120)
            cache[page] = prefix.with_suffix(".png")
        with cache[page].open("rb") as stream:
            header = stream.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("页面渲染不是 PNG")
        width, height = struct.unpack(">II", header[16:24])
        top, bottom = part.get("top"), part.get("bottom")
        reliable = (type(top) is int and type(bottom) is int and 0 <= top < bottom <= height
                    and bottom - top < height * .85)
        box = [0, top, width, bottom] if reliable else [0, 0, width, height]
        name = f"legacy-region-p{page:04d}-{index:02d}-{hashlib.sha256(str(part).encode()).hexdigest()[:8]}.png"
        path = out / "assets" / name
        if reliable:
            subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-scale-to", "1500",
                            "-x", "0", "-y", str(top), "-W", str(width), "-H", str(bottom - top),
                            "-png", "-singlefile", str(pdf), str(path.with_suffix(""))],
                           check=True, capture_output=True, timeout=120)
        else:
            shutil.copyfile(cache[page], path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        assets.append({"asset_id": name, "path": "assets/" + name, "sha256": sha,
                       "mime_type": "image/png", "kind": "PAGE_REGION_UNVERIFIED" if reliable else "FULL_PAGE_REVIEW",
                       "page": page, "bbox": box, "alt_text": "来源 PDF 页面区域，待人工核验"})
        if reliable:
            full = cache[page]
            assets.append({"asset_id": full.name, "path": "assets/" + full.name,
                           "sha256": hashlib.sha256(full.read_bytes()).hexdigest(),
                           "mime_type": "image/png", "kind": "FULL_PAGE_REVIEW",
                           "page": page, "bbox": [0, 0, width, height],
                           "alt_text": "原始 PDF 整页，用于核对局部裁剪是否遗漏图表"})
    return assets


def normalize(db_path: Path, out: Path, target_id: str | None = None,
              source_contains: str | None = None, years: list[int] | None = None) -> dict:
    if out.exists() and any(out.iterdir()):
        raise ValueError("输出目录非空；请使用新目录保护已有人工修改")
    rows, imports, topics = _read_legacy(db_path, target_id, source_contains, years)
    if not rows:
        raise ValueError("筛选后无历史候选")
    if len({row["import_id"] for row in rows}) != 1:
        raise ValueError("每个批次只允许一个来源 PDF，请收窄 source 筛选")
    imp = imports[rows[0]["import_id"]]
    pdf = _source_path(db_path, imp)
    out.mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir()
    source_asset = "assets/source-" + imp["sha256"] + ".pdf"
    shutil.copyfile(pdf, out / source_asset)
    if sha256_file(out / source_asset) != imp["sha256"]:
        raise ValueError("复制后的原始 PDF 哈希不匹配")
    manifest = {"schema_version": SCHEMA_VERSION, "source_file": imp["original_name"],
                "source_sha256": imp["sha256"], "source_asset": source_asset,
                "page_count": imp["page_count"], "question_count": len(rows),
                "source_name": imp["original_name"], "target_id": rows[0]["target_id"],
                "method": "legacy-local-rules", "created_at": datetime.now(timezone.utc).isoformat(),
                "model_runs": []}
    atomic_json(out / "manifest.json", manifest)
    items: list[dict] = []
    classes = Counter()
    split_attempts = []
    cached_pages: dict[int, Path] = {}
    for row in rows:
        classification, reason = _triage(row)
        classes[classification] += 1
        stem, subquestions, fragments = _text(row["stem"])
        segments = _segments(row["stem_segments_json"])
        answer_segments = _segments(row["answer_segments_json"])
        pages = sorted({part["page"] for part in segments})
        if classification == "NEED_SPLIT":
            split_attempts.append({"candidate_id": row["id"], **_split_attempt(row)})
        assets = _visual_assets(pdf, out, segments, cached_pages) if classification == "NEED_VISION" else []
        kind = _type(row["question_type"])
        answer = (row["answer"] or "").strip()
        source_analysis = (row["analysis"] or "").strip()
        warnings = ["原始资料和答案均待人工核验；不得标为官方答案",
                    "历史难度 3 为默认值，待重新评估"]
        if not kind:
            warnings.append("题型缺失或不在固定集合，待人工选择")
        if fragments:
            warnings.append("保守公式转换建议，需与原图核对")
        if classification == "NEED_VISION":
            warnings.append("视觉内容未送入答案模型，AI 答案保持 PENDING")
        if classification in {"MANUAL_REVIEW", "NEED_SPLIT"}:
            warnings.append("原始题面或题目/答案边界不可靠，不得自动补造")
        item = {
            "schema_version": SCHEMA_VERSION,
            "item_key": "legacy-" + hashlib.sha256(row["id"].encode()).hexdigest()[:24],
            "source": {"kind": "TARGET_PAST_EXAM", "name": row["original_name"], "url": None,
                       "file_name": row["original_name"], "file_sha256": imp["sha256"],
                       "pages": pages, "exam_year": row["exam_year"], "is_demo": False,
                       "human_verified": False},
            "exam_scope": {"target_id": row["target_id"]},
            "content": {"stem_raw": row["stem"], "stem_latex": stem,
                        "subquestions": subquestions, "latex_fragments": fragments, "assets": assets},
            "source_answer": {"status": "PRESENT" if answer else "ABSENT",
                              "kind": "REFERENCE" if answer else "NONE", "text": answer,
                              "analysis": source_analysis if source_analysis != answer else "",
                              "human_verified": False,
                              "evidence": [{"file_sha256": imp["sha256"], "page": part["page"],
                                            "note": "历史 OCR 答案区域；待人工核验"} for part in answer_segments]},
            "ai_answer": {"status": "PENDING", "answer": "", "analysis": "", "provider": None},
            "classification": {"topic_id": row["topic_id"] if (row["topic_id"], row["target_id"]) in topics else None,
                               "question_type": kind, "difficulty": None},
            "validation": {"errors": [], "warnings": warnings, "duplicate_candidates": []},
            "processing_meta": {"pipeline_version": SCHEMA_VERSION, "method": "legacy-local-rules",
                                "legacy_candidate_id": row["id"], "legacy_status": classification,
                                "legacy_reason": reason, "legacy_gate": "BLOCKED" if classification in
                                {"MANUAL_REVIEW", "NEED_SPLIT", "NEED_VISION"} else "READY_FOR_ENRICHMENT",
                                "question_number": row["question_number"], "regions": segments,
                                "answer_regions": answer_segments,
                                "stem_fingerprint": stem_fingerprint(stem), "model_runs": []},
        }
        items.append(item)
    fingerprints: dict[str, str] = {}
    duplicate_groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        fp = item["processing_meta"]["stem_fingerprint"]
        duplicate_groups[fp].append(item["item_key"])
        if fp in fingerprints:
            item["validation"]["warnings"].append("疑似本批重复题：" + fingerprints[fp])
            item["validation"]["duplicate_candidates"].append(fingerprints[fp])
        else:
            fingerprints[fp] = item["item_key"]
        errors, warnings = validate_item(item, out, verified_source_hash=imp["sha256"])
        if item["validation"]["duplicate_candidates"]:
            warnings.append("疑似本批重复题：" + item["validation"]["duplicate_candidates"][0])
        item["validation"] = {"errors": errors, "warnings": warnings,
                              "duplicate_candidates": item["validation"]["duplicate_candidates"]}
    pilot = []
    by_year_seq = {(row["exam_year"], row["sequence"]): item for row, item in zip(rows, items)}
    for group, pairs in PILOT.items():
        for year, sequence in pairs:
            item = by_year_seq.get((year, sequence))
            if item:
                pilot.append({"group": group, "year": year, "sequence": sequence,
                              "item_key": item["item_key"], "legacy_candidate_id": item["processing_meta"]["legacy_candidate_id"],
                              "legacy_status": item["processing_meta"]["legacy_status"]})
    write_items(out, items)
    manifest.update({"classes": {kind: classes[kind] for kind in KINDS}, "split_attempts": split_attempts,
                     "duplicate_groups": [keys for keys in duplicate_groups.values() if len(keys) > 1]})
    atomic_json(out / "manifest.json", manifest)
    atomic_json(out / "progress.json", {"schema_version": SCHEMA_VERSION,
                "items": {item["item_key"]: {"status": "BLOCKED", "attempts": 0,
                         "errors": item["validation"]["errors"]} for item in items},
                "page_errors": []})
    atomic_json(out / "pilot-manifest.json", {"schema_version": SCHEMA_VERSION, "items": pilot})
    pilot_keys = {entry["item_key"] for entry in pilot}
    write_items(out, [item for item in items if item["item_key"] in pilot_keys], filename="pilot.jsonl")
    return {"total": len(items), "classes": {kind: classes[kind] for kind in KINDS},
            "locally_normalized_first": sum(classes[k] for k in ("NORMALIZE_ONLY", "NEED_TAGGING", "NEED_AI_ANSWER")),
            "split_attempts": split_attempts, "vision_assets": sum(len(x["content"]["assets"]) for x in items),
            "manual_review": classes["MANUAL_REVIEW"], "pilot": dict(Counter(x["group"] for x in pilot)),
            "duplicates": {"groups": sum(len(v) > 1 for v in duplicate_groups.values()),
                           "members": sum(len(v) for v in duplicate_groups.values() if len(v) > 1)}}
