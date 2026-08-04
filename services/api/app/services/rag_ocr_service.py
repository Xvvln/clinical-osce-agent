from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from typing import Any

from PIL import Image, ImageSequence, UnidentifiedImageError

DEFAULT_OCR_MIN_CONFIDENCE = 0.5
MAX_OCR_IMAGE_PIXELS = 24_000_000
MAX_OCR_IMAGE_FRAMES = 20


class RagOcrError(ValueError):
    pass


@dataclass(frozen=True)
class RagOcrPage:
    page_number: int
    text: str
    mean_confidence: float
    line_count: int


_OCR_CALL_LOCK = threading.Lock()


def recognize_image_pages(content_bytes: bytes) -> list[RagOcrPage]:
    """Recognize one image or every frame of a multi-frame image locally."""
    if not content_bytes:
        raise RagOcrError("OCR image content is empty")

    try:
        with Image.open(BytesIO(content_bytes)) as image:
            frame_count = int(getattr(image, "n_frames", 1) or 1)
            if frame_count > MAX_OCR_IMAGE_FRAMES:
                raise RagOcrError(
                    f"OCR image has too many frames; maximum is {MAX_OCR_IMAGE_FRAMES}"
                )
            pages: list[RagOcrPage] = []
            for page_number, frame in enumerate(ImageSequence.Iterator(image), start=1):
                _validate_image_size(frame)
                stream = BytesIO()
                frame.convert("RGB").save(stream, format="PNG")
                page = recognize_image(stream.getvalue(), page_number=page_number)
                if page.text:
                    pages.append(page)
    except RagOcrError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RagOcrError("image could not be decoded for OCR") from exc
    return pages


def recognize_image(content_bytes: bytes, *, page_number: int = 1) -> RagOcrPage:
    """Run RapidOCR and return confidence-filtered text in reading order."""
    engine = _build_ocr_engine()
    try:
        with _OCR_CALL_LOCK:
            output = engine(content_bytes, text_score=_ocr_min_confidence())
    except Exception as exc:
        raise RagOcrError("local OCR failed to process the image") from exc

    texts = list(getattr(output, "txts", None) or [])
    scores = list(getattr(output, "scores", None) or [])
    accepted: list[tuple[str, float]] = []
    threshold = _ocr_min_confidence()
    for index, raw_text in enumerate(texts):
        text = " ".join(str(raw_text).split()).strip()
        score = _safe_float(scores[index] if index < len(scores) else 1.0)
        if text and score >= threshold:
            accepted.append((text, score))
    return RagOcrPage(
        page_number=page_number,
        text="\n".join(text for text, _ in accepted),
        mean_confidence=(
            round(sum(score for _, score in accepted) / len(accepted), 4)
            if accepted
            else 0.0
        ),
        line_count=len(accepted),
    )


def image_to_png_bytes(image: Image.Image) -> bytes:
    _validate_image_size(image)
    stream = BytesIO()
    image.convert("RGB").save(stream, format="PNG")
    return stream.getvalue()


@lru_cache(maxsize=1)
def _build_ocr_engine() -> Any:
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:  # pragma: no cover - dependency is required by pyproject
        raise RagOcrError("local OCR dependency rapidocr is not installed") from exc
    try:
        return RapidOCR()
    except Exception as exc:
        raise RagOcrError("local OCR engine could not be initialized") from exc


def _validate_image_size(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise RagOcrError("OCR image has invalid dimensions")
    if width * height > MAX_OCR_IMAGE_PIXELS:
        raise RagOcrError(
            f"OCR image is too large; maximum is {MAX_OCR_IMAGE_PIXELS} pixels"
        )


def _ocr_min_confidence() -> float:
    raw_value = os.getenv("OSCE_RAG_OCR_MIN_CONFIDENCE", "").strip()
    if not raw_value:
        return DEFAULT_OCR_MIN_CONFIDENCE
    try:
        value = float(raw_value)
    except ValueError:
        return DEFAULT_OCR_MIN_CONFIDENCE
    return value if 0 <= value <= 1 else DEFAULT_OCR_MIN_CONFIDENCE


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
