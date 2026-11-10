"""Synthetic, temporary PDF smoke test; no real exam material is committed."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from api.bulk_import.ai import MockTasks
from api.bulk_import.pipeline import prepare
from api.bulk_import.pdf import read_pages, related_assets, split_questions
from api.bulk_import.storage import read_items, read_json


def minimal_pdf(text: str, graphic: bool = False) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    if graphic:
        stream += b"\n100 500 m 220 500 l S 100 500 m 100 620 l S"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    startxref = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF".encode("ascii"))
    return bytes(content)


class _NoVision:
    def vision(self, image_bytes, mime_type):
        raise AssertionError("Text PDF should not call vision")


@unittest.skipUnless(importlib.util.find_spec("pdfplumber"), "pdfplumber is not installed")
class PdfExtractionTests(unittest.TestCase):
    def test_read_text_pdf_and_preserve_page_number(self):
        test_data = Path(__file__).resolve().parents[2] / "data"
        test_data.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_data, ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            path = root / "synthetic.pdf"
            path.write_bytes(minimal_pdf("1. Explain demand elasticity in microeconomics."))
            pages, errors = read_pages(path, root / "assets", _NoVision())
            self.assertEqual(errors, [])
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0]["page"], 1)
            questions, _ = split_questions(pages)
            self.assertEqual(len(questions), 1)
            self.assertIn("demand elasticity", questions[0]["text"])

    def test_prepare_creates_four_outputs_without_real_model(self):
        test_data = Path(__file__).resolve().parents[2] / "data"
        test_data.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_data, ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            path = root / "synthetic.pdf"
            path.write_bytes(minimal_pdf("1. Explain demand elasticity in microeconomics."))
            out = root / "batch"
            manifest = prepare(path, out, source_name="Synthetic fixture",
                               source_kind="CURATED_EXERCISE", target_id="test-target",
                               exam_year=None, source_url=None, tasks=MockTasks(), topics=[])
            self.assertEqual(manifest["question_count"], 1)
            self.assertTrue((out / "manifest.json").is_file())
            self.assertTrue((out / "questions.jsonl").is_file())
            self.assertTrue((out / "assets").is_dir())
            self.assertTrue((out / "progress.json").is_file())
            self.assertEqual(read_items(out)[0]["ai_answer"]["status"], "MOCK")
            self.assertEqual(read_json(out / "progress.json")["schema_version"], "0.1")
            self.assertTrue((out / "assets" / ("source-" + manifest["source_sha256"] + ".pdf")).is_file())

    def test_vector_graph_is_rendered_and_linked_to_question_region(self):
        test_data = Path(__file__).resolve().parents[2] / "data"
        test_data.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_data, ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            path = root / "graph.pdf"
            path.write_bytes(minimal_pdf("1. Analyze the effect of a shift in demand curve.", graphic=True))
            pages, errors = read_pages(path, root / "assets", _NoVision())
            self.assertEqual(errors, [])
            self.assertTrue(pages[0]["assets"])
            questions, _ = split_questions(pages)
            self.assertTrue(related_assets(questions[0], pages))


if __name__ == "__main__":
    unittest.main()
