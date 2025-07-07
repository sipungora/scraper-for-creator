import pytest
from unittest.mock import patch, MagicMock
from scrape_and_upload import chunk_text, extract_main_content

# Тесты для chunk_text

def test_chunk_text_basic():
    text = "A" * 5000
    chunks = chunk_text(text, chunk_size=2048, chunk_overlap=200)
    assert all(len(c) <= 2048 * 1.2 for c in chunks)
    assert len(chunks) > 1
    # Проверяем overlap
    for i in range(1, len(chunks)):
        assert chunks[i-1][-200:] in chunks[i][:300]

def test_chunk_text_paragraphs():
    text = "para1\n\npara2" + "A"*2040
    chunks = chunk_text(text, chunk_size=2048, chunk_overlap=200)
    assert len(chunks) >= 1

def test_chunk_text_short():
    text = "short text"
    chunks = chunk_text(text, chunk_size=2048, chunk_overlap=200)
    assert chunks == ["short text"]

# Тест extract_main_content

def test_extract_main_content_main():
    html = "<html><main>main content</main><body>body content</body></html>"
    assert extract_main_content(html) == "main content"

def test_extract_main_content_body():
    html = "<html><body>body content</body></html>"
    assert extract_main_content(html) == "body content"

def test_extract_main_content_fallback():
    html = "<html><div>other content</div></html>"
    assert "other content" in extract_main_content(html)

# Мокаем get_embedding и upload_chunk

def test_get_embedding_mock():
    with patch("scrape_and_upload.get_embedding") as mock_emb:
        mock_emb.return_value = [0.1] * 1536
        result = mock_emb("test")
        assert isinstance(result, list)
        assert len(result) == 1536

def test_upload_chunk_mock():
    with patch("scrape_and_upload.upload_chunk") as mock_up:
        mock_up.return_value = None
        assert mock_up("chunk", [0.1]*1536, "url", "topic") is None 