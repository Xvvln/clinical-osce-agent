import tomllib
from pathlib import Path

from app.services.rag_document_ingestion_service import chunk_rag_document


def test_document_parser_stack_is_a_default_backend_dependency() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"].get("optional-dependencies", {})

    assert any(dependency.startswith("unstructured[all-docs]") for dependency in dependencies)
    assert "documents" not in optional_dependencies


def test_markdown_document_chunking_preserves_sections_and_overlap() -> None:
    content = """
# 急性腹痛教学资料

急性腹痛训练应先建立病史框架，再决定体格检查与辅助检查。

## 病史采集

需要追问起病时间、疼痛部位、疼痛性质、疼痛程度、疼痛演变和伴随症状。
疼痛迁移、恶心呕吐、发热和既往腹部手术史会影响下一步推理。

## 查体策略

腹部查体应包含视诊、听诊、触诊和腹膜刺激征，避免只做单个压痛点。
如果病史仍不完整，应先补齐关键病史，再解释为什么进入查体。

## 检查选择

血常规、炎症指标、尿常规和腹部超声用于支持或修正诊断假设。
检查结果只能作为反馈和教学知识，不进入标准评分裁判。
""".strip()

    chunks = chunk_rag_document(
        file_name="appendicitis_teaching.md",
        content_bytes=content.encode("utf-8"),
        document_id="kbdoc:appendicitis_001:test",
        max_chars=90,
        overlap_chars=18,
    )

    assert len(chunks) >= 4
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.section_title for chunk in chunks} >= {"急性腹痛教学资料", "病史采集", "查体策略", "检查选择"}
    assert all(chunk.source_location.startswith("appendicitis_teaching.md") for chunk in chunks)
    assert all(chunk.document_id == "kbdoc:appendicitis_001:test" for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)
    assert chunks[1].text[:18] in chunks[0].text
