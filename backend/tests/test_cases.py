"""Тесты Фазы 2: вход, роли, ведение дел."""

from datetime import date, timedelta

import pytest

from app.core.security import hash_password, verify_password

MANAGER = {"email": "boss@garantlc.ru", "password": "manager-pass-1", "name": "Руководитель"}
LAWYER = {"email": "urist@garantlc.ru", "password": "lawyer-pass-1", "name": "Юрист Ирина"}

NEW_CASE = {
    "client_name": "Иван Петров",
    "client_phone": "+7 900 111-22-33",
    "service_type": "delay",
    "region": "msk",
    "project": "ЖК Символ",
    "contract_price": "8500000",
    "due_date": "2021-12-30",
    "developer_name": "Донстрой",
}


@pytest.fixture
def staff(api_client):
    """Заводит руководителя и юриста, возвращает их токены."""
    from app.db import SessionLocal
    from app.models import User

    session = SessionLocal()
    try:
        for data, role in ((MANAGER, "manager"), (LAWYER, "lawyer")):
            if not session.query(User).filter(User.email == data["email"]).first():
                session.add(User(
                    email=data["email"], name=data["name"], role=role,
                    password_hash=hash_password(data["password"]),
                ))
        session.commit()
    finally:
        session.close()

    def login(data):
        response = api_client.post(
            "/api/v1/auth/login", json={"email": data["email"], "password": data["password"]}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["token"]}

    return {"manager": login(MANAGER), "lawyer": login(LAWYER)}


# --- пароли ----------------------------------------------------------------


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("одинаковый-пароль")
    second = hash_password("одинаковый-пароль")

    assert first != second, "соль должна быть разной"
    assert verify_password("одинаковый-пароль", first)
    assert verify_password("одинаковый-пароль", second)
    assert not verify_password("другой-пароль", first)


def test_short_password_is_rejected():
    with pytest.raises(ValueError, match="8 символов"):
        hash_password("1234567")


def test_broken_hash_does_not_crash_verification():
    assert not verify_password("пароль", "мусор")
    assert not verify_password("пароль", "")


# --- вход ------------------------------------------------------------------


def test_login_returns_token_and_user(api_client, staff):
    response = api_client.post(
        "/api/v1/auth/login", json={"email": MANAGER["email"], "password": MANAGER["password"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["user"]["role"] == "manager"
    assert body["user"]["role_title"] == "Руководитель"


def test_login_with_wrong_password_is_rejected(api_client, staff):
    response = api_client.post(
        "/api/v1/auth/login", json={"email": MANAGER["email"], "password": "не тот"}
    )

    assert response.status_code == 401


def test_unknown_email_gives_the_same_answer_as_wrong_password(api_client, staff):
    """Ответ не должен выдавать, заведён ли такой сотрудник."""
    unknown = api_client.post(
        "/api/v1/auth/login", json={"email": "nobody@garantlc.ru", "password": "какой-то"}
    )
    wrong = api_client.post(
        "/api/v1/auth/login", json={"email": MANAGER["email"], "password": "не тот"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_me_returns_current_user(api_client, staff):
    response = api_client.get("/api/v1/auth/me", headers=staff["lawyer"])

    assert response.status_code == 200
    assert response.json()["name"] == LAWYER["name"]


def test_requests_without_token_are_rejected(api_client, staff):
    assert api_client.get("/api/v1/cases").status_code == 401
    assert api_client.get("/api/v1/cases", headers={"Authorization": "Bearer nonsense-token"}).status_code == 401


def test_logout_kills_the_session(api_client, staff):
    token = api_client.post(
        "/api/v1/auth/login", json={"email": LAWYER["email"], "password": LAWYER["password"]}
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}

    assert api_client.get("/api/v1/auth/me", headers=headers).status_code == 200
    api_client.post("/api/v1/auth/logout", headers=headers)
    assert api_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_expired_session_is_rejected(api_client, staff):
    from datetime import datetime, timezone

    from app.core.security import token_fingerprint
    from app.db import SessionLocal
    from app.models import Session as SessionModel

    token = api_client.post(
        "/api/v1/auth/login", json={"email": LAWYER["email"], "password": LAWYER["password"]}
    ).json()["token"]

    session = SessionLocal()
    try:
        record = session.query(SessionModel).filter(
            SessionModel.token_hash == token_fingerprint(token)
        ).one()
        record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert "истекла" in response.json()["detail"]


def test_session_token_is_not_stored_in_plain_text(api_client, staff):
    from app.db import SessionLocal
    from app.models import Session as SessionModel

    token = api_client.post(
        "/api/v1/auth/login", json={"email": LAWYER["email"], "password": LAWYER["password"]}
    ).json()["token"]

    session = SessionLocal()
    try:
        stored = [row.token_hash for row in session.query(SessionModel).all()]
    finally:
        session.close()

    assert token not in stored


# --- дела ------------------------------------------------------------------


def test_case_gets_number_and_appears_in_list(api_client, staff):
    created = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"])

    assert created.status_code == 201, created.text
    case = created.json()
    assert case["number"].startswith(str(date.today().year))
    assert case["stage"] == "new"
    assert case["stage_title"] == "Новое"
    assert case["client_name"] == "Иван Петров"
    assert case["developer"] == "Донстрой"
    assert case["lawyer_name"] == LAWYER["name"], "автор становится ответственным"

    listed = api_client.get("/api/v1/cases", headers=staff["lawyer"]).json()
    assert any(item["id"] == case["id"] for item in listed["items"])


def test_case_numbers_do_not_repeat(api_client, staff):
    numbers = {
        api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["number"]
        for _ in range(3)
    }

    assert len(numbers) == 3


def test_developer_is_reused_not_duplicated(api_client, staff):
    first = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()
    second = api_client.post(
        "/api/v1/cases", json={**NEW_CASE, "developer_name": "донстрой"}, headers=staff["lawyer"]
    ).json()

    assert first["developer_id"] == second["developer_id"]


def test_unknown_stage_is_rejected(api_client, staff):
    response = api_client.post(
        "/api/v1/cases", json={**NEW_CASE, "stage": "выдуманная"}, headers=staff["lawyer"]
    )

    assert response.status_code == 400


def test_stage_change_is_recorded_in_the_feed(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    response = api_client.post(
        f"/api/v1/cases/{case_id}/stage",
        json={"stage": "claim", "comment": "Отправили почтой"},
        headers=staff["lawyer"],
    )

    assert response.status_code == 200
    case = response.json()
    assert case["stage"] == "claim"
    latest = case["events"][0]
    assert latest["kind"] == "stage"
    assert "Новое → Претензия" in latest["text"]
    assert "Отправили почтой" in latest["text"]
    assert latest["author"] == LAWYER["name"]


def test_final_stage_sets_closed_at(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    closed = api_client.post(
        f"/api/v1/cases/{case_id}/stage", json={"stage": "closed"}, headers=staff["lawyer"]
    ).json()
    assert closed["closed_at"]

    reopened = api_client.post(
        f"/api/v1/cases/{case_id}/stage", json={"stage": "hearings"}, headers=staff["lawyer"]
    ).json()
    assert reopened["closed_at"] is None


def test_field_edits_are_recorded_with_readable_values(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    updated = api_client.patch(
        f"/api/v1/cases/{case_id}",
        json={"court_name": "Никулинский районный суд", "amount_claimed": "2174725.00"},
        headers=staff["lawyer"],
    ).json()

    assert updated["court_name"] == "Никулинский районный суд"
    text = updated["events"][0]["text"]
    assert "суд: — → Никулинский районный суд" in text
    assert "заявлено: — → 2 174 725,00 ₽" in text


def test_unchanged_values_do_not_create_feed_noise(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    before = len(api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()["events"])

    api_client.patch(f"/api/v1/cases/{case_id}", json={"project": "ЖК Символ"}, headers=staff["lawyer"])

    after = len(api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()["events"])
    assert after == before


def test_sending_a_claim_sets_the_response_deadline(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    updated = api_client.patch(
        f"/api/v1/cases/{case_id}", json={"claim_sent_on": "2026-08-10"}, headers=staff["lawyer"]
    ).json()

    assert updated["claim_response_deadline"] == "2026-08-20"


def test_explicit_deadline_is_not_overwritten(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    updated = api_client.patch(
        f"/api/v1/cases/{case_id}",
        json={"claim_sent_on": "2026-08-10", "claim_response_deadline": "2026-09-01"},
        headers=staff["lawyer"],
    ).json()

    assert updated["claim_response_deadline"] == "2026-09-01"


def test_notes_land_in_the_feed(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    case = api_client.post(
        f"/api/v1/cases/{case_id}/notes",
        json={"text": "Клиент принесёт ДДУ в понедельник"},
        headers=staff["lawyer"],
    ).json()

    assert case["events"][0]["kind"] == "note"
    assert case["events"][0]["text"] == "Клиент принесёт ДДУ в понедельник"


def test_unknown_case_returns_404(api_client, staff):
    assert api_client.get("/api/v1/cases/нет-такого", headers=staff["lawyer"]).status_code == 404


# --- сроки -----------------------------------------------------------------


def test_overdue_deadline_is_flagged(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    api_client.patch(
        f"/api/v1/cases/{case_id}",
        json={"claim_response_deadline": yesterday},
        headers=staff["lawyer"],
    )
    api_client.post(f"/api/v1/cases/{case_id}/stage", json={"stage": "claim_wait"}, headers=staff["lawyer"])

    case = api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()
    assert case["deadline"]["is_overdue"] is True
    assert case["deadline"]["title"] == "Ответ на претензию"

    overdue = api_client.get("/api/v1/cases?only_overdue=true", headers=staff["lawyer"]).json()
    assert any(item["id"] == case_id for item in overdue["items"])


def test_closed_case_has_no_deadline(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    api_client.patch(
        f"/api/v1/cases/{case_id}",
        json={"next_hearing_on": (date.today() + timedelta(days=2)).isoformat()},
        headers=staff["lawyer"],
    )
    assert api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()["deadline"]

    api_client.post(f"/api/v1/cases/{case_id}/stage", json={"stage": "closed"}, headers=staff["lawyer"])

    assert api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()["deadline"] is None


def test_nearest_deadline_wins(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    api_client.patch(
        f"/api/v1/cases/{case_id}",
        json={
            "next_hearing_on": (date.today() + timedelta(days=20)).isoformat(),
            "claim_response_deadline": (date.today() + timedelta(days=2)).isoformat(),
        },
        headers=staff["lawyer"],
    )

    case = api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()
    assert case["deadline"]["kind"] == "claim_response"
    assert case["deadline"]["is_soon"] is True


# --- роли ------------------------------------------------------------------


def test_lawyer_does_not_see_the_fee(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    api_client.patch(f"/api/v1/cases/{case_id}", json={"fee": "150000"}, headers=staff["manager"])

    as_manager = api_client.get(f"/api/v1/cases/{case_id}", headers=staff["manager"]).json()
    as_lawyer = api_client.get(f"/api/v1/cases/{case_id}", headers=staff["lawyer"]).json()

    assert as_manager["fee_display"] == "150 000,00"
    assert "fee" not in as_lawyer


def test_lawyer_cannot_change_the_fee(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]

    response = api_client.patch(f"/api/v1/cases/{case_id}", json={"fee": "150000"}, headers=staff["lawyer"])

    assert response.status_code == 403
    assert "руководитель" in response.json()["detail"]


def test_lawyer_sees_all_cases(api_client, staff):
    """На четверых сотрудников разделение «только свои дела» мешает работе."""
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["manager"]).json()["id"]

    listed = api_client.get("/api/v1/cases", headers=staff["lawyer"]).json()

    assert any(item["id"] == case_id for item in listed["items"])


def test_money_summary_is_manager_only(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    api_client.patch(
        f"/api/v1/cases/{case_id}",
        json={"amount_awarded": "2000000", "amount_received": "1500000"},
        headers=staff["manager"],
    )

    assert "money" in api_client.get("/api/v1/dashboard", headers=staff["manager"]).json()
    assert "money" not in api_client.get("/api/v1/dashboard", headers=staff["lawyer"]).json()


def test_admin_config_requires_manager(api_client, staff):
    assert api_client.get("/api/v1/admin/legal-config", headers=staff["manager"]).status_code == 200

    response = api_client.get("/api/v1/admin/legal-config", headers=staff["lawyer"])
    assert response.status_code == 403
    assert "руководител" in response.json()["detail"].lower()


# --- фильтры и сводка ------------------------------------------------------


def test_filters_narrow_the_list(api_client, staff):
    api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"])
    api_client.post(
        "/api/v1/cases",
        json={**NEW_CASE, "client_name": "Пётр Сидоров", "region": "kzn", "service_type": "defects"},
        headers=staff["lawyer"],
    )

    by_region = api_client.get("/api/v1/cases?region=kzn", headers=staff["lawyer"]).json()
    assert by_region["count"] == 1
    assert by_region["items"][0]["client_name"] == "Пётр Сидоров"

    by_service = api_client.get("/api/v1/cases?service_type=defects", headers=staff["lawyer"]).json()
    assert by_service["count"] == 1

    by_search = api_client.get("/api/v1/cases?q=Сидоров", headers=staff["lawyer"]).json()
    assert by_search["count"] == 1


def test_only_active_hides_finished_cases(api_client, staff):
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    api_client.post(f"/api/v1/cases/{case_id}/stage", json={"stage": "closed"}, headers=staff["lawyer"])

    active = api_client.get("/api/v1/cases?only_active=true", headers=staff["lawyer"]).json()

    assert all(item["id"] != case_id for item in active["items"])


def test_dashboard_counts_by_stage(api_client, staff):
    api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"])
    case_id = api_client.post("/api/v1/cases", json=NEW_CASE, headers=staff["lawyer"]).json()["id"]
    api_client.post(f"/api/v1/cases/{case_id}/stage", json={"stage": "hearings"}, headers=staff["lawyer"])

    summary = api_client.get("/api/v1/dashboard", headers=staff["lawyer"]).json()

    assert summary["total"] >= 2
    assert summary["by_stage"].get("hearings") == 1


def test_meta_lists_stages_and_users(api_client, staff):
    meta = api_client.get("/api/v1/meta", headers=staff["lawyer"]).json()

    assert meta["stages"][0]["code"] == "new"
    assert {user["name"] for user in meta["users"]} >= {MANAGER["name"], LAWYER["name"]}
    assert meta["can_see_money"] is False


# --- заявка в дело ---------------------------------------------------------


def make_lead(api_client, **overrides):
    payload = {
        "name": "Анна Смирнова", "phone": "+7 917 000-11-22", "topic": "defects",
        "region": "kzn", "consent": True, "project": "ЖК Весна",
    }
    payload.update(overrides)
    return api_client.post("/api/v1/leads", json=payload).json()["id"]


def test_lead_becomes_a_case(api_client, staff):
    lead_id = make_lead(api_client)

    response = api_client.post(f"/api/v1/leads/{lead_id}/convert", json={}, headers=staff["lawyer"])

    assert response.status_code == 201, response.text
    case = response.json()
    assert case["client_name"] == "Анна Смирнова"
    assert case["service_type"] == "defects", "тип услуги берётся из темы заявки"
    assert case["region"] == "kzn"
    assert case["project"] == "ЖК Весна"
    assert case["stage"] == "qualification"
    assert case["lead_id"] == lead_id
    assert "из заявки" in case["events"][-1]["text"]


def test_converted_lead_is_marked_and_cannot_be_converted_twice(api_client, staff):
    lead_id = make_lead(api_client)
    api_client.post(f"/api/v1/leads/{lead_id}/convert", json={}, headers=staff["lawyer"])

    again = api_client.post(f"/api/v1/leads/{lead_id}/convert", json={}, headers=staff["lawyer"])
    assert again.status_code == 409
    assert "уже заведено" in again.json()["detail"]

    leads = api_client.get("/api/v1/leads", headers=staff["lawyer"]).json()
    converted = next(item for item in leads["items"] if item["id"] == lead_id)
    assert converted["status"] == "converted"


def test_calculation_from_the_site_becomes_the_claimed_amount(api_client, staff):
    calculation = api_client.post("/api/v1/calc/delay", json={
        "contract_price": "1000000", "due_date": "2022-01-10", "actual_date": "2022-02-09",
    }).json()
    lead_id = make_lead(api_client, calculation_id=calculation["calculation_id"], topic="neustoyka")

    case = api_client.post(f"/api/v1/leads/{lead_id}/convert", json={}, headers=staff["lawyer"]).json()

    assert case["amount_claimed"] == "20000.00"
    assert case["calculation_id"] == calculation["calculation_id"]
    assert "20 000,00" in case["events"][-1]["text"]


def test_converting_an_unknown_lead_returns_404(api_client, staff):
    assert api_client.post("/api/v1/leads/нет/convert", json={}, headers=staff["lawyer"]).status_code == 404
