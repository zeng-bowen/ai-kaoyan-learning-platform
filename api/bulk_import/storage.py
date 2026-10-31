"""Atomic JSONL and progress-file operations for resumable local batches."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_items(batch_dir: Path) -> list[dict[str, Any]]:
    path = batch_dir / "questions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_items(batch_dir: Path, items: list[dict[str, Any]], *, filename: str = "questions.jsonl") -> None:
    if filename not in {"questions.jsonl", "pilot.jsonl"}:
        raise ValueError("unsupported JSONL output")
    path = batch_dir / filename
    temp = path.with_suffix(".jsonl.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
