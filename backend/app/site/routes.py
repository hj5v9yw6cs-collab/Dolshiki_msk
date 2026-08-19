"""Публичный сайт: страницы, карта сайта, правовые документы.

Страницы отрисовываются на сервере — поисковикам нужен готовый HTML, а не
пустая страница, которую дособирает браузер. Отдельного фронтенд-приложения
нет намеренно: на четырёх сотрудников второй язык и второй процесс на
сервере не окупаются.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from ..env import env
from .content import Content, ContentError, store

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
STATIC = Path(__file__).parent / "static"


def asset_version() -> str:
    """Метка версии стилей и скрипта.

    Без неё браузер после обновления сайта берёт старый site.css из кэша:
    разметка новая, оформление прежнее — и правки выглядят несделанными.
    Метка меняется вместе с файлами, поэтому кэш сбрасывается ровно тогда,
    когда есть что сбрасывать.
    """
    stamps = [0]
    files = [STATIC / "site.css", STATIC / "site.js"]
    # Калькулятор во врезке живёт в отдельной папке и кэшируется так же.
    widget = Path(__file__).resolve().parents[3] / "widget"
    files += [widget / "calculator.css", widget / "calculator.js", widget / "index.html"]
    for path in files:
        try:
            stamps.append(int(path.stat().st_mtime))
        except OSError:
            pass
    return str(max(stamps))

router = APIRouter(tags=["Сайт"], include_in_schema=False)


def site_origin() -> str:
    """Адрес сайта для canonical и карты сайта."""
    return env("SITE_ORIGIN", "https://" + store.get().company.get("domain", "dolshikirf.ru")).rstrip("/")


def content() -> Content:
    try:
        return store.get()
    except ContentError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


# ---------------------------------------------------------------------------
# Микроразметка
# ---------------------------------------------------------------------------


def organization_schema(data: Content, origin: str) -> Dict[str, Any]:
    company = data.company
    return {
        "@type": "LegalService",
        "@id": origin + "/#organization",
        "name": company["name"],
        "legalName": company.get("legal_name"),
        "url": origin,
        "telephone": company.get("phone"),
        "email": company.get("email"),
        "areaServed": [office for office in ("Москва", "Казань")],
        "description": data.seo.get("default_description", ""),
    }


def faq_schema(items: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in items
        ],
    }


def breadcrumb_schema(crumbs: List[Dict[str, str]], origin: str) -> Dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": crumb["title"],
                "item": origin + crumb["url"],
            }
            for index, crumb in enumerate(crumbs, start=1)
        ],
    }


def build_schema(
    data: Content, origin: str, *, faq: Optional[List[Dict[str, str]]] = None,
    crumbs: Optional[List[Dict[str, str]]] = None,
) -> str:
    graph: List[Dict[str, Any]] = [organization_schema(data, origin)]
    if faq:
        graph.append(faq_schema(faq))
    if crumbs and len(crumbs) > 1:
        graph.append(breadcrumb_schema(crumbs, origin))
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def render(
    request: Request, template: str, *, data: Content, page: Dict[str, Any],
    path: str, current: str = "", crumbs: Optional[List[Dict[str, str]]] = None,
    **extra: Any,
) -> HTMLResponse:
    origin = site_origin()
    return TEMPLATES.TemplateResponse(
        request=request,
        name=template,
        context={
            "content": data,
            "page": page,
            "page_title": page.get("title") or data.seo["default_title"],
            "page_description": page.get("description") or data.seo["default_description"],
            "canonical": origin + path,
            "current": current,
            "breadcrumbs": crumbs,
            "schema": build_schema(data, origin, faq=page.get("faq"), crumbs=crumbs),
            "asset_version": asset_version(),
            **extra,
        },
    )


# ---------------------------------------------------------------------------
# Страницы
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def home(request: Request, data: Content = Depends(content)) -> HTMLResponse:
    return render(request, "home.html", data=data, page=data.data["home"], path="/", current="")


@router.get("/praktika", response_class=HTMLResponse)
def practice(request: Request, data: Content = Depends(content)) -> HTMLResponse:
    crumbs = [{"title": "Главная", "url": "/"}, {"title": "Практика", "url": "/praktika"}]
    return render(
        request, "practice.html", data=data, page=data.data["practice"],
        path="/praktika", current="praktika", crumbs=crumbs,
    )


@router.get("/kontakty", response_class=HTMLResponse)
def contacts(request: Request, data: Content = Depends(content)) -> HTMLResponse:
    crumbs = [{"title": "Главная", "url": "/"}, {"title": "Контакты", "url": "/kontakty"}]
    return render(
        request, "contacts.html", data=data, page=data.data["contacts"],
        path="/kontakty", current="kontakty", crumbs=crumbs,
    )


@router.get("/politika", response_class=HTMLResponse)
def policy(request: Request, data: Content = Depends(content)) -> HTMLResponse:
    from .legal import policy_html

    page = {
        "h1": "Политика обработки персональных данных",
        "title": "Политика обработки персональных данных",
        "description": "Как мы собираем, храним и используем персональные данные посетителей сайта и клиентов.",
        "lead": "",
    }
    crumbs = [{"title": "Главная", "url": "/"}, {"title": "Политика", "url": "/politika"}]
    return render(
        request, "legal.html", data=data, page=page, path="/politika",
        crumbs=crumbs, with_form=False, body_html=policy_html(data),
    )


@router.get("/soglasie", response_class=HTMLResponse)
def consent(request: Request, data: Content = Depends(content)) -> HTMLResponse:
    from .legal import consent_html

    page = {
        "h1": "Согласие на обработку персональных данных",
        "title": "Согласие на обработку персональных данных",
        "description": "Текст согласия, которое даёт посетитель при отправке заявки.",
        "lead": "",
    }
    crumbs = [{"title": "Главная", "url": "/"}, {"title": "Согласие", "url": "/soglasie"}]
    return render(
        request, "legal.html", data=data, page=page, path="/soglasie",
        crumbs=crumbs, with_form=False, body_html=consent_html(data),
    )


# ---------------------------------------------------------------------------
# Служебные адреса объявляются до общего маршрута /{slug}: FastAPI подбирает
# обработчики по порядку, и иначе robots.txt и sitemap.xml были бы приняты
# за адрес страницы услуги.
# ---------------------------------------------------------------------------


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> PlainTextResponse:
    origin = site_origin()
    lines = [
        "User-agent: *",
        "Allow: /",
        # Кабинет и API в поиске не нужны.
        "Disallow: /app/",
        "Disallow: /api/",
        "Disallow: /docs",
        "",
        f"Sitemap: {origin}/sitemap.xml",
    ]
    return PlainTextResponse("\n".join(lines))


@router.get("/sitemap.xml")
def sitemap(data: Content = Depends(content)) -> Response:
    origin = site_origin()
    today = date.today().isoformat()
    urls = "".join(
        f"<url><loc>{origin}{path}</loc><lastmod>{today}</lastmod>"
        f"<priority>{'1.0' if path == '/' else '0.8'}</priority></url>"
        for path in data.all_urls()
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/site.css")
def site_css() -> FileResponse:
    return FileResponse(
        STATIC / "site.css", media_type="text/css",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/site.js")
def site_js() -> FileResponse:
    return FileResponse(
        STATIC / "site.js", media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{slug}", response_class=HTMLResponse)
def service_page(slug: str, request: Request, data: Content = Depends(content)) -> HTMLResponse:
    page = data.page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Страница не найдена.")

    crumbs = [{"title": "Главная", "url": "/"},
              {"title": page["nav_title"], "url": f"/{slug}"}]
    return render(
        request, "page.html", data=data, page=page, path=f"/{slug}",
        current=slug, crumbs=crumbs, topic=page.get("topic", "neustoyka"),
    )


@router.get("/{slug}/{region}", response_class=HTMLResponse)
def region_page(slug: str, region: str, request: Request, data: Content = Depends(content)) -> HTMLResponse:
    page = data.page(slug)
    area = data.region_page(slug, region)
    if page is None or area is None:
        raise HTTPException(status_code=404, detail="Страница не найдена.")

    # Региональная страница — та же услуга, но со своим заголовком и адресом.
    local = dict(page)
    local["h1"] = f"{page['h1']} — {area['title']}"
    local["title"] = f"{page['title']} — {area['title']}"
    local["description"] = f"{page['description']} {area['title']}."
    local["regions"] = []

    crumbs = [
        {"title": "Главная", "url": "/"},
        {"title": page["nav_title"], "url": f"/{slug}"},
        {"title": area["title"], "url": f"/{slug}/{region}"},
    ]
    return render(
        request, "page.html", data=data, page=local, path=f"/{slug}/{region}",
        current=slug, crumbs=crumbs, topic=page.get("topic", "neustoyka"),
        region_code=area.get("code", ""),
    )
