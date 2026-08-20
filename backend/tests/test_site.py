"""Тесты публичного сайта: отрисовка, SEO, формы."""

import json
import re

import pytest

from app.site.content import ContentError, validate


def html(api_client, path):
    response = api_client.get(path)
    assert response.status_code == 200, f"{path} вернул {response.status_code}"
    return response.text


# --- содержимое ------------------------------------------------------------


def test_shipped_content_is_valid():
    from app.site.content import store

    data = store.reload()
    assert data.pages, "должны быть страницы услуг"
    assert data.company["name"]


def test_missing_section_is_rejected():
    with pytest.raises(ContentError, match="нет раздела"):
        validate({"company": {}})


def test_page_without_title_is_rejected():
    base = {
        "company": {}, "seo": {}, "nav": [], "home": {}, "practice": {}, "contacts": {},
        "pages": [{"slug": "test", "description": "d", "h1": "h"}],
    }
    with pytest.raises(ContentError, match="title"):
        validate(base)


def test_duplicate_page_addresses_are_rejected():
    page = {"slug": "same", "title": "t", "description": "d", "h1": "h"}
    base = {
        "company": {}, "seo": {}, "nav": [], "home": {}, "practice": {}, "contacts": {},
        "pages": [page, dict(page)],
    }
    with pytest.raises(ContentError, match="Две страницы"):
        validate(base)


def test_broken_file_does_not_break_the_site(tmp_path):
    """Сломанный site.json не должен ронять сайт — остаётся прежний текст."""
    from app.site.content import ContentStore

    good = tmp_path / "site.json"
    from app.site.content import store as live

    good.write_text(json.dumps(live.get().data, ensure_ascii=False), encoding="utf-8")
    local = ContentStore(good)
    before = local.get().company["name"]

    good.write_text("{ это не json", encoding="utf-8")
    with pytest.raises(ContentError):
        local.reload()

    assert local.get().company["name"] == before


# --- страницы --------------------------------------------------------------


def test_home_renders_on_the_server(api_client):
    page = html(api_client, "/")

    assert "<h1>" in page
    assert "Калькулятор" in page
    assert "id=\"lead-form\"" in page


def test_every_service_page_opens(api_client):
    from app.site.content import store

    for item in store.get().pages:
        page = html(api_client, "/" + item["slug"])
        assert item["h1"] in page


def test_region_pages_have_their_own_heading(api_client):
    page = html(api_client, "/neustoyka/kazan")

    assert "Казань и Татарстан" in page
    assert "<h1>" in page
    # Форма на региональной странице сразу помечена нужным регионом.
    assert 'data-region="kzn"' in page


def test_unknown_page_returns_404(api_client):
    assert api_client.get("/takoy-stranicy-net").status_code == 404
    assert api_client.get("/neustoyka/marsa").status_code == 404


def test_service_route_does_not_swallow_api_and_cabinet(api_client):
    """Общий маршрут /{slug} не должен перехватывать служебные адреса."""
    assert api_client.get("/health").json()["status"] == "ok"
    assert api_client.get("/api/v1/rate").status_code == 200
    assert api_client.get("/api/v1/cases").status_code == 401


def test_legal_pages_name_the_operator(api_client):
    """Без реквизитов оператора документ по 152-ФЗ не работает."""
    for path in ("/politika", "/soglasie"):
        page = html(api_client, path)
        assert "Оператор персональных данных" in page, f"{path}: не назван оператор"
        assert "ИНН 120101147767" in page, f"{path}: нет ИНН оператора"
        assert "Фучика" in page, f"{path}: нет адреса для обращений"
        assert "0000000000" not in page, f"{path}: остался ИНН-заглушка"


def test_policy_names_a_retention_period(api_client):
    page = html(api_client, "/politika")

    assert "одного года" in page
    assert "должен определить юрист" not in page


def test_contacts_page_shows_requisites(api_client):
    page = html(api_client, "/kontakty")

    assert "ИНН" in page
    assert "Где работаем" in page


def test_practice_page_shows_won_cases_without_naming_the_client(api_client):
    """Дела публикуются, доверители — нет: страница обещает именно это."""
    page = html(api_client, "/praktika")

    assert "МТ-Девелопмент" in page
    assert "Советский районный суд" in page
    assert "466 097,66" in page
    assert "Насырова" not in page, "имя доверителя на публичной странице"


def test_page_has_unique_title_and_description(api_client):
    home = html(api_client, "/")
    service = html(api_client, "/nedostatki-otdelki")

    def meta(page, name):
        match = re.search(r'<meta name="%s" content="([^"]+)"' % name, page)
        return match.group(1) if match else ""

    def title(page):
        return re.search(r"<title>([^<]+)</title>", page).group(1)

    assert title(home) != title(service)
    assert meta(home, "description") != meta(service, "description")
    assert len(meta(service, "description")) > 40


def test_canonical_and_open_graph_are_present(api_client):
    page = html(api_client, "/neustoyka")

    assert '<link rel="canonical"' in page
    assert 'property="og:title"' in page
    assert 'property="og:url"' in page


def test_schema_org_describes_the_business_and_faq(api_client):
    page = html(api_client, "/neustoyka")
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    graph = json.loads(raw)["@graph"]
    types = {item["@type"] for item in graph}

    assert "LegalService" in types
    assert "FAQPage" in types
    assert "BreadcrumbList" in types

    faq = next(item for item in graph if item["@type"] == "FAQPage")
    assert len(faq["mainEntity"]) >= 3
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"]


def test_home_has_no_breadcrumbs(api_client):
    """На главной хлебные крошки не нужны — и в разметке их быть не должно."""
    page = html(api_client, "/")
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    types = {item["@type"] for item in json.loads(raw)["@graph"]}

    assert "BreadcrumbList" not in types


def test_sitemap_lists_every_page(api_client):
    from app.site.content import store

    response = api_client.get("/sitemap.xml")

    assert response.status_code == 200
    assert "xml" in response.headers["content-type"]
    body = response.text
    for path in store.get().all_urls():
        assert f"<loc>https://" in body
        assert path + "</loc>" in body or path == "/"


def test_robots_blocks_the_cabinet_and_points_to_sitemap(api_client):
    body = html(api_client, "/robots.txt")

    assert "Disallow: /app/" in body
    assert "Disallow: /api/" in body
    assert "Sitemap: https://" in body


def test_static_files_are_served(api_client):
    assert api_client.get("/site.css").status_code == 200
    assert api_client.get("/site.js").status_code == 200


# --- заявка с сайта --------------------------------------------------------


def test_lead_from_the_site_reaches_the_cabinet(api_client, staff):
    created = api_client.post("/api/v1/leads", json={
        "name": "Мария Иванова", "phone": "+7 900 555-11-22",
        "topic": "defects", "region": "kzn", "project": "ЖК Весна",
        "consent": True, "source": "site",
    })
    assert created.status_code == 201

    listed = api_client.get("/api/v1/leads", headers=staff["lawyer"]).json()
    lead = next(item for item in listed["items"] if item["id"] == created.json()["id"])
    assert lead["source"] == "site"
    assert lead["project"] == "ЖК Весна"


def test_site_form_marks_the_topic_of_its_page(api_client):
    page = html(api_client, "/nedostatki-otdelki")

    assert 'data-topic="defects"' in page
