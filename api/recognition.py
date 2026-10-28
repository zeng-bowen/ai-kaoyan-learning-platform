"""Provider boundary for future domestic-model question image recognition.

Implement RecognitionProvider in a separately configured module. Its output is
only an administrator-visible suggestion and must never publish a question.
"""

from importlib import import_module
from typing import Protocol
import os

from pydantic import BaseModel, Field


class RecognitionCandidate(BaseModel):
    stem: str = Field(min_length=1)
    subject: str = ""
    difficulty: int | None = Field(default=None, ge=1, le=5)
    answer: str = ""
    analysis: str = ""
    question_type: str = ""
    confidence_note: str = ""


class RecognitionProvider(Protocol):
    def recognize(self, image_bytes: bytes, mime_type: str) -> list[RecognitionCandidate]: ...


def configured_provider() -> RecognitionProvider | None:
    """Load a local provider factory named by ECON_RECOGNITION_PROVIDER=module:factory."""
    spec = os.environ.get("ECON_RECOGNITION_PROVIDER", "").strip()
    if not spec:
        return None
    module_name, separator, factory_name = spec.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("ECON_RECOGNITION_PROVIDER must be module:factory")
    factory = getattr(import_module(module_name), factory_name)
    return factory()
