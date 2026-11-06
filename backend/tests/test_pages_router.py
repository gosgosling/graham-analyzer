"""Страницы для роботов: заголовки, превью, текст в #root, 404 и noindex."""
from app.routers.pages_router import Page, render

INDEX = (
    '<!doctype html><html><head><title>Graham Analyzer</title>'
    '<meta name="description" content="старое" /></head>'
    '<body><div id="root"></div><script src="/static/js/main.js"></script></body></html>'
)


def test_render_puts_title_preview_and_text_into_index():
    page = Page(title="Сбер Банк (SBER) — стоимость по Грэму",
                description="Цена 292 ₽, опорная 259 ₽ — дороже на 13%.",
                heading="Сбер Банк (SBER)", lines=["Цена 292 ₽ <b>"], links=[("/companies", "Все компании")])
    out = render(INDEX, page, "https://example.ru/company/1", "https://example.ru")
    assert "<title>Сбер Банк (SBER) — стоимость по Грэму — Graham Analyzer</title>" in out
    assert 'name="description" content="Цена 292 ₽, опорная 259 ₽ — дороже на 13%."' in out
    assert 'property="og:title" content="Сбер Банк (SBER) — стоимость по Грэму"' in out
    assert 'rel="canonical" href="https://example.ru/company/1"' in out
    # Текст для робота — внутри #root и экранирован; скрипт сборки на месте.
    assert '<div id="root"><main' in out and "Цена 292 ₽ &lt;b&gt;" in out
    assert '<script src="/static/js/main.js"></script>' in out
    assert "noindex" not in out


def test_render_marks_private_pages_noindex_without_text():
    out = render(INDEX, Page(title="Вход", description="d", noindex=True), "https://example.ru/login", "https://example.ru")
    assert '<meta name="robots" content="noindex" />' in out
    assert '<div id="root"></div>' in out


def test_dump_import_deep_link_is_private_and_known():
    from app.routers.pages_router import resolve

    page = resolve(None, "admin/dump-import")
    assert page.status == 200
    assert page.title == "Импорт из дампа"
    assert page.noindex
    assert resolve(None, "admin/unknown").status == 404
