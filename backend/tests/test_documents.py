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


# --- реквизиты из ДДУ -------------------------------------------------------

FULL_DDU = """ДОГОВОР УЧАСТИЯ В ДОЛЕВОМ СТРОИТЕЛЬСТВЕ № КЗН-1(кв)-3/16 от 10.09.2024
г. Казань
Общество с ограниченной ответственностью «МТ-ДЕВЕЛОПМЕНТ», ОГРН 1141690077725,
ИНН 1655310204, именуемое в дальнейшем «Застройщик», в лице директора
Сидорова Петра Ивановича, с одной стороны, и
гражданка РФ Седина Анна Владимировна, дата рождения 17.05.1997,
паспорт 92 15 № 456789, выдан ОУФМС России по Республике Татарстан 20.06.2017,
СНИЛС 123-456-789 00, ИНН 165512345678, зарегистрирована по адресу:
г. Казань, ул. Халитова, д. 8, кв. 12, именуемая в дальнейшем
«Участник долевого строительства», с другой стороны, заключили договор.
1.1. Застройщик обязуется построить жилой комплекс «Статный» и передать
Участнику долевого строительства объект долевого строительства — квартиру
№ 353, общая проектная площадь 41,20 кв.м, расположенную по адресу:
420088, Республика Татарстан, г. Казань, улица Халитова, д. 8.
2.1. Цена договора составляет 8 238 699 (Восемь миллионов) рублей 43 копейки.
3.1. Застройщик обязуется передать объект долевого строительства
не позднее 31.10.2025.
"""


def test_contract_requisites_are_read_in_full():
    data = extract_requisites(FULL_DDU, "ddu").as_dict()

    assert data["contract_number"] == "КЗН-1(кв)-3/16"
    assert data["contract_date"] == "2024-09-10"
    assert data["contract_price"] == "8238699.43"
    assert data["due_date"] == "2025-10-31"
    assert data["apartment"] == "353"
    assert data["area"] == "41.20"
    assert data["project"] == "Статный"
    assert data["object_address"].startswith("420088")


def test_party_requisites_are_read_and_not_mixed_up():
    data = extract_requisites(FULL_DDU, "ddu").as_dict()

    assert data["client_name"] == "Седина Анна Владимировна"
    assert data["client_birth_date"] == "1997-05-17"
    assert data["client_snils"] == "123-456-789 00"
    assert data["client_passport"].startswith("92 15 № 456789")
    assert "выдан" in data["client_passport"]
    assert data["client_address"] == "г. Казань, ул. Халитова, д. 8, кв. 12"
    # ИНН физлица — двенадцать цифр, юрлица — десять; по длине их и делим.
    assert data["client_inn"] == "165512345678"
    assert data["developer_inn"] == "1655310204"
    assert data["developer_ogrn"] == "1141690077725"
    assert data["developer_name"] == "ООО «МТ-ДЕВЕЛОПМЕНТ»"


def test_birth_date_does_not_become_the_contract_date():
    """Паспорт участника выдан в 1997 году — датой ДДУ это быть не может."""
    data = extract_requisites(FULL_DDU, "ddu").as_dict()

    assert data["contract_date"] != "1997-05-17"


def test_applying_fills_the_client_and_the_developer(api_client, staff, case):
    """Данные сторон живут в своих таблицах — перенос должен доходить и туда."""
    document = upload(api_client, staff, case, name="дду.txt",
                      content=FULL_DDU.encode("utf-8")).json()

    api_client.post(f"/api/v1/documents/{document['id']}/apply", headers=staff["lawyer"])

    fresh = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    assert fresh["client_snils"] == "123-456-789 00"
    assert fresh["client_inn"] == "165512345678"
    assert fresh["client_birth_date"] == "1997-05-17"
    assert fresh["developer_inn"] == "1655310204"
    assert fresh["developer_ogrn"] == "1141690077725"
    assert fresh["object_address"].startswith("420088")


# Второй договор — в той форме, в какой их печатают застройщики: стороны
# разделены оборотом «именуемое в дальнейшем», реквизиты идут подряд, цена
# записана прописью, срок переносится на следующую строку. Данные вымышлены.
DEVELOPER_STYLE_DDU = """Договор участия в долевом строительстве № ОСТ-5/17/54-901369401И

Москва "24" мая 2025 г.

Общество с ограниченной ответственностью "СПЕЦИАЛИЗИРОВАННЫЙ ЗАСТРОЙЩИК "СР-
ГРУПП", ОГРН 1167746567053, ИНН/КПП 7731319243/775101001, адрес: 108852, г. Москва,
именуемое в дальнейшем «Застройщик», в лице Петрова Ильи Сергеевича, действующего
на основании доверенности № B3AC9CF2 от 01.08.2024, удостоверенной Павловым
Анатолием Анатольевичем, нотариусом города Москвы, зарегистрированной в реестре
за № 50/976-н/77-2024-8-702, с одной стороны, и
Гражданин РФ Иванова Мария Петровна, пол: Женский, 26.07.1979 года рождения,
паспорт: серия 4524 № 366479, выдан: ГУ МВД РОССИИ ПО Г. МОСКВЕ, Дата выдачи:
22.08.2024, код подразделения: 770-125, зарегистрирован по адресу: 108813, г Москва,
ул Радужная, д 11, кв 254, СНИЛС:04194546359, именуемый в дальнейшем «Участник
долевого строительства» с другой стороны, заключили договор.
Расчёты ведутся на счете эскроу в АО «АЛЬФА-БАНК», ИНН 7728168971.
Объект – город Москва, поселение Рязановское, с. Остафьево, участок 19.
2.5. Стороны согласовали, что срок передачи Застройщиком Объекта долевого
строительства Участнику долевого строительства до
30.12.2025 года
3.1. Цена Договора составляет сумму в размере 15 613 672,30 (Пятнадцать миллионов
шестьсот тринадцать тысяч шестьсот семьдесят два) рубля 30 копеек.
"""


def test_dates_of_the_notary_and_the_passport_are_not_the_contract_date():
    """В шапке дата договора, ниже — доверенности и паспорта. Нужна первая."""
    data = extract_requisites(DEVELOPER_STYLE_DDU, "ddu").as_dict()

    assert data["contract_date"] == "2025-05-24"
    assert data["due_date"] == "2025-12-30"
    assert data["contract_price"] == "15613672.30"


def test_the_developer_address_is_taken_from_the_preamble():
    """Адрес ответчика — обязательный реквизит иска, и он есть в договоре."""
    data = extract_requisites(DEVELOPER_STYLE_DDU, "ddu").as_dict()

    assert data["developer_address"] == "108852, г. Москва"


def test_escrow_bank_is_not_taken_for_the_developer():
    """В договоре названы и банк, и нотариус — застройщик тот, чья это роль."""
    data = extract_requisites(DEVELOPER_STYLE_DDU, "ddu").as_dict()

    assert "СР-" in data["developer_name"], data["developer_name"]
    assert data["developer_inn"] == "7731319243"  # не 7728168971 — это банк
    assert data["developer_ogrn"] == "1167746567053"


def test_registered_in_the_registry_is_not_a_home_address():
    """«зарегистрированной в реестре» — про нотариуса, а не про дольщика."""
    data = extract_requisites(DEVELOPER_STYLE_DDU, "ddu").as_dict()

    assert data["client_address"].startswith("108813")
    assert data["client_snils"] == "041-945-463 59"  # в тексте одиннадцать цифр подряд
    assert data["client_name"] == "Иванова Мария Петровна"


def test_claim_states_the_contract_date_in_its_own_way():
    """В претензии шапка занята сторонами, а дата стоит перед словом «между»."""
    text = (
        "ПРЕТЕНЗИЯ\nо выплате неустойки\n"
        "24 мая 2025 года между ООО «СЗ «СР-ГРУПП» и мной был заключен Договор "
        "участия в долевом строительстве № ОСТ-5/17/54-901369401И, "
        "проектный номер: 54, общая приведенная площадь: 74,43 кв. м."
    )

    data = extract_requisites(text, "claim").as_dict()

    assert data["contract_date"] == "2025-05-24"
    assert data["apartment"] == "54"
    assert data["area"] == "74.43"


def test_developer_name_survives_a_line_break_inside_the_quotes():
    """PDF рвёт длинное наименование по строкам — склеиваем обратно."""
    data = extract_requisites(DEVELOPER_STYLE_DDU, "ddu").as_dict()

    assert data["developer_name"] == 'ООО «СПЕЦИАЛИЗИРОВАННЫЙ ЗАСТРОЙЩИК «СР-ГРУПП»»'


def test_registry_does_not_hand_excel_a_formula_from_the_lead_form(api_client, staff):
    """Имя в заявке пишет посетитель сайта, а реестр открывает юрист.

    Строка, начинающаяся со знака равенства, для Excel не текст, а формула,
    и выполняется она при открытии файла.
    """
    from openpyxl import load_workbook

    api_client.post(
        "/api/v1/cases",
        json={"client_name": '=HYPERLINK("http://example.invalid","отчёт")',
              "client_phone": "+79000000003"},
        headers=staff["manager"],
    )

    response = api_client.get("/api/v1/cases.xlsx", headers=staff["manager"])
    sheet = load_workbook(io.BytesIO(response.content))["Дела"]
    values = [cell.value for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str)]

    assert not any(value.startswith("=") for value in values), "формула ушла в файл как формула"
    assert any(value.startswith("'=HYPERLINK") for value in values), "значение потерялось"


# --- сборка документов по шаблонам -----------------------------------------


def test_case_calculation_is_linked_and_fills_the_claimed_amount(api_client, staff, case):
    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_price": "8500000", "due_date": "2025-10-31"},
        headers=staff["lawyer"],
    )

    response = api_client.post(f"/api/v1/cases/{case['id']}/calculate", headers=staff["lawyer"])

    assert response.status_code == 200, response.text
    fresh = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    assert fresh["amount_claimed"] == response.json()["result"]["total"]


def test_recalculation_also_fills_the_state_duty(api_client, staff, case):
    """Пошлину не должен считать человек: она однозначно следует из цены иска."""
    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_price": "8500000", "due_date": "2020-10-31"},
        headers=staff["lawyer"],
    )

    body = api_client.post(
        f"/api/v1/cases/{case['id']}/calculate", headers=staff["lawyer"]
    ).json()

    duty = body["result"]["duty"]
    fresh = api_client.get(f"/api/v1/cases/{case['id']}", headers=staff["lawyer"]).json()
    # В карточке сумма хранится с копейками, в расчёте — в полных рублях,
    # как её и исчисляет закон. Сравниваем числа, а не их запись.
    assert Decimal(fresh["duty"]) == Decimal(duty["amount"]) > 0
    # Основание всегда попадает в ленту: юрист должен видеть, откуда сумма.
    assert any("Госпошлина" in event["text"] for event in fresh["events"])


def test_a_small_claim_leaves_the_duty_at_zero_and_says_why(api_client, staff, case):
    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_price": "1000000", "due_date": "2025-10-31"},
        headers=staff["lawyer"],
    )

    duty = api_client.post(
        f"/api/v1/cases/{case['id']}/calculate", headers=staff["lawyer"]
    ).json()["result"]["duty"]

    assert duty["exempt"] is True
    assert duty["amount"] == "0"


def test_the_lawsuit_header_states_the_exemption_instead_of_zero(api_client, staff, case):
    """«Госпошлина: 0 руб.» читается как незаполненное поле, а не как льгота."""
    from docx import Document as DocxDocument

    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_price": "1000000", "due_date": "2025-10-31"},
        headers=staff["lawyer"],
    )
    api_client.post(f"/api/v1/cases/{case['id']}/calculate", headers=staff["lawyer"])
    created = api_client.post(
        f"/api/v1/cases/{case['id']}/generate",
        data={"template": "lawsuit_delay"}, headers=staff["lawyer"],
    ).json()

    downloaded = api_client.get(
        f"/api/v1/documents/{created['id']}/file", headers=staff["lawyer"]
    )
    text = "\n".join(p.text for p in DocxDocument(io.BytesIO(downloaded.content)).paragraphs)

    assert "истец освобождён от уплаты" in text
    assert "Госпошлина: 0" not in text
    assert "duty" not in created["missing"]


def test_generated_claim_lands_in_the_case_as_a_document(api_client, staff, case):
    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_price": "8500000", "due_date": "2025-10-31",
              "contract_number": "ОСТ-1", "contract_date": "2024-05-24"},
        headers=staff["lawyer"],
    )
    api_client.post(f"/api/v1/cases/{case['id']}/calculate", headers=staff["lawyer"])

    response = api_client.post(
        f"/api/v1/cases/{case['id']}/generate",
        data={"template": "claim_delay"},
        headers=staff["lawyer"],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["doc_type"] == "claim"
    assert body["stored_name"].endswith(".docx")

    listed = api_client.get(f"/api/v1/cases/{case['id']}/documents", headers=staff["lawyer"]).json()
    assert any(item["id"] == body["id"] for item in listed["items"])


def test_missing_fields_are_named_and_left_visible(api_client, staff, case):
    """Пустое место в готовом иске заметить труднее, чем подчёркивания."""
    response = api_client.post(
        f"/api/v1/cases/{case['id']}/generate",
        data={"template": "lawsuit_delay"},
        headers=staff["lawyer"],
    )

    assert response.status_code == 201, response.text
    assert "court_name" in response.json()["missing"]
    assert "contract_number" in response.json()["missing"]


def test_generated_document_carries_the_real_numbers(api_client, staff, case):
    from docx import Document as DocxDocument

    api_client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"contract_price": "8500000", "due_date": "2025-10-31", "contract_number": "ОСТ-1"},
        headers=staff["lawyer"],
    )
    api_client.post(f"/api/v1/cases/{case['id']}/calculate", headers=staff["lawyer"])
    created = api_client.post(
        f"/api/v1/cases/{case['id']}/generate",
        data={"template": "claim_delay"}, headers=staff["lawyer"],
    ).json()

    downloaded = api_client.get(
        f"/api/v1/documents/{created['id']}/file", headers=staff["lawyer"]
    )
    text = "\n".join(p.text for p in DocxDocument(io.BytesIO(downloaded.content)).paragraphs)

    assert "ОСТ-1" in text
    assert "8 500 000,00" in text
    assert "Восемь миллионов пятьсот тысяч рублей" in text


def test_templates_can_name_the_practice_itself(api_client, staff, case):
    """Реквизиты исполнителя нужны договору услуг и подписи представителя."""
    from app.generation import firm_values

    values = firm_values()

    assert values["firm_inn"] == "120101147767"
    assert "Фучика" in values["firm_address"]
    assert values["firm_legal_name"].startswith("Рузайкина")


def test_apply_is_not_offered_when_the_card_is_already_full(api_client, staff, case):
    """Кнопка, которая отвечает отказом, выглядит поломкой, а не отказом."""
    document = upload(api_client, staff, case).json()
    assert document["pending"], "сразу после загрузки переносить есть что"

    api_client.post(f"/api/v1/documents/{document['id']}/apply", headers=staff["lawyer"])
    second = upload(api_client, staff, case, name="дду-копия.txt", content=DDU_BYTES + b" ").json()

    assert second["extracted"], "реквизиты в документе нашлись"
    assert second["pending"] == [], "но в карточке они уже есть — переносить нечего"


# --- обучение на исправлениях ----------------------------------------------


def test_a_correction_teaches_the_system_the_practice_wording(api_client, staff, case):
    """Юрист поправил тип — такой же файл в следующий раз определится сам."""
    first = upload(api_client, staff, case, name="ои_претензия_иванов.pdf",
                   content=b"%PDF-1.4 no text").json()

    api_client.patch(
        f"/api/v1/documents/{first['id']}",
        json={"doc_type": "claim_tracking"},
        headers=staff["lawyer"],
    )

    second = upload(api_client, staff, case, name="ои_претензия_петров.pdf",
                    content=b"%PDF-1.4 other file").json()

    assert second["doc_type"] == "claim_tracking", second["signals"]


def test_hashes_and_service_words_are_not_remembered():
    """Случайное имя второй раз не встретится, «скан» встретится у всех."""
    from app.doctype_memory import words

    assert words("ddu-h6xj8aap1rmerfli_365bff277f47b38a0e252b173b16d2fc.pdf") == []
    assert "скан" not in words("Скан_претензия.pdf")
    assert "претензия" in words("Скан_претензия.pdf")


def test_memory_does_not_argue_with_a_confident_rule_after_one_correction(api_client, staff, case):
    """Одного исправления мало, чтобы спорить с заголовком документа."""
    odd = upload(api_client, staff, case, name="важное_письмо.pdf",
                 content=b"%PDF-1.4 nothing").json()
    api_client.patch(f"/api/v1/documents/{odd['id']}",
                     json={"doc_type": "writ"}, headers=staff["lawyer"])

    contract = upload(
        api_client, staff, case, name="важное_письмо_2.txt",
        content="ДОГОВОР УЧАСТИЯ В ДОЛЕВОМ СТРОИТЕЛЬСТВЕ № 1\nЗастройщик обязуется передать.".encode(),
    ).json()

    assert contract["doc_type"] == "ddu", contract["signals"]


def test_the_same_word_corrected_twice_outweighs_the_rules(api_client, staff, case):
    """Дважды исправленное слово — уже не случайность, а привычка практики."""
    for index in (1, 2):
        odd = upload(api_client, staff, case, name=f"почтовик_{index}.pdf",
                     content=f"%PDF-1.4 file {index}".encode()).json()
        api_client.patch(f"/api/v1/documents/{odd['id']}",
                         json={"doc_type": "lawsuit_tracking"}, headers=staff["lawyer"])

    contract = upload(
        api_client, staff, case, name="почтовик_3.txt",
        content="ДОГОВОР УЧАСТИЯ В ДОЛЕВОМ СТРОИТЕЛЬСТВЕ № 7\nЗастройщик обязуется передать.".encode(),
    ).json()

    assert contract["doc_type"] == "lawsuit_tracking", contract["signals"]
