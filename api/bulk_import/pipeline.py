"""PDF extraction to the V0.1 exchange contract, without database writes."""

from __future__ import annotations

import hashlib
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ai import ModelError
from .contract import SCHEMA_VERSION
from .pdf import normalize_formula, read_pages, related_assets, split_questions
from .storage import atomic_json, write_items


def _guess_type(stem: str) -> str | None:
    for needle, result in (("计算", "计算题"), ("求", "计算题"),
                           ("简述", "简答题"), ("解释", "简答题"),
                           ("论述", "论述题")):
        if needle in stem:
            return result
    return None


def _local_topic(stem: str, topics: list[dict[str, str]]) -> str | None:
    matches = [topic["id"] for topic in topics if topic["name"] in stem]
    return matches[0] if len(matches) == 1 else None


def prepare(pdf_path: Path, out_dir: Path, *, source_name: str, source_kind: str,
            target_id: str, exam_year: int | None, source_url: str | None,
            tasks, topics: list[dict[str, str]]) -> dict[str, Any]:
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise ValueError("需要存在的 PDF 文件")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("输出目录非空；为保护人工修改稿，请使用新目录")
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    source_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    source_asset = f"assets/source-{source_hash}.pdf"
    shutil.copyfile(pdf_path, out_dir / source_asset)
    pages, page_errors = read_pages(pdf_path, assets_dir, tasks)
    questions, answers = split_questions(pages)
    expanded: list[dict[str, Any]] = []
    for question in questions:
        if question["number"] is None and len(question["text"]) >= 80:
            try:
                suggestions = tasks.structure(question["text"])
            except ModelError:
                suggestions = []
            if len(suggestions) > 1:
                for suggestion in suggestions:
                    child = deepcopy(question)
                    child["raw_text"] = question["text"]
                    child["text"] = suggestion["stem"]
                    child["warnings"].append("模型拆题共用原始页面区域，须核对边界和图表归属")
                    expanded.append(child)
                continue
        expanded.append(question)
    questions = expanded
    items: list[dict[str, Any]] = []
    for ordinal, question in enumerate(questions, 1):
        stem_raw = question.get("raw_text", question["text"])
        stem_latex, latex_fragments = normalize_formula(question["text"])
        answer_info = answers.get(question["number"] or "")
        source_answer = {
            "status": "PRESENT" if answer_info else "ABSENT",
            "kind": "REFERENCE" if answer_info else "NONE",
            "text": "\n".join(answer_info["lines"]).strip() if answer_info else "",
            "analysis": "", "human_verified": False,
            "evidence": [{"file_sha256": source_hash, "page": page, "note": "PDF 答案段落，类型待人工核对"}
                         for page in answer_info["pages"]] if answer_info else [],
        }
        first_page = question["regions"][0]["page"]
        item_key = hashlib.sha256(f"{source_hash}:{ordinal}:{first_page}:{question['number']}".encode()).hexdigest()[:24]
        runs_before = len(tasks.runs)
        assets = related_assets(question, pages)
        if assets:
            ai = {"status": "PENDING", "answer": "", "analysis": "", "provider": None,
                  "error": "题目含图表；当前答案适配器未接收视觉上下文"}
        else:
            try:
                generated = tasks.answer(stem_latex)
                ai = {"status": "MOCK" if type(tasks).__name__ == "MockTasks" else "SUCCEEDED",
                      "answer": generated["answer"], "analysis": generated["analysis"],
                      "provider": "mock" if type(tasks).__name__ == "MockTasks" else "doubao-ark"}
            except ModelError as exc:
                ai = {"status": "PENDING", "answer": "", "analysis": "", "provider": None, "error": str(exc)}
        topic_id = _local_topic(stem_latex, topics)
        question_type = _guess_type(stem_latex)
        difficulty = None
        if not topic_id or not question_type:
            try:
                suggestion = tasks.recommend(stem_latex, topics)
                topic_id = topic_id or suggestion.get("topic_id")
                question_type = question_type or (suggestion.get("question_type") if suggestion.get("question_type") in
                                                  {"名词解释", "选择/填空", "简答题", "论述题", "计算题"} else None)
                difficulty = suggestion.get("difficulty")
            except ModelError:
                pass
        warnings = list(question["warnings"])
        if latex_fragments:
            warnings.append("公式由保守规则转换，需人工核对 LaTeX")
        if any(page["scanned"] for page in pages if page["page"] in {r["page"] for r in question["regions"]}):
            warnings.append("扫描页题目/图形关联需人工核对")
        if assets:
            warnings.append("图表已按页面纵向位置关联；答案模型未接收视觉信息，AI 答案保持 PENDING")
        items.append({
            "schema_version": SCHEMA_VERSION, "item_key": item_key,
            "source": {"kind": source_kind, "name": source_name, "url": source_url,
                       "file_name": pdf_path.name, "file_sha256": source_hash,
                       "pages": sorted({region["page"] for region in question["regions"]}),
                       "exam_year": exam_year, "is_demo": False},
            "exam_scope": {"target_id": target_id},
            "content": {"stem_raw": stem_raw, "stem_latex": stem_latex,
                        "subquestions": question["subquestions"], "latex_fragments": latex_fragments,
                        "assets": assets},
            "source_answer": source_answer, "ai_answer": ai,
            "classification": {"topic_id": topic_id, "question_type": question_type,
                               "difficulty": difficulty},
            "validation": {"errors": [], "warnings": warnings, "duplicate_candidates": []},
            "processing_meta": {"pipeline_version": SCHEMA_VERSION, "method": "pdfplumber-local",
                                "question_number": question["number"], "regions": question["regions"],
                                "model_runs": tasks.runs[runs_before:]},
        })
    manifest = {"schema_version": SCHEMA_VERSION, "source_file": pdf_path.name,
                "source_sha256": source_hash, "source_asset": source_asset,
                "page_count": len(pages), "question_count": len(items),
                "page_errors": page_errors, "created_at": datetime.now(timezone.utc).isoformat(),
                "source_name": source_name, "target_id": target_id,
                "model_runs": tasks.runs,
                "estimated_model_cost": round(sum(run["estimated_cost"] for run in tasks.runs
                                                  if isinstance(run.get("estimated_cost"), (int, float))), 8)}
    write_items(out_dir, items)
    atomic_json(out_dir / "manifest.json", manifest)
    atomic_json(out_dir / "progress.json", {"schema_version": SCHEMA_VERSION,
                                           "items": {item["item_key"]: {"status": "PENDING", "attempts": 0}
                                                     for item in items}, "page_errors": page_errors})
    return manifest
