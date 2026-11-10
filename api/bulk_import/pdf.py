"""Conservative local PDF extraction. Ambiguous layout is flagged for review."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any


QUESTION_START = re.compile(r"^\s*(?:第\s*(\d{1,3}|[一二三四五六七八九十]+)\s*题|([一二三四五六七八九十]+)[、．.]|(\d{1,3})[、．.])\s*(.*)$")
SUBQUESTION = re.compile(r"^\s*[（(]([一二三四五六七八九十\d]+)[）)]\s*(.*)$")
ANSWER_HEADING = re.compile(r"^\s*(?:参考答案(?:与解析)?|答案及解析|答案|解析)\s*[:：]?\s*$")
SECTION_HEADING = re.compile(r"^\s*[一二三四五六七八九十]+[、．.]\s*(?:名词解释|简答题?|论述题?|计算题?|选择题?|证明题?|图形分析题?)(?:\s*[（(].*[）)])?\s*$")
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
MATH_MAP = {"≤": r"\leq ", "≥": r"\geq ", "≠": r"\neq ", "×": r"\times ",
            "÷": r"\div ", "∂": r"\partial ", "∞": r"\infty ", "√": r"\sqrt ",
            "α": r"\alpha ", "β": r"\beta ", "Δ": r"\Delta "}


def normalize_formula(text: str) -> tuple[str, list[str]]:
    """Only lossless/common symbol rewrites; complex equations remain review-required."""
    fragments: list[str] = []

    def superscript(match: re.Match[str]) -> str:
        expr = match.group(1) + "^{" + match.group(2).translate(SUPERSCRIPTS) + "}"
        fragments.append(expr)
        return expr

    result = re.sub(r"([A-Za-z0-9)]+)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", superscript, text)
    for old, new in MATH_MAP.items():
        if old in result:
            result = result.replace(old, new)
            fragments.append(new.strip())
    fragments.extend(re.findall(r"\$([^$]+)\$", result))
    return result, fragments


def _save_png(image: Any, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _asset(page, page_number: int, image, bbox: tuple[float, float, float, float],
           assets_dir: Path, index: int, *, kind: str = "IMAGE") -> dict[str, Any] | None:
    x0, top, x1, bottom = bbox
    x0, top = max(0, x0), max(0, top)
    x1, bottom = min(page.width, x1), min(page.height, bottom)
    if x1 - x0 < 8 or bottom - top < 8:
        return None
    scale = image.width / page.width
    crop = image.crop(tuple(round(value * scale) for value in (x0, top, x1, bottom)))
    name = f"p{page_number:04d}-a{index:03d}.png"
    return {"asset_id": name, "path": "assets/" + name, "sha256": _save_png(crop, assets_dir / name),
            "mime_type": "image/png", "kind": kind, "page": page_number,
            "bbox": [round(x0, 2), round(top, 2), round(x1, 2), round(bottom, 2)],
            "alt_text": "PDF 第 " + str(page_number) + " 页图表，待人工描述"}


def read_pages(pdf_path: Path, assets_dir: Path, tasks) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("缺少 pdfplumber；请安装 api/requirements.txt") from exc

    pages: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as document:
        for number, page in enumerate(document.pages, 1):
            try:
                extracted = page.extract_text_lines(return_chars=False)
                lines = [{"text": line["text"].strip(), "top": float(line["top"]),
                          "bottom": float(line["bottom"])} for line in extracted if line["text"].strip()]
                sparse = len("".join(line["text"] for line in lines)) < 30
                images = list(page.images)
                # Curves are kept as reviewable raster regions; tiny text-decoration
                # lines/rectangles are not treated as diagrams.
                curves = [curve for curve in page.curves if
                          curve.get("x1", 0) - curve.get("x0", 0) > 35 and
                          curve.get("bottom", 0) - curve.get("top", 0) > 25]
                vector_region = None
                vectors = list(page.lines) + list(page.rects)
                if len(vectors) >= 2:
                    box = (min(float(v["x0"]) for v in vectors), min(float(v["top"]) for v in vectors),
                           max(float(v["x1"]) for v in vectors), max(float(v["bottom"]) for v in vectors))
                    if box[2] - box[0] > 60 and box[3] - box[1] > 60:
                        vector_region = {"x0": box[0], "top": box[1], "x1": box[2], "bottom": box[3]}
                has_graphics = bool(images or curves or vector_region)
                scanned = sparse and (has_graphics or not lines)
                assets: list[dict[str, Any]] = []
                if scanned or has_graphics:
                    raster = page.to_image(resolution=160).original
                    if scanned:
                        full = _asset(page, number, raster, (0, 0, page.width, page.height), assets_dir, 0)
                        if full:
                            assets.append(full)
                        try:
                            recognized = tasks.vision((assets_dir / full["asset_id"]).read_bytes(), "image/png") if full else []
                            if recognized:
                                step = page.height / (len(recognized) + 1)
                                lines = [{"text": str(item["stem"]), "top": step * (i + 1),
                                          "bottom": step * (i + 1) + 1, "vision_candidate": True}
                                         for i, item in enumerate(recognized) if item.get("stem")]
                            else:
                                errors.append({"page": number, "error": "扫描页无可识别题目；原页图已保留"})
                        except Exception as exc:
                            errors.append({"page": number, "error": "扫描页视觉识别待处理：" + str(exc)})
                    else:
                        regions = images + curves + ([vector_region] if vector_region else [])
                        for i, region in enumerate(regions, 1):
                            bbox = (float(region["x0"]), float(region["top"]),
                                    float(region["x1"]), float(region["bottom"]))
                            item = _asset(page, number, raster, bbox, assets_dir, i)
                            if item:
                                assets.append(item)
                pages.append({"page": number, "height": float(page.height), "lines": lines,
                              "assets": assets, "scanned": scanned})
            except Exception as exc:
                errors.append({"page": number, "error": "页面提取失败：" + type(exc).__name__})
                pages.append({"page": number, "height": float(page.height), "lines": [],
                              "assets": [], "scanned": True})
    return pages, errors


def _new_question(number: str | None, page: int, top: float, height: float, uncertain: bool = False) -> dict[str, Any]:
    return {"number": number, "lines": [], "subquestions": [], "regions": [{"page": page, "top": top, "bottom": height}],
            "warnings": ["题目边界由本地规则推定，需人工核对"] if uncertain else []}


def split_questions(pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Preserve order and carry active questions over page boundaries."""
    questions: list[dict[str, Any]] = []
    answers: dict[str, dict[str, Any]] = {}
    active: dict[str, Any] | None = None
    answer_mode = False
    answer_number: str | None = None
    for page in pages:
        page_number = page["page"]
        if active and active["regions"][-1]["page"] != page_number:
            active["regions"].append({"page": page_number, "top": 0.0, "bottom": page["height"]})
        for line in page["lines"]:
            text = line["text"].strip()
            if not answer_mode and SECTION_HEADING.match(text):
                continue
            if ANSWER_HEADING.match(text):
                answer_mode = True
                if active:
                    active["regions"][-1]["bottom"] = line["top"]
                    active = None
                continue
            matched = QUESTION_START.match(text)
            number = next((part for part in matched.groups()[:3] if part), None) if matched else None
            remainder = matched.group(4).strip() if matched else text
            if answer_mode:
                if number:
                    answer_number = number
                    answers.setdefault(number, {"lines": [], "pages": []})
                    if remainder:
                        answers[number]["lines"].append(remainder)
                elif answer_number:
                    answers[answer_number]["lines"].append(text)
                if answer_number and page_number not in answers[answer_number]["pages"]:
                    answers[answer_number]["pages"].append(page_number)
                continue
            if number or line.get("vision_candidate"):
                if active:
                    active["regions"][-1]["bottom"] = line["top"]
                active = _new_question(number, page_number, line["top"], page["height"],
                                       uncertain=bool(line.get("vision_candidate")))
                questions.append(active)
                if remainder:
                    inline_sub = SUBQUESTION.match(remainder)
                    if inline_sub:
                        active["subquestions"].append({"label": inline_sub.group(1), "text": inline_sub.group(2)})
                    else:
                        active["lines"].append(remainder)
            else:
                if active is None:
                    active = _new_question(None, page_number, line["top"], page["height"], uncertain=True)
                    questions.append(active)
                sub = SUBQUESTION.match(text)
                if sub:
                    active["subquestions"].append({"label": sub.group(1), "text": sub.group(2)})
                elif active["subquestions"]:
                    active["subquestions"][-1]["text"] += " " + text
                else:
                    active["lines"].append(text)
    for question in questions:
        question["text"] = "\n".join(question["lines"] +
                                      ["(" + sub["label"] + ") " + sub["text"] for sub in question["subquestions"]]).strip()
    return [question for question in questions if question["text"]], answers


def related_assets(question: dict[str, Any], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for region in question["regions"]:
        page = next(item for item in pages if item["page"] == region["page"])
        for asset in page["assets"]:
            top, bottom = asset["bbox"][1], asset["bbox"][3]
            midpoint = (top + bottom) / 2
            if region["top"] <= midpoint <= region["bottom"]:
                matches.append(asset)
    return matches
