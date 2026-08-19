"""Извлечение реквизитов из текста документа.

Всё, что здесь получается, — это ПРЕДЛОЖЕНИЕ для карточки дела, а не
готовые данные. Юрист подтверждает или правит; система ничего не
подставляет молча.

Из ДДУ вытаскивается всё, что потом переписывается в шапку иска: стороны
с их номерами и паспортом, объект с адресом и площадью, цена и сроки.
Каждое поле ищется по своему признаку в тексте рядом, а не «первое
похожее число в документе» — иначе дата рождения участника уезжает в дату
договора, а ИНН застройщика в ИНН клиента.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# 214-ФЗ действует с 1 апреля 2005 года: договора участия в долевом
# строительстве раньше этой даты не существует. Всё, что старше, — чужая
# дата в тексте (рождения, выдачи паспорта, регистрации застройщика).
EARLIEST_CONTRACT = date(2005, 4, 1)

NUMBER_RE = re.compile(
    r"(?:договор[а-я]*|дду)[^\n№]{0,60}№\s*([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/\.\(\)]{1,60})",
    re.IGNORECASE,
)
DOTTED_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
WORDED_DATE_RE = re.compile(
    r"[«\"]?(\d{1,2})[»\"]?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.IGNORECASE
)
# Дата договора стоит сразу за его номером: «№ КЗН-1 от 10.09.2024».
NUMBER_DATE_RE = re.compile(
    r"№\s*[A-Za-zА-Яа-я0-9][^\n]{0,60}?\s+от\s+([^,;\n]{6,40})", re.IGNORECASE
)

PRICE_RE = re.compile(
    r"(\d{1,3}(?:[  ]\d{3}){1,4}(?:[.,]\d{2})?)\s*(?:руб|₽|рублей)", re.IGNORECASE
)
# «8 238 699 (Восемь миллионов…) рублей 43 копейки» — копейки отдельным словом.
PRICE_KOPEKS_RE = re.compile(
    r"(\d{1,3}(?:[  ]\d{3}){1,4})\s*(?:\([^)]{0,200}\)\s*)?руб[а-я]*[^\d]{0,20}(\d{1,2})\s*коп",
    re.IGNORECASE,
)
PRICE_LABEL_RE = re.compile(r"цена\s+(?:договора|объекта|квартиры)", re.IGNORECASE)

FLAT_RE = re.compile(
    r"(?:квартир[а-я]{0,2}|помещени[а-я]{0,2})[\s\S]{0,40}?(?:№|условный номер)\s*([0-9]{1,4}[А-Яа-я]?)",
    re.IGNORECASE,
)
AREA_RE = re.compile(
    r"(?:общая|проектная|общая проектная)\s+площад[а-я]{1,3}[^\d]{0,30}(\d{1,3}[.,]\d{1,2})",
    re.IGNORECASE,
)
PROJECT_RE = re.compile(
    r"(?:жилой комплекс|жк)\s*[«\"']([^»\"'\n]{2,80})[»\"']", re.IGNORECASE
)
OBJECT_ADDRESS_RE = re.compile(
    r"(?:строительный адрес|почтовый адрес|расположенн[а-я]{2,3} по адресу|адрес объекта)"
    r"\s*[:—-]?\s*([^\n;]{10,200})",
    re.IGNORECASE,
)

# В хвосте нельзя запрещать точку: сама дата пишется через точки (30.12.2021).
TRANSFER_RE = re.compile(
    r"передать[^.]{0,200}?(?:не позднее|в срок до|до)\s+([^,;\n]{4,60})", re.IGNORECASE
)

# --- стороны ----------------------------------------------------------------

# Отчество — самый надёжный признак ФИО в сплошном тексте.
FIO_RE = re.compile(
    r"\b([А-ЯЁ][а-яё]{1,30})\s+([А-ЯЁ][а-яё]{1,20})\s+"
    r"([А-ЯЁ][а-яё]{1,20}(?:вич|вна|ична|инична|оглы|кызы))\b"
)
PARTICIPANT_RE = re.compile(
    r"участник[а-я]{0,3} долевого строительства|дольщик|гражданин[кае]{0,2}\s+(?:рф|российской)",
    re.IGNORECASE,
)
BIRTH_RE = re.compile(
    r"(?:дат[аы]\s+рождения|года рождения|рождени[яе])\s*[:—-]?\s*(\d{1,2}\.\d{1,2}\.\d{4})"
    r"|(\d{1,2}\.\d{1,2}\.\d{4})\s*(?:год[ае]?\s*)?рождения",
    re.IGNORECASE,
)
PASSPORT_RE = re.compile(
    r"паспорт[^\n]{0,40}?(\d{2}\s?\d{2})\s*(?:№|N)?\s*(\d{6})",
    re.IGNORECASE,
)
PASSPORT_ISSUED_RE = re.compile(r"выдан[а-я]{0,2}\s*[:—-]?\s*([^\n;]{5,160})", re.IGNORECASE)
SNILS_RE = re.compile(r"\b(\d{3}-\d{3}-\d{3}[\s-]\d{2})\b")
INN_PERSON_RE = re.compile(r"инн\s*[:№—-]?\s*(\d{12})\b", re.IGNORECASE)
INN_COMPANY_RE = re.compile(r"инн\s*[:№—-]?\s*(\d{10})\b", re.IGNORECASE)
OGRN_RE = re.compile(r"огрн[а-я]{0,2}\s*[:№—-]?\s*(\d{13,15})\b", re.IGNORECASE)
CLIENT_ADDRESS_RE = re.compile(
    r"(?:зарегистрирован[а-я]{0,3}|адрес регистрации|место жительства)"
    r"(?:\s*по адресу)?\s*[:—-]?\s*(.{10,200})",
    re.IGNORECASE,
)

# Адрес в договоре не заканчивается знаком препинания: за ним идёт оборот
# про сторону договора либо номер следующего пункта. Обрывать по точке
# нельзя — точки стоят внутри самого адреса: «г. Казань, ул. Халитова, д. 8».
ADDRESS_TAIL_RE = re.compile(
    r"\s*(?:именуем|далее|с другой стороны|с одной стороны|,\s*действующ|\d+\.\d|$)",
    re.IGNORECASE,
)
COMPANY_RE = re.compile(
    r"\b(ООО|АО|ПАО|ЗАО|ОАО|ООО\s*«|Общество с ограниченной ответственностью)\s*"
    r"[«\"']([^»\"'\n]{2,120})[»\"']",
    re.IGNORECASE,
)


@dataclass
class Requisites:
    """Реквизиты дела. Поля клиента и застройщика вынесены префиксами —
    в карточке они живут в своих таблицах."""

    contract_number: Optional[str] = None
    contract_date: Optional[date] = None
    contract_price: Optional[Decimal] = None
    apartment: Optional[str] = None
    due_date: Optional[date] = None
    project: Optional[str] = None
    object_address: Optional[str] = None
    area: Optional[Decimal] = None

    client_name: Optional[str] = None
    client_birth_date: Optional[date] = None
    client_passport: Optional[str] = None
    client_snils: Optional[str] = None
    client_inn: Optional[str] = None
    client_address: Optional[str] = None

    developer_name: Optional[str] = None
    developer_inn: Optional[str] = None
    developer_ogrn: Optional[str] = None

    def as_dict(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for name, value in vars(self).items():
            if value is None or value == "":
                continue
            result[name] = value.isoformat() if isinstance(value, date) else str(value)
        return result

    @property
    def is_empty(self) -> bool:
        return not self.as_dict()


def parse_date(text: str) -> Optional[date]:
    """Дата в формате 12.05.2021 или «12» мая 2021 года."""
    match = DOTTED_DATE_RE.search(text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = WORDED_DATE_RE.search(text)
    if match:
        day, month_name, year = match.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                return None
    return None


def parse_price(text: str) -> Optional[Decimal]:
    """Цена договора.

    Ищется сначала возле слов «цена договора»: в тексте полно других сумм —
    неустойка, госпошлина, стоимость метра.
    """
    label = PRICE_LABEL_RE.search(text)
    window = text[label.start(): label.start() + 400] if label else text

    for source in (window, text):
        kopeks = PRICE_KOPEKS_RE.search(source)
        if kopeks:
            rubles = _digits(kopeks.group(1))
            try:
                return Decimal(f"{rubles}.{int(kopeks.group(2)):02d}")
            except InvalidOperation:
                pass

        plain = PRICE_RE.search(source)
        if plain:
            try:
                return Decimal(_digits(plain.group(1)).replace(",", "."))
            except InvalidOperation:
                pass
    return None


def _digits(raw: str) -> str:
    return raw.replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")


def _clean(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .,;:—-")
    return cleaned or None


def _address(value: Optional[str]) -> Optional[str]:
    """Адрес до оборота, который за ним следует.

    В договоре адрес не заканчивается знаком: сразу за ним идёт «именуемая
    в дальнейшем» или «с другой стороны», и без обрезки они попадают
    в карточку вместе с улицей.
    """
    cleaned = _clean(value)
    if not cleaned:
        return None
    tail = ADDRESS_TAIL_RE.search(cleaned)
    if tail and tail.start() > 0:
        cleaned = cleaned[: tail.start()]
    return _clean(cleaned)


def _contract_date(text: str) -> Optional[date]:
    """Дата договора, а не первая дата в документе.

    Сначала — дата сразу за номером договора, там она и стоит. Если такой
    нет, берётся первая дата из шапки, которая вообще может быть датой ДДУ:
    паспорт участника выдан в 1997 году, и без этой проверки в карточку
    уезжал именно он.
    """
    near_number = NUMBER_DATE_RE.search(text)
    if near_number:
        parsed = parse_date(near_number.group(1))
        if parsed and parsed >= EARLIEST_CONTRACT:
            return parsed

    for match in DOTTED_DATE_RE.finditer(text[:3000]):
        try:
            parsed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            continue
        if parsed >= EARLIEST_CONTRACT:
            return parsed

    worded = parse_date(text[:3000])
    return worded if worded and worded >= EARLIEST_CONTRACT else None


def _client_name(text: str) -> Optional[str]:
    """ФИО участника долевого строительства.

    Берётся ФИО, ближайшее к упоминанию участника: в договоре есть и
    подписант со стороны застройщика, и он обычно идёт первым.
    """
    names = list(FIO_RE.finditer(text))
    if not names:
        return None

    anchor = PARTICIPANT_RE.search(text)
    if anchor:
        after = [match for match in names if match.start() >= anchor.start()]
        if after:
            return " ".join(after[0].groups())

    return " ".join(names[0].groups())


def _passport(text: str) -> Optional[str]:
    match = PASSPORT_RE.search(text)
    if not match:
        return None

    series = re.sub(r"\s+", " ", match.group(1))
    value = f"{series} № {match.group(2)}"

    issued = PASSPORT_ISSUED_RE.search(text, match.end(), match.end() + 200)
    if issued:
        value += ", выдан " + _address(issued.group(1))
    return value


def _developer_name(text: str) -> Optional[str]:
    """Наименование застройщика.

    Ищется от слова «застройщик»: в договоре названы и банк, и подрядчик,
    и они тоже записаны как ООО «…».
    """
    anchor = re.search(r"застройщик", text, re.IGNORECASE)
    window = text[anchor.start():] if anchor else text
    for source in (window, text):
        match = COMPANY_RE.search(source)
        if match:
            form = match.group(1).strip().rstrip("«").strip()
            if form.lower().startswith("общество"):
                form = "ООО"
            return f"{form.upper()} «{_clean(match.group(2))}»"
    return None


def extract(text: str, doc_type: str = "") -> Requisites:
    """Реквизиты из текста. Пустые поля — норма, а не ошибка."""
    if not text:
        return Requisites()

    result = Requisites()

    number = NUMBER_RE.search(text)
    if number:
        result.contract_number = number.group(1).strip(" .,;")

    result.contract_date = _contract_date(text)
    result.contract_price = parse_price(text)

    flat = FLAT_RE.search(text)
    if flat:
        result.apartment = flat.group(1)

    area = AREA_RE.search(text)
    if area:
        try:
            result.area = Decimal(area.group(1).replace(",", "."))
        except InvalidOperation:
            result.area = None

    project = PROJECT_RE.search(text)
    if project:
        result.project = _clean(project.group(1))

    flat_text = re.sub(r"\s+", " ", text)

    address = OBJECT_ADDRESS_RE.search(flat_text)
    if address:
        result.object_address = _address(address.group(1))

    transfer = TRANSFER_RE.search(text)
    if transfer:
        result.due_date = parse_date(transfer.group(1))

    result.client_name = _client_name(text)

    birth = BIRTH_RE.search(text)
    if birth:
        result.client_birth_date = parse_date(birth.group(1) or birth.group(2) or "")

    result.client_passport = _passport(text)

    snils = SNILS_RE.search(text)
    if snils:
        result.client_snils = snils.group(1).replace("-", "-").strip()

    person_inn = INN_PERSON_RE.search(text)
    if person_inn:
        result.client_inn = person_inn.group(1)

    client_address = CLIENT_ADDRESS_RE.search(flat_text)
    if client_address:
        result.client_address = _address(client_address.group(1))

    result.developer_name = _developer_name(text)

    # ИНН юридического лица — десять цифр, физического — двенадцать.
    # Разделять их по длине надёжнее, чем по расстоянию до слова в тексте.
    company_inn = INN_COMPANY_RE.search(text)
    if company_inn:
        result.developer_inn = company_inn.group(1)

    ogrn = OGRN_RE.search(text)
    if ogrn:
        result.developer_ogrn = ogrn.group(1)

    # Для не-договоров реквизиты договора не предлагаем: в претензии или
    # решении суда те же числа значат совсем другое.
    if doc_type not in ("ddu", "ddu_amendment", "assignment", ""):
        result.contract_price = None
        result.due_date = None

    return result
