"""Тесты синхронизации ключевой ставки.

Сеть не дёргаем: подставляем httpx-транспорт с готовым ответом.
"""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.core import cbr
from app.core.legal_config import ConfigStore
from conftest import config_dict

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <KeyRateResponse xmlns="http://web.cbr.ru/">
      <KeyRateResult>
        <diffgram>
          <KeyRate>
            <KR><DT>2023-12-30T00:00:00+03:00</DT><Rate>16.00</Rate></KR>
            <KR><DT>2023-12-31T00:00:00+03:00</DT><Rate>16.00</Rate></KR>
            <KR><DT>2024-01-01T00:00:00+03:00</DT><Rate>16.00</Rate></KR>
            <KR><DT>2024-07-29T00:00:00+03:00</DT><Rate>18.00</Rate></KR>
            <KR><DT>2024-07-30T00:00:00+03:00</DT><Rate>18.00</Rate></KR>
            <KR><DT>2024-09-16T00:00:00+03:00</DT><Rate>19.00</Rate></KR>
          </KeyRate>
        </diffgram>
      </KeyRateResult>
    </KeyRateResponse>
  </soap:Body>
</soap:Envelope>
"""


def client_returning(payload: str, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_keyrate_xml_reads_all_values():
    items = cbr.parse_keyrate_xml(SAMPLE_XML)

    assert len(items) == 6
    assert items[0] == (date(2023, 12, 30), Decimal("16.00"))
    assert items[-1] == (date(2024, 9, 16), Decimal("19.00"))


def test_parse_keyrate_xml_accepts_comma_decimal_separator():
    payload = """<r><KR><DT>2024-01-01</DT><Rate>16,50</Rate></KR></r>"""
    assert cbr.parse_keyrate_xml(payload) == [(date(2024, 1, 1), Decimal("16.50"))]


def test_parse_keyrate_xml_rejects_empty_response():
    with pytest.raises(cbr.CbrError, match="не найдено ни одного значения"):
        cbr.parse_keyrate_xml("<r></r>")


def test_parse_keyrate_xml_rejects_broken_xml():
    with pytest.raises(cbr.CbrError, match="неразбираемый XML"):
        cbr.parse_keyrate_xml("<not-xml")


def test_compress_to_changes_keeps_only_change_points():
    changes = cbr.compress_to_changes(cbr.parse_keyrate_xml(SAMPLE_XML))

    assert changes == [
        (date(2023, 12, 30), Decimal("16.00")),
        (date(2024, 7, 29), Decimal("18.00")),
        (date(2024, 9, 16), Decimal("19.00")),
    ]


def test_fetch_key_rates_reports_http_error():
    with pytest.raises(cbr.CbrError, match="кодом 503"):
        cbr.fetch_key_rates(
            date(2024, 1, 1), date(2024, 12, 31), client=client_returning("", status_code=503)
        )


def test_fetch_key_rates_reports_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(cbr.CbrError, match="Не удалось обратиться к cbr.ru"):
        cbr.fetch_key_rates(date(2024, 1, 1), date(2024, 12, 31), client=client)


def make_store(tmp_path, **overrides):
    path = tmp_path / "legal-config.json"
    data = config_dict(
        cbr_rates={
            "source": "test",
            "auto_sync": True,
            "requires_lawyer_review": False,
            "items": [{"from": "2023-12-30", "rate": 16.0}],
        },
        **overrides,
    )
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ConfigStore(path)


def test_sync_adds_only_new_rate_changes(tmp_path):
    store = make_store(tmp_path)
    state_path = tmp_path / "state.json"

    result = cbr.sync_rates(
        store,
        today=date(2024, 12, 31),
        client=client_returning(SAMPLE_XML),
        state_path=state_path,
    )

    assert result["synced"] is True
    assert result["added"] == 2
    rates = {entry.from_date.isoformat(): entry.rate for entry in store.get().rates}
    assert rates == {
        "2023-12-30": Decimal("16.0"),
        "2024-07-29": Decimal("18.0"),
        "2024-09-16": Decimal("19.0"),
    }


def test_sync_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    state_path = tmp_path / "state.json"
    args = dict(today=date(2024, 12, 31), client=client_returning(SAMPLE_XML), state_path=state_path)

    cbr.sync_rates(store, **args)
    second = cbr.sync_rates(store, **args)

    assert second["added"] == 0
    assert len(store.get().rates) == 3


def test_sync_failure_keeps_config_intact_and_records_error(tmp_path):
    store = make_store(tmp_path)
    state_path = tmp_path / "state.json"
    before = [entry.from_date for entry in store.get().rates]

    result = cbr.sync_rates(
        store,
        today=date(2024, 12, 31),
        client=client_returning("", status_code=500),
        state_path=state_path,
    )

    assert result["synced"] is False
    assert "500" in result["reason"]
    assert [entry.from_date for entry in store.get().rates] == before
    assert cbr.load_state(state_path).last_error


def test_sync_respects_auto_sync_switch(tmp_path):
    store = make_store(tmp_path)
    data = json.loads((store.path).read_text(encoding="utf-8"))
    data["cbr_rates"]["auto_sync"] = False
    store.save(data, author="tests")
    state_path = tmp_path / "state.json"

    result = cbr.sync_rates(
        store, today=date(2024, 12, 31), client=client_returning(SAMPLE_XML), state_path=state_path
    )

    assert result["synced"] is False
    assert "выключена" in result["reason"]


def test_rate_status_flags_stale_data(tmp_path):
    store = make_store(tmp_path)
    state_path = tmp_path / "state.json"
    cbr.save_state(cbr.SyncState(last_success_at=None), state_path)

    status = cbr.rate_status(store.get(), state_path)

    assert status["is_stale"] is True
    assert status["warning"] and "Проверьте актуальность" in status["warning"]


def test_rate_status_is_clean_after_recent_sync(tmp_path):
    store = make_store(tmp_path)
    state_path = tmp_path / "state.json"
    cbr.save_state(
        cbr.SyncState(last_success_at=datetime.now(timezone.utc).isoformat()), state_path
    )

    status = cbr.rate_status(store.get(), state_path)

    assert status["is_stale"] is False
    assert status["warning"] is None
    assert status["rate"] == 16.0


def test_rate_status_goes_stale_after_threshold(tmp_path):
    store = make_store(tmp_path)
    state_path = tmp_path / "state.json"
    old = datetime.now(timezone.utc) - timedelta(hours=cbr.STALE_AFTER_HOURS + 1)
    cbr.save_state(cbr.SyncState(last_success_at=old.isoformat()), state_path)

    assert cbr.rate_status(store.get(), state_path)["is_stale"] is True
