"""Синхронизация ключевой ставки ЦБ РФ.

Источник — открытый SOAP-сервис cbr.ru (метод KeyRate). Сервис отдаёт
значение на каждый календарный день; мы сжимаем это в точки изменения
ставки и дописываем в юридический конфиг.

Правило на случай недоступности источника: расчёт НЕ останавливается,
используется последняя известная ставка из конфига, но в ответе API
проставляется признак stale и дата последней успешной синхронизации.
Молча считать по устаревшей ставке нельзя.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

import httpx

from .legal_config import ConfigStore, LegalConfig

CBR_ENDPOINT = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
SOAP_ACTION = "http://web.cbr.ru/KeyRate"
STATE_PATH = Path(__file__).resolve().parents[2] / "config" / "cbr-sync-state.json"

# Ставка считается устаревшей, если синхронизация не проходила дольше этого срока.
STALE_AFTER_HOURS = 48

_SOAP_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                 xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <KeyRate xmlns="http://web.cbr.ru/">
      <fromDate>{from_date}</fromDate>
      <ToDate>{to_date}</ToDate>
    </KeyRate>
  </soap12:Body>
</soap12:Envelope>
"""


class CbrError(Exception):
    """Источник ЦБ недоступен или ответил неожиданным форматом."""


@dataclass
class SyncState:
    last_success_at: Optional[str] = None
    last_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
    added_entries: int = 0

    @property
    def is_stale(self) -> bool:
        if not self.last_success_at:
            return True
        try:
            moment = datetime.fromisoformat(self.last_success_at)
        except ValueError:
            return True
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - moment > timedelta(hours=STALE_AFTER_HOURS)


def load_state(path: Path = STATE_PATH) -> SyncState:
    try:
        return SyncState(**json.loads(Path(path).read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return SyncState()


def save_state(state: SyncState, path: Path = STATE_PATH) -> None:
    Path(path).write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_keyrate_xml(payload: str) -> List[Tuple[date, Decimal]]:
    """Разбирает ответ KeyRate в список (дата, ставка), отсортированный по дате.

    Формат ответа неоднократно менялся в деталях (namespace, регистр тегов),
    поэтому разбор идёт по локальным именам тегов, а не по полным путям.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise CbrError(f"ЦБ вернул неразбираемый XML: {exc}") from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    items: List[Tuple[date, Decimal]] = []
    for node in root.iter():
        if local(node.tag) != "kr":
            continue
        day: Optional[date] = None
        rate: Optional[Decimal] = None
        for child in node:
            name = local(child.tag)
            text = (child.text or "").strip()
            if not text:
                continue
            if name == "dt":
                try:
                    day = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
                except ValueError:
                    try:
                        day = date.fromisoformat(text[:10])
                    except ValueError:
                        day = None
            elif name == "rate":
                try:
                    rate = Decimal(text.replace(",", "."))
                except Exception:
                    rate = None
        if day is not None and rate is not None:
            items.append((day, rate))

    if not items:
        raise CbrError("В ответе ЦБ не найдено ни одного значения ключевой ставки.")
    items.sort(key=lambda pair: pair[0])
    return items


def compress_to_changes(daily: List[Tuple[date, Decimal]]) -> List[Tuple[date, Decimal]]:
    """Из ежедневных значений оставляет только точки изменения ставки."""
    changes: List[Tuple[date, Decimal]] = []
    previous: Optional[Decimal] = None
    for day, rate in daily:
        if previous is None or rate != previous:
            changes.append((day, rate))
            previous = rate
    return changes


def fetch_key_rates(
    from_date: date, to_date: date, *, timeout: float = 15.0, client: Optional[httpx.Client] = None
) -> List[Tuple[date, Decimal]]:
    body = _SOAP_TEMPLATE.format(from_date=from_date.isoformat(), to_date=to_date.isoformat())
    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "SOAPAction": SOAP_ACTION,
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        response = client.post(CBR_ENDPOINT, content=body.encode("utf-8"), headers=headers)
        if response.status_code != 200:
            raise CbrError(f"ЦБ ответил кодом {response.status_code}.")
        return parse_keyrate_xml(response.text)
    except httpx.HTTPError as exc:
        raise CbrError(f"Не удалось обратиться к cbr.ru: {exc}") from exc
    finally:
        if owns_client:
            client.close()


def sync_rates(
    store: ConfigStore,
    *,
    today: Optional[date] = None,
    client: Optional[httpx.Client] = None,
    state_path: Path = STATE_PATH,
) -> Dict[str, object]:
    """Дотягивает историю ставок до сегодняшнего дня и пишет в конфиг."""
    today = today or date.today()
    config = store.get()
    state = load_state(state_path)
    state.last_attempt_at = datetime.now(timezone.utc).isoformat()

    if not config.rates_auto_sync:
        state.last_error = "Автосинхронизация выключена в конфиге (cbr_rates.auto_sync=false)."
        save_state(state, state_path)
        return {"synced": False, "reason": state.last_error, "added": 0}

    known_last = config.latest_rate()
    window_start = min(known_last.from_date, today)

    try:
        daily = fetch_key_rates(window_start, today, client=client)
    except CbrError as exc:
        state.last_error = str(exc)
        save_state(state, state_path)
        return {"synced": False, "reason": str(exc), "added": 0}

    changes = compress_to_changes(daily)
    existing = {entry.from_date: entry.rate for entry in config.rates}
    previous_rate = known_last.rate

    new_entries: List[Dict[str, object]] = []
    for day, rate in changes:
        if day in existing:
            previous_rate = rate
            continue
        if day <= known_last.from_date:
            continue
        if rate == previous_rate:
            continue
        new_entries.append({"from": day.isoformat(), "rate": float(rate)})
        previous_rate = rate

    if new_entries:
        data = json.loads(json.dumps(config.raw))  # глубокая копия
        data["cbr_rates"]["items"].extend(new_entries)
        data["cbr_rates"]["source"] = f"синхронизировано с cbr.ru {today.isoformat()}"
        data["updated_at"] = today.isoformat()
        store.save(data, author="cbr-sync")

    state.last_success_at = datetime.now(timezone.utc).isoformat()
    state.last_error = None
    state.added_entries = len(new_entries)
    save_state(state, state_path)
    return {"synced": True, "added": len(new_entries), "entries": new_entries}


def rate_status(config: LegalConfig, state_path: Path = STATE_PATH) -> Dict[str, object]:
    """Состояние ставки для вывода в UI: значение, дата, свежесть."""
    state = load_state(state_path)
    latest = config.latest_rate()
    return {
        "rate": float(latest.rate),
        "effective_from": latest.from_date.isoformat(),
        "auto_sync": config.rates_auto_sync,
        "last_success_at": state.last_success_at,
        "last_attempt_at": state.last_attempt_at,
        "last_error": state.last_error,
        "is_stale": state.is_stale,
        "source": config.rates_source,
        "requires_lawyer_review": config.rates_requires_review,
        "warning": (
            "Ставка взята из локального конфига: синхронизация с cbr.ru не выполнялась "
            f"или не удалась (последняя успешная: {state.last_success_at or 'никогда'}). "
            "Проверьте актуальность ставки вручную."
        )
        if state.is_stale
        else None,
    }
