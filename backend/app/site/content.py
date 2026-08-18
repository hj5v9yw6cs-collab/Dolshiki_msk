"""Содержимое публичного сайта.

Тексты живут в content/site.json и правятся без программиста — тем же
приёмом, что и юридический конфиг: файл проверяется при загрузке, и
сломанный вариант не применяется, вместо этого продолжает работать
предыдущий.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "content" / "site.json"

REQUIRED_TOP = ("company", "seo", "nav", "home", "pages", "practice", "contacts")
REQUIRED_PAGE = ("slug", "title", "description", "h1")


class ContentError(Exception):
    """Файл с содержимым сайта невалиден."""


def validate(data: Dict[str, Any]) -> None:
    for key in REQUIRED_TOP:
        if key not in data:
            raise ContentError(f"В site.json нет раздела «{key}».")

    slugs = set()
    for index, page in enumerate(data["pages"]):
        for key in REQUIRED_PAGE:
            if not page.get(key):
                raise ContentError(f"pages[{index}]: не заполнено поле «{key}».")
        if page["slug"] in slugs:
            raise ContentError(f"Две страницы с адресом «{page['slug']}».")
        slugs.add(page["slug"])

    for item in data["nav"]:
        if not item.get("slug") or not item.get("short"):
            raise ContentError("В меню у каждого пункта должны быть slug и short.")


@dataclass
class Content:
    data: Dict[str, Any]

    @property
    def company(self) -> Dict[str, Any]:
        return self.data["company"]

    @property
    def seo(self) -> Dict[str, Any]:
        return self.data["seo"]

    @property
    def nav(self) -> List[Dict[str, Any]]:
        return self.data["nav"]

    @property
    def pages(self) -> List[Dict[str, Any]]:
        return self.data["pages"]

    def page(self, slug: str) -> Optional[Dict[str, Any]]:
        for item in self.pages:
            if item["slug"] == slug:
                return item
        return None

    def region_page(self, slug: str, region: str) -> Optional[Dict[str, Any]]:
        page = self.page(slug)
        if not page:
            return None
        for item in page.get("regions", []):
            if item["slug"] == region:
                return item
        return None

    def all_urls(self) -> List[str]:
        """Адреса всех публичных страниц — для карты сайта."""
        urls = ["/", "/praktika", "/kontakty", "/politika", "/soglasie"]
        for page in self.pages:
            urls.append(f"/{page['slug']}")
            for region in page.get("regions", []):
                urls.append(f"/{page['slug']}/{region['slug']}")
        return urls


class ContentStore:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._content: Optional[Content] = None

    def _load(self) -> Content:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ContentError(f"Не найден файл с содержимым сайта: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise ContentError(f"site.json повреждён: {exc}") from exc
        validate(data)
        return Content(data)

    def get(self) -> Content:
        with self._lock:
            if self._content is None:
                self._content = self._load()
            return self._content

    def reload(self) -> Content:
        """Перечитывает файл. Ошибка не ломает сайт: остаётся прежний текст."""
        with self._lock:
            self._content = self._load()
            return self._content


store = ContentStore()
