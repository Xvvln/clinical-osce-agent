from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
TEMP_UPLOAD_DIR = ROOT_DIR / "data" / "runtime" / "rag_document_uploads"
MARKDOWN_SUFFIXES = {".md", ".markdown"}
TEXT_SUFFIXES = {".txt", ".text", ".csv"}


class RagDocumentParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedRagDocumentElement:
    text: str
    category: str
    section_title: str
    page_number: int | None
    element_index: int


@dataclass(frozen=True)
class RagDocumentChunk:
    document_id: str
    chunk_index: int
    text: str
    section_title: str
    page_number: int | None
    source_location: str
    chunking_strategy: str = "project_section_window"
    chunk_categories: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    char_count: int = 0


def generate_rag_document_id(*, case_id: str, file_name: str, content_bytes: bytes) -> str:
    safe_case_id = _safe_identifier(case_id)
    file_digest = hashlib.sha1(
        b"|".join([case_id.encode("utf-8"), Path(file_name).name.encode("utf-8"), content_bytes])
    ).hexdigest()[:16]
    return f"kbdoc:{safe_case_id}:{file_digest}"


def chunk_rag_document(
    *,
    file_name: str,
    content_bytes: bytes,
    document_id: str,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[RagDocumentChunk]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in MARKDOWN_SUFFIXES | TEXT_SUFFIXES:
        return _chunk_with_unstructured(
            file_name=file_name,
            content_bytes=content_bytes,
            document_id=document_id,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
    elements = parse_rag_document(file_name=file_name, content_bytes=content_bytes)
    return chunk_rag_document_elements(
        elements=elements,
        file_name=file_name,
        document_id=document_id,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )


def parse_rag_document(*, file_name: str, content_bytes: bytes) -> list[ParsedRagDocumentElement]:
    normalized_file_name = Path(file_name).name.strip()
    if not normalized_file_name:
        raise RagDocumentParseError("file_name is required")
    if not content_bytes:
        raise RagDocumentParseError("document content is empty")

    suffix = Path(normalized_file_name).suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return _parse_markdown_text(_decode_text(content_bytes))
    if suffix in TEXT_SUFFIXES:
        return _parse_plain_text(_decode_text(content_bytes))
    return _parse_with_unstructured(file_name=normalized_file_name, content_bytes=content_bytes)


def chunk_rag_document_elements(
    *,
    elements: list[ParsedRagDocumentElement],
    file_name: str,
    document_id: str,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[RagDocumentChunk]:
    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative")

    chunks: list[RagDocumentChunk] = []
    current_parts: list[str] = []
    current_categories: list[str] = []
    current_section = ""
    current_page: int | None = None
    previous_tail = ""

    def flush() -> None:
        nonlocal current_parts, current_categories, current_section, current_page, previous_tail
        chunk_body = "\n\n".join(part.strip() for part in current_parts if part.strip()).strip()
        if not chunk_body:
            current_parts = []
            current_categories = []
            return
        chunk_text = f"{previous_tail}\n\n{chunk_body}".strip() if previous_tail else chunk_body
        chunk_categories = _unique_strings(current_categories)
        chunk = RagDocumentChunk(
            document_id=document_id,
            chunk_index=len(chunks),
            text=chunk_text,
            section_title=current_section,
            page_number=current_page,
            source_location=_source_location(
                file_name=file_name,
                section_title=current_section,
                page_number=current_page,
                chunk_number=len(chunks) + 1,
            ),
            chunking_strategy="project_section_window",
            chunk_categories=chunk_categories,
            quality_warnings=_quality_warnings(chunk_text, section_title=current_section, categories=chunk_categories, max_chars=max_chars),
            risk_flags=_risk_flags(chunk_text, section_title=current_section),
            char_count=len(chunk_text),
        )
        chunks.append(chunk)
        previous_tail = _tail_window(chunk_body, overlap_chars)
        current_parts = []
        current_categories = []
        current_section = ""
        current_page = None

    for element in elements:
        text = element.text.strip()
        if not text:
            continue
        section_title = element.section_title.strip()
        if element.category.lower() == "title":
            section_title = text
        split_parts = _split_long_text(text, max_chars=max_chars)
        for part in split_parts:
            candidate_parts = [*current_parts, part]
            candidate_length = len("\n\n".join(candidate_parts))
            next_section = current_section or section_title
            next_page = current_page if current_page is not None else element.page_number
            if current_parts and candidate_length > max_chars:
                flush()
                next_section = section_title
                next_page = element.page_number
            current_parts.append(part)
            current_categories.append(element.category)
            current_section = next_section
            current_page = next_page

    flush()
    if not chunks:
        raise RagDocumentParseError("document contains no readable text")
    return chunks


def _chunk_with_unstructured(
    *,
    file_name: str,
    content_bytes: bytes,
    document_id: str,
    max_chars: int,
    overlap_chars: int,
) -> list[RagDocumentChunk]:
    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative")
    try:
        from unstructured.chunking.title import chunk_by_title
        from unstructured.partition.auto import partition
    except ImportError as exc:
        raise RagDocumentParseError(
            "document parser dependency is not installed; install unstructured for PDF/DOCX/HTML ingestion"
        ) from exc

    TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix.lower()
    temp_name = f"{hashlib.sha1(content_bytes).hexdigest()[:16]}{suffix}"
    temp_path = TEMP_UPLOAD_DIR / temp_name
    temp_path.write_bytes(content_bytes)
    partition_kwargs = {"strategy": "fast"} if suffix == ".pdf" else {}
    try:
        raw_elements = partition(filename=str(temp_path), **partition_kwargs)
    finally:
        temp_path.unlink(missing_ok=True)

    raw_chunks = chunk_by_title(
        raw_elements,
        max_characters=max_chars,
        new_after_n_chars=max(80, int(max_chars * 0.85)),
        combine_text_under_n_chars=max(40, min(500, int(max_chars * 0.35))),
        overlap=overlap_chars,
        include_orig_elements=True,
        multipage_sections=True,
    )
    chunks: list[RagDocumentChunk] = []
    for raw_chunk in raw_chunks:
        converted_chunk = _convert_unstructured_chunk(
            raw_chunk,
            file_name=file_name,
            document_id=document_id,
            chunk_index=len(chunks),
            max_chars=max_chars,
        )
        if converted_chunk is not None:
            chunks.append(converted_chunk)
    if not chunks:
        raise RagDocumentParseError("document contains no readable text")
    return chunks


def _convert_unstructured_chunk(
    raw_chunk: Any,
    *,
    file_name: str,
    document_id: str,
    chunk_index: int,
    max_chars: int,
) -> RagDocumentChunk | None:
    text = str(raw_chunk).strip()
    if not text:
        return None
    metadata = getattr(raw_chunk, "metadata", None)
    orig_elements = list(getattr(metadata, "orig_elements", []) or [])
    chunk_categories = _unique_strings(_element_category(element) for element in orig_elements) or [
        _element_category(raw_chunk) or raw_chunk.__class__.__name__
    ]
    section_title = _section_title_from_elements(orig_elements)
    page_number = _first_page_number(orig_elements) or _optional_int(getattr(metadata, "page_number", None))
    return RagDocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        text=text,
        section_title=section_title,
        page_number=page_number,
        source_location=_source_location(
            file_name=file_name,
            section_title=section_title,
            page_number=page_number,
            chunk_number=chunk_index + 1,
        ),
        chunking_strategy="unstructured_by_title",
        chunk_categories=chunk_categories,
        quality_warnings=_quality_warnings(text, section_title=section_title, categories=chunk_categories, max_chars=max_chars),
        risk_flags=_risk_flags(text, section_title=section_title),
        char_count=len(text),
    )


def _parse_markdown_text(text: str) -> list[ParsedRagDocumentElement]:
    elements: list[ParsedRagDocumentElement] = []
    current_section = ""
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_lines
        block = "\n".join(line.strip() for line in block_lines if line.strip()).strip()
        if block:
            elements.append(
                ParsedRagDocumentElement(
                    text=block,
                    category="NarrativeText",
                    section_title=current_section,
                    page_number=None,
                    element_index=len(elements),
                )
            )
        block_lines = []

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        heading_match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush_block()
            current_section = heading_match.group(2).strip()
            elements.append(
                ParsedRagDocumentElement(
                    text=current_section,
                    category="Title",
                    section_title=current_section,
                    page_number=None,
                    element_index=len(elements),
                )
            )
            continue
        if not line.strip():
            flush_block()
            continue
        block_lines.append(line)
    flush_block()
    return elements


def _parse_plain_text(text: str) -> list[ParsedRagDocumentElement]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")) if block.strip()]
    return [
        ParsedRagDocumentElement(
            text=block,
            category="NarrativeText",
            section_title="",
            page_number=None,
            element_index=index,
        )
        for index, block in enumerate(blocks)
    ]


def _parse_with_unstructured(*, file_name: str, content_bytes: bytes) -> list[ParsedRagDocumentElement]:
    try:
        from unstructured.partition.auto import partition
    except ImportError as exc:
        raise RagDocumentParseError(
            "document parser dependency is not installed; install unstructured for PDF/DOCX/HTML ingestion"
        ) from exc

    TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix.lower()
    temp_name = f"{hashlib.sha1(content_bytes).hexdigest()[:16]}{suffix}"
    temp_path = TEMP_UPLOAD_DIR / temp_name
    temp_path.write_bytes(content_bytes)
    partition_kwargs = {"strategy": "fast"} if suffix == ".pdf" else {}
    try:
        raw_elements = partition(filename=str(temp_path), **partition_kwargs)
    finally:
        temp_path.unlink(missing_ok=True)

    parsed_elements: list[ParsedRagDocumentElement] = []
    current_section = ""
    for raw_element in raw_elements:
        text = str(raw_element).strip()
        if not text:
            continue
        category = str(getattr(raw_element, "category", "") or raw_element.__class__.__name__)
        metadata = getattr(raw_element, "metadata", None)
        page_number = _optional_int(getattr(metadata, "page_number", None))
        if category.lower() == "title":
            current_section = text
        parsed_elements.append(
            ParsedRagDocumentElement(
                text=text,
                category=category,
                section_title=current_section,
                page_number=page_number,
                element_index=len(parsed_elements),
            )
        )
    return parsed_elements


def _element_category(element: Any) -> str:
    return str(getattr(element, "category", "") or element.__class__.__name__).strip()


def _section_title_from_elements(elements: list[Any]) -> str:
    for element in elements:
        if _element_category(element).lower() == "title":
            title = str(element).strip()
            if title:
                return title
    return ""


def _first_page_number(elements: list[Any]) -> int | None:
    for element in elements:
        metadata = getattr(element, "metadata", None)
        page_number = _optional_int(getattr(metadata, "page_number", None))
        if page_number is not None:
            return page_number
    return None


def _unique_strings(values: Any) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(normalized)
    return unique_values


def _quality_warnings(text: str, *, section_title: str, categories: list[str], max_chars: int) -> list[str]:
    warnings: list[str] = []
    normalized_text = text.strip()
    if len(normalized_text) < 80:
        warnings.append("short_chunk")
    if len(normalized_text) > max_chars:
        warnings.append("over_max_chars")
    if not section_title.strip():
        warnings.append("missing_section_title")
    if _is_low_value_section(section_title, normalized_text):
        warnings.append("low_value_section")
    if any(category.lower() == "table" for category in categories) and len(normalized_text) < 120:
        warnings.append("short_table_chunk")
    return _unique_strings(warnings)


def _risk_flags(text: str, *, section_title: str) -> list[str]:
    flags: list[str] = []
    combined_text = f"{section_title}\n{text}".lower()
    if _is_low_value_section(section_title, text):
        flags.append("references_section")
    if re.search(r"(标准诊断|诊断为|最终诊断|diagnosis\s*(is|:)|diagnosed\s+with)", combined_text, flags=re.IGNORECASE):
        flags.append("diagnosis_answer_content")
    if re.search(r"(治疗|手术|抗生素|用药|剂量|mg\b|q\d+h|treatment|therapy|dose|dosage)", combined_text, flags=re.IGNORECASE):
        flags.append("treatment_or_dose_content")
    return _unique_strings(flags)


def _is_low_value_section(section_title: str, text: str) -> bool:
    combined_text = f"{section_title}\n{text}".strip().lower()
    if "参考文献" in combined_text or "致谢" in combined_text:
        return True
    return bool(re.search(r"(^|\n)\s*(references|bibliography|acknowledg(e)?ments?)\b", combined_text))


def _decode_text(content_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RagDocumentParseError("document text encoding is not supported")


def _split_long_text(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;.\n])", text) if part.strip()]
    if len(sentences) <= 1:
        return [text[start : start + max_chars].strip() for start in range(0, len(text), max_chars)]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current}{sentence}" if current else sentence
        if current and len(candidate) > max_chars:
            parts.append(current.strip())
            current = sentence
            continue
        current = candidate
    if current.strip():
        parts.append(current.strip())
    return parts


def _tail_window(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0:
        return ""
    compact_text = text.strip()
    if len(compact_text) <= overlap_chars:
        return compact_text
    return compact_text[-overlap_chars:].strip()


def _source_location(
    *,
    file_name: str,
    section_title: str,
    page_number: int | None,
    chunk_number: int,
) -> str:
    parts: list[str] = [Path(file_name).name]
    if page_number is not None:
        parts.append(f"第 {page_number} 页")
    if section_title:
        parts.append(section_title)
    parts.append(f"片段 {chunk_number}")
    return " · ".join(parts)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_:-]+", "_", value.strip())
    return normalized.strip("_") or "global"
