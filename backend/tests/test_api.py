"""Тесты HTTP-слоя."""

from conftest import config_dict

ADMIN = {"Authorization": "Bearer test-admin-token-dlinnyy-dostatochno"}

DELAY_PAYLOAD = {
    "contract_price": "1000000",
    "due_date": "2022-01-10",
    "actual_date": "2022-02-09",
    "is_individual": True,
}

LEAD_PAYLOAD = {
    "name": "Иван Петров",
    "phone": "+7 999 123-45-67",
    "topic": "neustoyka",
    "region": "msk",
    "consent": True,
}


def test_health(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_calc_delay_returns_full_breakdown(api_client):
    response = api_client.post("/api/v1/calc/delay", json=DELAY_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == "20000.00"
    assert body["total_display"] == "20 000,00"
    assert len(body["segments"]) == 1
    assert body["segments"][0]["formula"].startswith("1 000 000,00 × 30 дней × 10% / 300 × 2")
    assert body["calculation_id"]
    assert "rate_status" in body
    assert body["disclaimer"]


def test_calc_delay_rejects_zero_price(api_client):
    response = api_client.post("/api/v1/calc/delay", json={**DELAY_PAYLOAD, "contract_price": "0"})

    assert response.status_code == 422


def test_calc_delay_reports_missing_historical_rate(api_client):
    response = api_client.post(
        "/api/v1/calc/delay",
        json={**DELAY_PAYLOAD, "due_date": "2015-01-01", "actual_date": "2015-03-01"},
    )

    assert response.status_code == 400
    assert "ключевой ставки" in response.json()["detail"]


def test_calc_defects_returns_lines(api_client):
    response = api_client.post(
        "/api/v1/calc/defects",
        json={
            "repair_cost": "300000",
            "demand_served_date": "2022-01-01",
            "satisfied_date": "2022-01-21",
            "expertise_cost": "45000",
        },
    )

    assert response.status_code == 200
    body = response.json()
    codes = [line["code"] for line in body["lines"]]
    assert codes == ["repair_cost", "neustoyka", "expertise"]
    assert body["total"] == "347000.00"


def test_saved_calculation_can_be_read_back(api_client):
    calculation_id = api_client.post("/api/v1/calc/delay", json=DELAY_PAYLOAD).json()["calculation_id"]

    response = api_client.get(f"/api/v1/calc/{calculation_id}")

    assert response.status_code == 200
    assert response.json()["total"] == "20000.00"


def test_unknown_calculation_returns_404(api_client):
    assert api_client.get("/api/v1/calc/does-not-exist").status_code == 404


def test_print_view_renders_court_ready_table(api_client):
    calculation_id = api_client.post("/api/v1/calc/delay", json=DELAY_PAYLOAD).json()["calculation_id"]

    response = api_client.get(f"/api/v1/calc/{calculation_id}/print")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    page = response.text
    assert "ИТОГО к взысканию" in page
    assert "20 000,00" in page
    assert "требует проверки юристом" in page


def test_rate_endpoint_reports_staleness(api_client):
    response = api_client.get("/api/v1/rate")

    assert response.status_code == 200
    body = response.json()
    assert "rate" in body and "is_stale" in body


def test_public_legal_config_lists_pending_review(api_client):
    response = api_client.get("/api/v1/legal-config")

    assert response.status_code == 200
    body = response.json()
    assert "moratoriums" in body
    assert body["pending_lawyer_review"] == []  # тестовый конфиг подтверждён


# --- Заявки ----------------------------------------------------------------


def test_lead_is_created_with_consent(api_client):
    response = api_client.post("/api/v1/leads", json=LEAD_PAYLOAD)

    assert response.status_code == 201
    assert response.json()["id"]


def test_lead_without_consent_is_rejected(api_client):
    response = api_client.post("/api/v1/leads", json={**LEAD_PAYLOAD, "consent": False})

    assert response.status_code == 400
    assert "персональных данных" in response.json()["detail"]


def test_lead_honeypot_silently_drops_bots(api_client):
    response = api_client.post("/api/v1/leads", json={**LEAD_PAYLOAD, "website": "http://spam"})

    assert response.status_code == 201
    assert response.json()["id"] is None


def test_lead_with_bad_phone_is_rejected(api_client):
    response = api_client.post("/api/v1/leads", json={**LEAD_PAYLOAD, "phone": "нет"})

    assert response.status_code == 422


def test_lead_can_reference_a_calculation(api_client):
    calculation_id = api_client.post("/api/v1/calc/delay", json=DELAY_PAYLOAD).json()["calculation_id"]

    created = api_client.post(
        "/api/v1/leads", json={**LEAD_PAYLOAD, "calculation_id": calculation_id}
    )
    assert created.status_code == 201

    listed = api_client.get("/api/v1/leads", headers=ADMIN).json()
    match = next(item for item in listed["items"] if item["id"] == created.json()["id"])
    assert match["calculation_total"] == "20 000,00"


def test_lead_with_unknown_calculation_is_rejected(api_client):
    response = api_client.post(
        "/api/v1/leads", json={**LEAD_PAYLOAD, "calculation_id": "no-such-id"}
    )

    assert response.status_code == 400


def test_lead_rate_limit_kicks_in(api_client):
    for _ in range(5):
        assert api_client.post("/api/v1/leads", json=LEAD_PAYLOAD).status_code == 201

    response = api_client.post("/api/v1/leads", json=LEAD_PAYLOAD)

    assert response.status_code == 429


def test_lead_list_requires_admin_token(api_client):
    assert api_client.get("/api/v1/leads").status_code == 401
    assert api_client.get("/api/v1/leads", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api_client.get("/api/v1/leads", headers=ADMIN).status_code == 200


# --- Админка ---------------------------------------------------------------


def test_admin_can_read_and_update_config(api_client):
    current = api_client.get("/api/v1/admin/legal-config", headers=ADMIN).json()
    assert current["version"] == 99

    updated = dict(current)
    updated["moratoriums"] = []
    response = api_client.put(
        "/api/v1/admin/legal-config",
        headers=ADMIN,
        json={"config": updated, "author": "lawyer@dolshikirf.ru", "comment": "убрал мораторий"},
    )

    assert response.status_code == 200
    assert "moratoriums" in response.json()["changed"]
    assert api_client.get("/api/v1/legal-config").json()["moratoriums"] == []


def test_invalid_config_is_rejected_without_saving(api_client):
    before = api_client.get("/api/v1/admin/legal-config", headers=ADMIN).json()
    broken = dict(before)
    broken["cbr_rates"] = {"items": []}

    response = api_client.put(
        "/api/v1/admin/legal-config",
        headers=ADMIN,
        json={"config": broken, "author": "lawyer@dolshikirf.ru"},
    )

    assert response.status_code == 400
    after = api_client.get("/api/v1/admin/legal-config", headers=ADMIN).json()
    assert after["cbr_rates"]["items"] == before["cbr_rates"]["items"]


def test_config_changes_are_logged(api_client):
    payload = config_dict()
    payload["disclaimer"] = "Изменённый текст."
    api_client.put(
        "/api/v1/admin/legal-config",
        headers=ADMIN,
        json={"config": payload, "author": "lawyer@dolshikirf.ru", "comment": "правка текста"},
    )

    history = api_client.get("/api/v1/admin/legal-config/history", headers=ADMIN).json()

    assert history["count"] >= 1
    latest = history["items"][0]
    assert latest["author"] == "lawyer@dolshikirf.ru"
    assert "правка текста" in latest["changed"]


def test_admin_endpoints_require_token(api_client):
    assert api_client.get("/api/v1/admin/legal-config").status_code == 401
    assert api_client.post("/api/v1/admin/rate/sync").status_code == 401


# --- переменные окружения --------------------------------------------------


def test_empty_env_variable_falls_back_to_default(monkeypatch):
    """В .env переменную часто оставляют пустой — это должно значить
    «взять значение по умолчанию», а не пустую строку."""
    from app.env import env, env_list

    monkeypatch.setenv("SOME_SETTING", "")
    assert env("SOME_SETTING", "по умолчанию") == "по умолчанию"

    monkeypatch.setenv("SOME_SETTING", "   ")
    assert env("SOME_SETTING", "по умолчанию") == "по умолчанию"

    monkeypatch.setenv("SOME_SETTING", " значение ")
    assert env("SOME_SETTING", "по умолчанию") == "значение"

    monkeypatch.delenv("SOME_SETTING")
    assert env("SOME_SETTING", "по умолчанию") == "по умолчанию"


def test_env_list_splits_and_drops_blanks(monkeypatch):
    from app.env import env_list

    monkeypatch.setenv("ORIGINS", "https://a.ru, https://b.ru ,")
    assert env_list("ORIGINS") == ["https://a.ru", "https://b.ru"]

    monkeypatch.setenv("ORIGINS", "")
    assert env_list("ORIGINS", "https://default.ru") == ["https://default.ru"]


def test_database_url_is_always_a_usable_url():
    """Пустой DATABASE_URL в .env раньше ронял приложение на старте сервера:
    create_engine("") падает. Теперь пустое значение равно отсутствующему.

    Модуль здесь намеренно не перезагружается — это подменило бы движок
    базы у всех остальных тестов."""
    import app.db

    assert app.db.DATABASE_URL
    assert "://" in app.db.DATABASE_URL


# --- смена пароля ----------------------------------------------------------


def test_user_changes_own_password(api_client, staff):
    response = api_client.post(
        "/api/v1/auth/password",
        json={"current_password": "lawyer-pass-1", "new_password": "novyy-parol-2026"},
        headers=staff["lawyer"],
    )

    assert response.status_code == 200
    assert api_client.post(
        "/api/v1/auth/login",
        json={"email": "urist@dolshikirf.ru", "password": "novyy-parol-2026"},
    ).status_code == 200


def test_wrong_current_password_is_refused(api_client, staff):
    response = api_client.post(
        "/api/v1/auth/password",
        json={"current_password": "ne-tot-parol", "new_password": "novyy-parol-2026"},
        headers=staff["lawyer"],
    )

    assert response.status_code == 400
    assert "неверен" in response.json()["detail"]


def test_short_new_password_is_refused(api_client, staff):
    response = api_client.post(
        "/api/v1/auth/password",
        json={"current_password": "lawyer-pass-1", "new_password": "korotko"},
        headers=staff["lawyer"],
    )

    assert response.status_code == 400


# --- ограничение попыток входа ---------------------------------------------


def test_forwarded_header_from_the_outside_does_not_reset_the_limit(api_client, staff):
    """Подделанный X-Forwarded-For не должен давать новый счётчик попыток.

    Заголовок присылает браузер, а не только прокси. Пока брался первый
    адрес из списка, подбор пароля обходил ограничение полностью: меняй
    заголовок в каждом запросе — и попытки считаются заново.
    """
    wrong = {"email": "urist@dolshikirf.ru", "password": "не тот пароль"}

    codes = []
    for attempt in range(14):
        response = api_client.post(
            "/api/v1/auth/login", json=wrong,
            headers={"X-Forwarded-For": f"203.0.113.{attempt}"},
        )
        codes.append(response.status_code)

    assert 429 in codes, "подбор не был остановлен"


def test_attempts_are_counted_per_account_too(api_client, staff):
    """Подбор с разных адресов по одной учётной записи тоже ограничен."""
    from app.api.deps import login_limiter

    for _ in range(12):
        login_limiter.reset()  # как будто каждый запрос с нового адреса
        response = api_client.post(
            "/api/v1/auth/login",
            json={"email": "urist@dolshikirf.ru", "password": "не тот пароль"},
        )

    assert response.status_code == 429


def test_short_admin_token_is_not_accepted(api_client, monkeypatch):
    """Заготовка из .env не должна молча стать рабочим ключом руководителя."""
    monkeypatch.setenv("ADMIN_TOKEN", "korotkiy")

    response = api_client.get(
        "/api/v1/admin/legal-config/history", headers={"Authorization": "Bearer korotkiy"}
    )

    assert response.status_code == 401
