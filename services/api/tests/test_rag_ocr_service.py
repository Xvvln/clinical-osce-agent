from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from PIL import Image

import app.services.rag_ocr_service as ocr_module


def test_recognize_image_filters_low_confidence_lines(monkeypatch) -> None:
    image_stream = BytesIO()
    Image.new("RGB", (200, 80), "white").save(image_stream, format="PNG")

    class FakeEngine:
        def __call__(self, content: bytes, **kwargs):
            assert content.startswith(b"\x89PNG")
            assert kwargs["text_score"] == 0.5
            return SimpleNamespace(
                txts=("  疼痛迁移  ", "模糊噪声"),
                scores=(0.96, 0.2),
            )

    monkeypatch.setattr(ocr_module, "_build_ocr_engine", lambda: FakeEngine())

    result = ocr_module.recognize_image(image_stream.getvalue(), page_number=3)

    assert result.page_number == 3
    assert result.text == "疼痛迁移"
    assert result.line_count == 1
    assert result.mean_confidence == 0.96


def test_recognize_multiframe_image_keeps_page_order(monkeypatch) -> None:
    first = Image.new("RGB", (100, 60), "white")
    second = Image.new("RGB", (100, 60), "black")
    image_stream = BytesIO()
    first.save(image_stream, format="TIFF", save_all=True, append_images=[second])
    calls: list[int] = []

    def fake_recognize_image(content: bytes, *, page_number: int):
        calls.append(page_number)
        return ocr_module.RagOcrPage(
            page_number=page_number,
            text=f"第 {page_number} 页",
            mean_confidence=0.9,
            line_count=1,
        )

    monkeypatch.setattr(ocr_module, "recognize_image", fake_recognize_image)

    pages = ocr_module.recognize_image_pages(image_stream.getvalue())

    assert calls == [1, 2]
    assert [page.text for page in pages] == ["第 1 页", "第 2 页"]
