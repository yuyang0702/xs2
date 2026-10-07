from fastapi import HTTPException

from src.web.novel_routes import _parse_public_page, _validate_fanqie_url


def test_fanqie_detail_page_extracts_reader_chapters():
    html = """
    <html><head><title>示例书_番茄小说</title></head><body>
      <h1>示例书</h1>
      <div class="chapter"><a class="info-last-title" href="/reader/999">最近更新：第9章</a>
        <div class="chapter-item"><a class="chapter-item-title" href="/reader/101">第1章 开始</a></div>
        <div class="chapter-item"><a class="chapter-item-title" href="/reader/102">第2章 继续</a></div>
      </div>
    </body></html>
    """
    parsed = _parse_public_page("https://fanqienovel.com/page/123", html)
    assert parsed["title"] == "示例书"
    assert [item["url"] for item in parsed["chapters"]] == [
        "https://fanqienovel.com/reader/101",
        "https://fanqienovel.com/reader/102",
    ]
    assert all(item["selected"] for item in parsed["chapters"])


def test_fanqie_reader_extracts_only_reader_content_and_flags_font_mapping():
    html = """
    <html><head><title>示例书第1章_番茄小说</title></head><body>
      <div class="muye-reader-nav"><h1 class="muye-reader-nav-title">示例书</h1></div>
      <div class="muye-reader-box"><h1 class="muye-reader-title">第1章 开始</h1>
        <div class="muye-reader-content noselect"><p>普通文字</p><p>混淆\ue400字符</p></div>
      </div><div class="reader-toolbar">不要写入</div>
    </body></html>
    """
    parsed = _parse_public_page("https://fanqienovel.com/reader/101", html)
    assert parsed["title"] == "第1章 开始"
    assert "普通文字" in parsed["text"]
    assert "不要写入" not in parsed["text"]
    assert parsed["font_obfuscated"] is True


def test_fanqie_url_is_allowlisted():
    assert _validate_fanqie_url("https://fanqienovel.com/page/123").endswith("/page/123")
    try:
        _validate_fanqie_url("https://example.com/page/123")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("non-Fanqie URL should be rejected")
