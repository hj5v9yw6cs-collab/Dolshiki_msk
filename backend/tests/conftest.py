import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Тестовая БД и токен — до импорта приложения, иначе подхватится боевая конфигурация.
_TEST_DB = Path(tempfile.mkdtemp(prefix="dolshiki-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["ADMIN_TOKEN"] = "test-admin-token"

from app.core.legal_config import parse_config  # noqa: E402


def config_dict(**overrides):
    """Детерминированный тестовый конфиг.

    Намеренно не используем боевой legal-config.json: тесты проверяют
    механику расчёта, а не конкретные исторические ставки, которые будут
    меняться.
    """
    data = {
        "version": 99,
        "updated_at": "2026-01-01",
        "updated_by": "tests",
        "day_count_rule": {
            "mode": "inclusive_both_ends",
            "start_offset_days": 1,
            "basis": "тестовое правило",
            "requires_lawyer_review": False,
        },
        "cbr_rates": {
            "source": "test",
            "auto_sync": False,
            "requires_lawyer_review": False,
            "items": [
                {"from": "2020-01-01", "rate": 6.0},
                {"from": "2022-01-01", "rate": 10.0},
                {"from": "2023-01-01", "rate": 20.0},
            ],
        },
        "moratoriums": [
            {
                "from": "2022-06-01",
                "to": "2022-08-31",
                "basis": "тестовый мораторий",
                "requires_lawyer_review": False,
            }
        ],
        "rate_caps": [],
        "delay_penalty": {
            "divisor": 300,
            "individual_multiplier": 2,
            "legal_entity_multiplier": 1,
            "basis": "ч. 2 ст. 6 214-ФЗ",
            "default_rate_mode": "on_obligation_date",
            "requires_lawyer_review": False,
        },
        "defects_penalty": {
            "divisor": 150,
            "multiplier": 1,
            "response_period_days": 10,
            "cap_at_repair_cost": True,
            "apply_moratoriums": True,
            "basis": "ст. 7, ст. 10 214-ФЗ",
            "requires_lawyer_review": False,
        },
        "consumer_penalty": {
            "percent": 0,
            "base": "neustoyka_and_moral_harm",
            "basis": "ст. 10 214-ФЗ",
            "requires_lawyer_review": False,
        },
        "disclaimer": "Предварительный расчёт.",
    }
    data.update(overrides)
    return data


@pytest.fixture
def config():
    return parse_config(config_dict())


@pytest.fixture
def make_config():
    def _make(**overrides):
        return parse_config(config_dict(**overrides))

    return _make


@pytest.fixture
def api_client(tmp_path):
    """TestClient с подменённым юридическим конфигом и чистыми лимитерами."""
    from fastapi.testclient import TestClient

    from app.api.deps import calc_limiter, lead_limiter
    from app.core.legal_config import store
    from app.main import app

    config_path = tmp_path / "legal-config.json"
    config_path.write_text(
        json.dumps(config_dict(), ensure_ascii=False), encoding="utf-8"
    )

    original_path = store.path
    store.path = config_path
    store.reload()
    calc_limiter._hits.clear()
    lead_limiter._hits.clear()

    with TestClient(app) as client:
        yield client

    store.path = original_path
    store.reload()
