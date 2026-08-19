"""Тесты Фазы 3: классификация, реквизиты, хранение, загрузка, реестр."""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.documents import (
    StorageError,
    build_checklist,
    build_filename,
    case_folder,
    check_upload,
    classify,
    extract_requisites,
    resolve_target,
    safe_name,
    save_stream,
    unique_path,
)

DDU_TEXT = (
    "ДОГОВОР № 12/АБ-345 участия в долевом строительстве от 15.05.2021 г. "
    "Застройщик обязуется передать квартиру № 145 не позднее 30.12.2021. "
    "Цена договора составляет 8 500 000 руб."
)


# --- классификация ---------------------------------------------------------


def test_ddu_is_recognised_by_text_even_with_useless_filename():
    guess = classify("скан_001.pdf", DDU_TEXT)

    assert guess.code == "ddu"
    assert guess.needs_review is False
    assert "участия в долевом строительстве" in guess.explanation


def test_filename_alone_gives_a_weak_guess():
    """Имя файла — слабый признак: часто это «Документ1.pdf»."""
    guess = classify("паспорт.pdf", "")

    assert guess.code == "passport"
    assert guess.confidence < 1.0


def test_unknown_document_goes_to_manual_review():
    guess = classify("IMG_20260817.jpg", "")

    assert guess.code == "other"
    assert guess.needs_review is True
    assert "вручную" in guess.explanation


def test_stop_word_prevents_wrong_type():
    """«Ответ на претензию» — это ответ застройщика, а не претензия."""
    guess = classify("ответ.pdf", "Ответ на претензию. Рассмотрев вашу претензию, сообщаем")

    assert guess.code == "developer_reply"


def test_amendment_is_not_confused_with_the_contract():
    guess = classify(
        "допник.pdf",
        "Дополнительное соглашение к договору участия в долевом строительстве",
    )

    assert guess.code == "ddu_amendment"


def test_court_decision_recognised_by_formula():
    guess = classify("решение.pdf", "ИМЕНЕМ РОССИЙСКОЙ ФЕДЕРАЦИИ суд решил: взыскать")

    assert guess.code == "court_decision"
    assert guess.needs_review is False


def test_case_and_yo_do_not_matter():
    assert classify("АКТ ПРИЁМА-ПЕРЕДАЧИ.PDF", "").code == "act"
    assert classify("акт приема-передачи.pdf", "").code == "act"


# --- реквизиты -------------------------------------------------------------


def test_requisites_are_pulled_from_the_contract():
    requisites = extract_requisites(DDU_TEXT, "ddu")

    assert requisites.contract_number == "12/АБ-345"
    assert requisites.contract_date == date(2021, 5, 15)
    assert requisites.contract_price == Decimal("8500000")
    assert requisites.apartment == "145"
    assert requisites.due_date == date(2021, 12, 30)


def test_worded_dates_are_understood():
    requisites = extract_requisites(
        'Договор № 7 от «15» мая 2021 года. Застройщик обязуется передать '
        'объект не позднее «31» декабря 2021 года.',
        "ddu",
    )

    assert requisites.contract_date == date(2021, 5, 15)
    assert requisites.due_date == date(2021, 12, 31)


def test_contract_figures_are_not_taken_from_other_documents():
    """В решении суда те же числа означают совсем другое."""
    requisites = extract_requisites(
        "Решение суда от 10.02.2026. Взыскать 2 174 725 руб.", "court_decision"
    )

    assert requisites.contract_price is None
    assert requisites.due_date is None


def test_empty_text_gives_empty_requisites():
    assert extract_requisites("", "ddu").is_empty


def test_broken_date_does_not_crash():
    assert extract_requisites("Договор № 5 от 32.13.2021", "ddu").contract_date is None


# --- имена и пути ----------------------------------------------------------


def test_cyrillic_names_are_transliterated():
    assert safe_name("Договор ДДУ №12/АБ") == "Dogovor_DDU_No12_AB"


def test_filename_follows_the_template():
    name = build_filename("2026-001", "Петров Иван Иванович", "ddu", date(2021, 5, 15), ".pdf")

    assert name == "Petrov_2026-001_Dogovor_dolevogo_uchastiya_15.05.2021.pdf"


def test_case_folder_is_grouped_by_year(tmp_path):
    folder = case_folder(tmp_path, "2026-001", "Петров Иван", date(2026, 3, 1))

    assert folder == tmp_path / "cases" / "2026" / "Petrov_2026-001"


def test_path_traversal_is_blocked(tmp_path):
    """Имя файла приходит от пользователя — выход из папки дела недопустим."""
    base = tmp_path / "case"
    base.mkdir()

    target = resolve_target(base, "01_Договор", "../../../etc/passwd")

    # Опасное имя обезврежено, а файл остаётся внутри папки дела.
    assert base in target.parents
    assert ".." not in target.parts
    assert target.name == "etc_passwd"


def test_traversal_through_folder_is_blocked(tmp_path):
    base = tmp_path / "case"
    base.mkdir()

    target = resolve_target(base, "../../secrets", "file.pdf")

    assert base in target.parents


def test_same_name_does_not_overwrite(tmp_path):
    first = tmp_path / "doc.pdf"
    first.write_bytes(b"1")

    second = unique_path(first)

    assert second.name == "doc_2.pdf"


# --- проверки приёма -------------------------------------------------------


def test_executables_are_rejected():
    with pytest.raises(StorageError, match=r"\.exe"):
        check_upload("вирус.exe", 100)


def test_html_is_rejected():
    with pytest.raises(StorageError):
        check_upload("страница.html", 100)


def test_unknown_format_is_rejected():
    with pytest.raises(StorageError, match="не поддерживается"):
        check_upload("файл.xyz", 100)


def test_file_without_extension_is_rejected():
    with pytest.raises(StorageError, match="расширения"):
        check_upload("документ", 100)


def test_too_big_file_is_rejected():
    with pytest.raises(StorageError, match="МБ"):
        check_upload("скан.pdf", 30 * 1024 * 1024)


def test_empty_file_is_rejected():
    with pytest.raises(StorageError, match="пустой"):
        check_upload("скан.pdf", 0)


def test_oversized_stream_leaves_no_file_behind(tmp_path):
    target = tmp_path / "big.pdf"
    source = io.BytesIO(b"x" * 5000)

    with pytest.raises(StorageError):
        save_stream(source, target, max_bytes=1000)

    assert not target.exists(), "недописанный файл должен удаляться"


def test_save_stream_returns_size_and_hash(tmp_path):
    target = tmp_path / "doc.pdf"

    size, digest = save_stream(io.BytesIO(b"hello"), target)

    assert size == 5
    assert len(digest) == 64
    assert target.read_bytes() == b"hello"


# --- комплектность ---------------------------------------------------------


def test_checklist_counts_what_is_missing():
    checklist = build_checklist("claim", ["ddu"])

    assert checklist["ready"] is False
    assert checklist["missing_required"] == 3
    titles = {item["title"]: item["present"] for item in checklist["items"]}
    assert titles["Договор долевого участия"] is True
    assert titles["Паспорт"] is False


def test_checklist_is_ready_when_everything_required_is_there():
    checklist = build_checklist("claim", ["services_contract", "ddu", "payment", "passport"])

    assert checklist["ready"] is True
    assert checklist["missing_required"] == 0


def test_optional_documents_do_not_block():
    checklist = build_checklist("claim", ["services_contract", "ddu", "payment", "passport"])
    optional = [item for item in checklist["items"] if item["optional"]]

    assert optional, "необязательные пункты должны быть в списке"
    assert checklist["ready"] is True


def test_suit_stage_requires_more_than_claim_stage():
    for_claim = build_checklist("claim", [])
    for_suit = build_checklist("suit_filed", [])

    assert for_suit["required_total"] > for_claim["required_total"]


# --- загрузка через API ----------------------------------------------------

DDU_BYTES = DDU_TEXT.encode("utf-8")


@pytest.fixture
def case(api_client, staff):
    created = api_client.post(
        "/api/v1/cases",
        json={"client_name": "Петров Иван Иванович", "client_phone": "+7 900 111-22-33",
              "project": "ЖК Символ"},
        headers=staff["lawyer"],
    )
    assert created.status_code == 201, created.text
    return created.json()


def upload(api_client, staff, case, name="dogovor.txt", content=DDU_BYTES, **data):
    return api_client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": (name, io.BytesIO(content), "text/plain")},
        data=data,
        headers=staff["lawyer"],
    )


def test_uploaded_document_is_classified_and_renamed(api_client, staff, case):
    response = upload(api_client, staff, case)

    assert response.status_code == 201, response.text
    document = response.json()
    assert document["doc_type"] == "ddu"
    assert document["doc_type_title"] == "Договор долевого участия"
    assert document["folder"] == "01_Договор"
    assert document["stored_name"].startswith("Petrov_2026-")
    assert document["needs_review"] is False
    assert document["original_name"] == "dogovor.txt"


def test_requisites_are_offered_not_applied(api_client, staff, case):
    document = upload(api_client, staff, case).json()

    assert document["extracted"]["contract_number"] == "12/АБ-345"
    assert document["extracted_applied"] is False

    # В карточке дела пока пусто — система ничего не подставила молча.
    fresh = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    assert fresh["contract_number"] is None


def test_requisites_can_be_applied_on_request(api_client, staff, case):
    document = upload(api_client, staff, case).json()

    applied = api_client.post(
        f"/api/v1/documents/{document['id']}/apply", headers=staff["lawyer"]
    )

    assert applied.status_code == 200
    assert "contract_number" in applied.json()["applied"]

    fresh = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    assert fresh["contract_number"] == "12/АБ-345"
    assert fresh["contract_price"] == "8500000.00"
    assert fresh["due_date"] == "2021-12-30"


def test_applying_does_not_overwrite_what_a_lawyer_typed(api_client, staff, case):
    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_number": "проверено вручную"},
        headers=staff["lawyer"],
    )
    document = upload(api_client, staff, case).json()

    applied = api_client.post(
        f"/api/v1/documents/{document['id']}/apply", headers=staff["lawyer"]
    ).json()

    assert "contract_number" not in applied["applied"]
    fresh = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    assert fresh["contract_number"] == "проверено вручную"


def test_unclear_document_is_flagged_for_review(api_client, staff, case):
    document = upload(api_client, staff, case, name="IMG_1234.jpg", content=b"\xff\xd8\xff").json()

    assert document["doc_type"] == "other"
    assert document["needs_review"] is True

    listed = api_client.get(
        f"/api/v1/cases/{case['id']}/documents", headers=staff["lawyer"]
    ).json()
    assert listed["needs_review"] == 1


def test_explicit_type_wins_over_guessing(api_client, staff, case):
    document = upload(api_client, staff, case, name="скан.pdf", content=b"%PDF-1.4 ",
                      doc_type="passport").json()

    assert document["doc_type"] == "passport"
    assert document["folder"] == "08_Личные"
    assert document["detected_by"] == "manual"
    assert document["needs_review"] is False


def test_changing_type_moves_the_file(api_client, staff, case):
    document = upload(api_client, staff, case).json()
    assert document["folder"] == "01_Договор"

    updated = api_client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"doc_type": "claim"},
        headers=staff["lawyer"],
    ).json()

    assert updated["folder"] == "05_Претензия"
    assert updated["needs_review"] is False
    # Файл действительно доступен по новому месту.
    assert api_client.get(
        f"/api/v1/documents/{document['id']}/file", headers=staff["lawyer"]
    ).status_code == 200


def test_same_file_twice_is_refused(api_client, staff, case):
    upload(api_client, staff, case)

    again = upload(api_client, staff, case, name="копия.txt")

    assert again.status_code == 409
    assert "уже загружен" in again.json()["detail"]


def test_executable_upload_is_refused(api_client, staff, case):
    response = upload(api_client, staff, case, name="virus.exe", content=b"MZ\x90")

    assert response.status_code == 400
    assert ".exe" in response.json()["detail"]


def test_download_is_written_to_the_access_log(api_client, staff, case):
    document = upload(api_client, staff, case).json()

    downloaded = api_client.get(
        f"/api/v1/documents/{document['id']}/file", headers=staff["lawyer"]
    )
    assert downloaded.status_code == 200

    log = api_client.get(
        f"/api/v1/documents/{document['id']}/access-log", headers=staff["manager"]
    ).json()
    assert log["count"] == 1
    assert log["items"][0]["action"] == "download"
    assert log["items"][0]["user"] == "Юрист Ирина"


def test_deleting_removes_file_and_is_logged(api_client, staff, case):
    document = upload(api_client, staff, case).json()

    api_client.delete(f"/api/v1/documents/{document['id']}", headers=staff["lawyer"])

    assert api_client.get(
        f"/api/v1/documents/{document['id']}/file", headers=staff["lawyer"]
    ).status_code == 404
    feed = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    assert any("Удалён документ" in event["text"] for event in feed["events"])


def test_checklist_only_counts_confirmed_documents(api_client, staff, case):
    """Догадка «похоже на паспорт» не должна закрывать пункт комплектности."""
    upload(api_client, staff, case, name="паспорт.jpg", content=b"\xff\xd8\xff\xe0")

    listed = api_client.get(
        f"/api/v1/cases/{case['id']}/documents", headers=staff["lawyer"]
    ).json()
    passport = next(
        item for item in listed["checklist"]["items"] if item["doc_type"] == "passport"
    )
    assert passport["present"] is False


def test_upload_requires_login(api_client, staff, case):
    response = api_client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": ("doc.txt", io.BytesIO(b"test"), "text/plain")},
    )

    assert response.status_code == 401


def test_upload_to_unknown_case_returns_404(api_client, staff):
    response = api_client.post(
        "/api/v1/cases/нет-такого/documents",
        files={"file": ("doc.txt", io.BytesIO(b"test"), "text/plain")},
        headers=staff["lawyer"],
    )

    assert response.status_code == 404


# --- реестр в Excel --------------------------------------------------------


def test_registry_has_three_sheets_and_the_case_row(api_client, staff, case):
    import openpyxl

    upload(api_client, staff, case)
    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"amount_claimed": "2174725.00", "court_name": "Никулинский районный суд"},
        headers=staff["lawyer"],
    )

    response = api_client.get("/api/v1/cases.xlsx", headers=staff["manager"])

    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    book = openpyxl.load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Дела", "Документы", "Заседания"]

    sheet = book["Дела"]
    headers = [cell.value for cell in sheet[1]]
    assert "№ дела" in headers and "Гонорар" in headers

    row = {headers[index]: cell.value for index, cell in enumerate(sheet[2])}
    assert row["Клиент"] == "Петров Иван Иванович"
    assert row["Заявлено"] == 2174725.0
    assert row["Суд"] == "Никулинский районный суд"
    assert row["Документов"] == 1

    documents = book["Документы"]
    assert [cell.value for cell in documents[2]][2] == "Договор долевого участия"


def test_lawyer_registry_has_no_fee_column(api_client, staff, case):
    import openpyxl

    response = api_client.get("/api/v1/cases.xlsx", headers=staff["lawyer"])

    book = openpyxl.load_workbook(io.BytesIO(response.content))
    headers = [cell.value for cell in book["Дела"][1]]
    assert "Гонорар" not in headers
    assert "Заявлено" in headers


def test_registry_export_requires_login(api_client):
    assert api_client.get("/api/v1/cases.xlsx").status_code == 401


def test_incoming_dir_shares_a_filesystem_with_case_folders():
    """Временный файл обязан лежать там же, где папки дел.

    Иначе перенос готового файла в дело падает: os.replace не умеет
    переносить между файловыми системами, а в контейнере /tmp и том с
    данными — разные. Ровно так загрузка и ломалась на сервере.
    """
    from app.api.documents import _incoming_dir
    from app.db import DATA_DIR

    incoming = _incoming_dir()

    assert incoming.is_relative_to(Path(DATA_DIR))
    assert incoming.stat().st_dev == Path(DATA_DIR).stat().st_dev


def test_upload_leaves_no_temporary_files(api_client, staff, case):
    from app.api.documents import _incoming_dir

    upload(api_client, staff, case, name="дду.pdf", content=DDU_BYTES)

    assert list(_incoming_dir().iterdir()) == []


def test_lawsuit_is_not_mistaken_for_the_contract_it_quotes():
    """Иск цитирует ДДУ, но заголовок у него свой — по нему и определяем."""
    text = (
        "ИСКОВОЕ ЗАЯВЛЕНИЕ\n"
        "о взыскании неустойки по договору участия в долевом строительстве\n"
        "Между истцом и ответчиком заключен договор участия в долевом строительстве "
        "№ КЗН-1 от 10.09.2024. Застройщик обязуется передать объект. "
        "ПРОШУ СУД взыскать неустойку."
    )

    guess = classify("скан_001.pdf", text)

    assert guess.code == "lawsuit", guess.explanation


def test_claim_is_not_mistaken_for_the_contract_it_quotes():
    text = (
        "ПРЕТЕНЗИЯ\n"
        "По договору участия в долевом строительстве № КЗН-1 застройщик обязуется "
        "передать объект долевого строительства. Требую выплатить неустойку "
        "в добровольном порядке."
    )

    guess = classify("скан_002.pdf", text)

    assert guess.code == "claim", guess.explanation


def test_contract_still_wins_on_its_own_text():
    text = (
        "ДОГОВОР УЧАСТИЯ В ДОЛЕВОМ СТРОИТЕЛЬСТВЕ № КЗН-1\n"
        "Застройщик обязуется передать участнику долевого строительства объект."
    )

    guess = classify("скан_001.pdf", text)

    assert guess.code == "ddu", guess.explanation


def test_heading_is_found_below_the_city_and_date_line():
    """В сканах над названием часто стоят город и дата — заголовок ниже."""
    text = "г. Казань\n10.09.2024\nДОГОВОР УЧАСТИЯ В ДОЛЕВОМ СТРОИТЕЛЬСТВЕ № КЗН-1\nЗастройщик и участник."

    guess = classify("скан_003.pdf", text)

    assert guess.code == "ddu", guess.explanation
