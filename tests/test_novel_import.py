import asyncio
from types import SimpleNamespace
from fastapi import HTTPException
import pytest
from src.web import novel_routes

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


def test_whole_url_uses_every_directory_chapter_and_rejects_partial(tmp_path,monkeypatch):
    base = "https://fanqienovel.com"
    url = base + "/page/1"
    directory = '<div class="chapter"><span>已完结</span>' + "".join(
        f'<a class="chapter-item-title" href="/reader/{i}">第{i}章</a>' for i in range(1,205)) + '</div>'
    bad = set()
    async def fetch(address):
        if address == url:
            return address, directory
        text = '' if address in bad else '一段连续正文。'
        return address, f'<div class="muye-reader-content"><p>{text}</p></div>'
    manager = SimpleNamespace(_ws_manager=SimpleNamespace(resolve_workflow_workspace=lambda *a,**k:tmp_path))
    monkeypatch.setattr(novel_routes,'_ensure_http_mutation_allowed',lambda *a:None)
    monkeypatch.setattr(novel_routes,'_ensure_workflow_writable',lambda *a:manager)
    monkeypatch.setattr(novel_routes,'require_manual_control',lambda *a:None)
    monkeypatch.setattr(novel_routes,'_fetch_public_page',fetch)
    payload = novel_routes.UrlImport(workflow_id='distill', workspace=str(tmp_path),url=url,source_mode='serial_full')
    result=asyncio.run(novel_routes.import_url(payload,None))
    assert (result['chapter_count'],result['source_mode'])==(204,'serial_full')
    corpus=(tmp_path/result['path']).read_bytes()
    bad.add(base+'/reader/56')
    with pytest.raises(HTTPException,match='56'):
        asyncio.run(novel_routes.import_url(payload,None))
    assert (tmp_path/result['path']).read_bytes()==corpus
    one = novel_routes.UrlChapter(index=1,title='第1章',url=base+'/reader/1')
    with pytest.raises(HTTPException,match='完整'):
        asyncio.run(novel_routes.import_url(payload.model_copy(update={'chapters':[one]}),None))
