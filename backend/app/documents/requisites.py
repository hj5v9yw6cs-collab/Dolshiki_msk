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
# «24 мая 2025 года между ООО … был заключен Договор» — так дату договора
# называют претензия и иск, где шапка занята реквизитами сторон.
CONCLUDED_RE = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\s+[а-я]{3,8}\s+\d{4})\s*(?:года|г\.)?\s+между",
    re.IGNORECASE,
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
PRICE_LABEL_RE = re.compile(
    r"цена\s+(?:договора|объекта|квартиры)", re.IGNORECASE
)
# «составляет сумму в размере 15 613 672,30 (Пятнадцать миллионов…) рубля 30
# копеек» — рубли стоят не сразу за числом, а после расшифровки прописью.
PRICE_AFTER_LABEL_RE = re.compile(
    r"(?:составляет|в размере)[^\d]{0,40}(\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)

# Номер квартиры берётся только там, где он назван прямо. В договоре полно
# других номеров рядом со словом «квартира» — дома, приложения, секции, — и
# любой из них попадал в карточку вместо квартиры.
FLAT_RE = re.compile(
    r"(?:номер квартиры|квартира|квартиру|квартиры)\s*(?:№|N)\s*([0-9]{1,4}[А-Яа-я]?)",
    re.IGNORECASE,
)
AREA_RE = re.compile(
    r"(?:обща[яй]\s+приведенн[ая][яй]?|общая|проектная)\s+площад[а-я]{1,3}"
    r"[^\d]{0,30}(\d{1,3}[.,]\d{1,2})",
    re.IGNORECASE,
)
# В новостройках квартира до сдачи живёт под проектным номером.
DESIGN_NUMBER_RE = re.compile(r"проектн[а-я]{2,3}\s+номер\s*[:№—-]?\s*(\d{1,4})", re.IGNORECASE)
PROJECT_RE = re.compile(
    r"(?:жилой комплекс|жк)\s*[«\"']([^»\"'\n]{2,80})[»\"']", re.IGNORECASE
)
# Адрес дома, а не земельного участка: участок в договоре тоже «расположен
# по адресу», и его описание идёт первым. Поэтому строительный адрес ищется
# по своим словам, а общая формулировка оставлена последней.
OBJECT_ADDRESS_RES = (
    re.compile(r"строительн[а-я]{2,3}\s+адрес[а-я]?\s*[:—-]?\s*(.{10,200})", re.IGNORECASE),
    re.compile(r"\bОбъект\s*[–—-]\s*((?:город|г\.|пос|респ|обл)[^\n]{10,200})", re.IGNORECASE),
    re.compile(r"почтовый адрес\s*[:—-]?\s*(.{10,200})", re.IGNORECASE),
    re.compile(r"расположенн[а-я]{2,3}\s+по адресу\s*[:—-]?\s*(.{10,200})", re.IGNORECASE),
)

# В хвосте нельзя запрещать точку: сама дата пишется через точки (30.12.2021).
# Срок формулируют по-разному: «обязуется передать … не позднее», «срок
# передачи … до». Дата при этом нередко переносится на следующую строку,
# поэтому перевод строки здесь разрешён.
TRANSFER_RES = (
    re.compile(r"срок\s+передачи[\s\S]{0,300}?(?:не позднее|в срок до|\bдо\b)\s*([\s\S]{4,40})",
               re.IGNORECASE),
    re.compile(r"обязуется передать[\s\S]{0,300}?(?:не позднее|в срок до|\bдо\b)\s*([\s\S]{4,40})",
               re.IGNORECASE),
    re.compile(r"передать[^.]{0,200}?(?:не позднее|в срок до|до)\s+([^,;\n]{4,60})",
               re.IGNORECASE),
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
# СНИЛС пишут и с разделителями, и одиннадцатью цифрами подряд.
SNILS_RE = re.compile(r"\b(\d{3}-\d{3}-\d{3}[\s-]\d{2})\b")
SNILS_PLAIN_RE = re.compile(r"снилс\s*[:№—-]?\s*(\d{11})\b", re.IGNORECASE)
INN_PERSON_RE = re.compile(r"инн\s*[:№—-]?\s*(\d{12})\b", re.IGNORECASE)
BARE_INN_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
# «ИНН/КПП 7731319243/775101001» — одной строкой, как в выписке.
INN_COMPANY_RE = re.compile(r"инн(?:\s*/\s*кпп)?\s*[:№—-]?\s*(\d{10})\b", re.IGNORECASE)
OGRN_RE = re.compile(r"огрн[а-я]{0,2}\s*[:№—-]?\s*(\d{13,15})\b", re.IGNORECASE)
# «зарегистрированной в реестре за №…» — про нотариуса, а не про человека,
# поэтому «по адресу» обязательно.
CLIENT_ADDRESS_RE = re.compile(
    r"(?:зарегистрирован[а-я]{0,3}\s+по адресу|адрес регистрации|место жительства)"
    r"\s*[:—-]?\s*(.{10,200})",
    re.IGNORECASE,
)

# Адрес в договоре не заканчивается знаком препинания: за ним идёт оборот
# про сторону договора либо номер следующего пункта. Обрывать по точке
# нельзя — точки стоят внутри самого адреса: «г. Казань, ул. Халитова, д. 8».
ADDRESS_TAIL_RE = re.compile(
    r"\s*(?:именуем|далее|с другой стороны|с одной стороны|,\s*действующ"
    r"|,?\s*снилс|,?\s*инн\b|,?\s*телефон|,?\s*дата выдачи|,?\s*код подразделения"
    r"|,?\s*категория земель|,?\s*\d{11,}|\d+\.\d|$)",
    re.IGNORECASE,
)
# Название бывает с вложенными кавычками: ООО "Специализированный застройщик
# "СР-ГРУПП"". Закрывающей считается та кавычка, за которой идёт запятая,
# реквизиты или конец строки, — иначе имя обрывается на первой внутренней.
COMPANY_RE = re.compile(
    r"\b(ООО|АО|ПАО|ЗАО|ОАО|Общество с ограниченной ответственностью)\s*"
    r"[«\"‹]{1,2}([\s\S]{2,140}?)[»\"›]{1,2}(?=\s*[,)]|\s+ОГРН|\s+ИНН|\s*$)",
    re.IGNORECASE,
)

# Роль стороны объявляется оборотом «именуемое в дальнейшем «Застройщик»».
# Он делит преамбулу на два блока, и это единственный надёжный способ не
# перепутать реквизиты застройщика, банка эскроу и самого дольщика.
ROLE_DEVELOPER_RE = re.compile(
    r"именуем[а-я]{0,3}\s+в\s+дальнейшем\s*[«\"‹]{1,2}\s*застройщик", re.IGNORECASE
)
ROLE_PARTICIPANT_RE = re.compile(
    r"именуем[а-я]{0,3}\s+в\s+дальнейшем\s*[«\"‹]{1,2}\s*участник", re.IGNORECASE
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

    Ищется возле слов «цена договора»: в тексте полно других сумм — неустойка,
    госпошлина, стоимость метра, цена иска. Без этой привязки в карточку
    попадает первая попавшаяся.
    """
    label = PRICE_LABEL_RE.search(text)
    window = text[label.start(): label.start() + 400] if label else ""

    if window:
        # Сначала форма с копейками словом: в ней есть и рубли, и копейки,
        # а без неё число обрывается на рублях.
        kopeks = PRICE_KOPEKS_RE.search(window)
        if kopeks:
            try:
                return Decimal(f"{_digits(kopeks.group(1))}.{int(kopeks.group(2)):02d}")
            except InvalidOperation:
                pass

        after = PRICE_AFTER_LABEL_RE.search(window)
        if after:
            value = _to_decimal(after.group(1))
            if value is not None:
                return value

    for source in (window, text):
        if not source:
            continue
        kopeks = PRICE_KOPEKS_RE.search(source)
        if kopeks:
            rubles = _digits(kopeks.group(1))
            try:
                return Decimal(f"{rubles}.{int(kopeks.group(2)):02d}")
            except InvalidOperation:
                pass

        plain = PRICE_RE.search(source)
        if plain:
            value = _to_decimal(plain.group(1))
            if value is not None:
                return value
    return None


def _to_decimal(raw: str) -> Optional[Decimal]:
    try:
        return Decimal(_digits(raw))
    except InvalidOperation:
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

    Дата стоит в шапке рядом с городом, до всяких реквизитов, поэтому она
    берётся из начала текста. Дальше по документу дат много и все чужие:
    рождение участника, выдача паспорта, доверенность представителя,
    регистрация права на участок — именно они и попадали в карточку.
    Всё, что старше 214-ФЗ, отбрасывается: договора участия в долевом
    строительстве до этой даты не существует.
    """
    concluded = CONCLUDED_RE.search(text)
    if concluded:
        parsed = parse_date(concluded.group(1))
        if parsed and parsed >= EARLIEST_CONTRACT:
            return parsed

    head = text[:1200]
    candidates = []

    for match in DOTTED_DATE_RE.finditer(head):
        try:
            candidates.append((match.start(), date(int(match.group(3)), int(match.group(2)),
                                                   int(match.group(1)))))
        except ValueError:
            continue

    for match in WORDED_DATE_RE.finditer(head):
        month = MONTHS.get(match.group(2).lower())
        if not month:
            continue
        try:
            candidates.append((match.start(), date(int(match.group(3)), month, int(match.group(1)))))
        except ValueError:
            continue

    # Шапка «Москва «24» мая 2025 г.» стоит выше реквизитов, а дата
    # доверенности представителя — ниже. Берём ту, что встретилась раньше,
    # независимо от того, цифрами она написана или прописью.
    for _, parsed in sorted(candidates):
        if parsed >= EARLIEST_CONTRACT:
            return parsed

    near_number = NUMBER_DATE_RE.search(text)
    if near_number:
        parsed = parse_date(near_number.group(1))
        if parsed and parsed >= EARLIEST_CONTRACT:
            return parsed
    return None


def _due_date(text: str, not_before: Optional[date]) -> Optional[date]:
    """Срок передачи объекта.

    Формулировки разные, поэтому выражений несколько. Дата раньше самого
    договора сроком передачи быть не может — такое совпадение отбрасывается.
    """
    for pattern in TRANSFER_RES:
        for match in pattern.finditer(text):
            parsed = parse_date(match.group(1))
            if parsed and (not_before is None or parsed >= not_before):
                return parsed
    return None


def _parties(text: str) -> tuple[str, str]:
    """Делит преамбулу на блок застройщика и блок участника.

    Реквизиты в договоре идут подряд и внешне неотличимы: ИНН банка эскроу,
    ОГРН застройщика и СНИЛС дольщика — просто числа рядом. Разделяет их
    оборот «именуемое в дальнейшем «Застройщик»»: всё до него относится к
    застройщику, всё между ним и таким же оборотом про участника — к
    участнику.
    """
    developer_role = ROLE_DEVELOPER_RE.search(text)
    participant_role = ROLE_PARTICIPANT_RE.search(text)

    if developer_role is None:
        return text, text

    developer_block = text[: developer_role.start()]
    end = participant_role.start() if participant_role else developer_role.end() + 1500
    participant_block = text[developer_role.end(): end]
    return developer_block, participant_block


def _client_name(text: str) -> Optional[str]:
    """ФИО участника долевого строительства.

    В блоке участника подписант застройщика уже не встречается, так что
    берётся первое ФИО. Отчество — самый надёжный признак: без него любая
    пара слов с заглавной буквы читается как имя.
    """
    match = FIO_RE.search(text)
    return " ".join(match.groups()) if match else None


def _passport(text: str) -> Optional[str]:
    match = PASSPORT_RE.search(text)
    if not match:
        return None

    series = re.sub(r"\s+", " ", match.group(1))
    value = f"{series} № {match.group(2)}"

    issued = PASSPORT_ISSUED_RE.search(text, match.end(), match.end() + 200)
    if issued:
        who = _address(issued.group(1))
        if who:
            value += ", выдан " + who
    return value


def _developer_name(block: str) -> Optional[str]:
    """Наименование застройщика — последнее, названное до его роли.

    В договоре упомянуты и банк эскроу, и подрядчик, и они записаны так же.
    Застройщик — тот, за кем идёт «именуемое в дальнейшем «Застройщик»»,
    то есть последний перед этим оборотом.
    """
    matches = list(COMPANY_RE.finditer(block))
    if not matches:
        return None

    match = matches[-1]
    form = match.group(1).strip()
    if form.lower().startswith("общество"):
        form = "ООО"

    name = _clean(match.group(2)) or ""
    # PDF рвёт длинное название по строкам: «СР -\nГРУПП» превращается в
    # «СР - ГРУПП». Дефис между двумя частями одного слова склеиваем обратно.
    name = re.sub(r"(?<=[А-ЯЁA-Z])\s+-\s+(?=[А-ЯЁA-Z])", "-", name)
    # Внутренние прямые кавычки приводим к тем же угловым, что и внешние.
    name = name.replace('"', "«", 1).replace('"', "»")
    if name.count("«") > name.count("»"):
        name += "»"
    return f"{form.upper()} «{name}»"


def _snils(text: str) -> Optional[str]:
    dashed = SNILS_RE.search(text)
    if dashed:
        return dashed.group(1).strip()

    plain = SNILS_PLAIN_RE.search(text)
    if plain:
        digits = plain.group(1)
        # Приводим к привычному виду 123-456-789 00.
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:9]} {digits[9:]}"
    return None


def extract(text: str, doc_type: str = "") -> Requisites:
    """Реквизиты из текста. Пустые поля — норма, а не ошибка."""
    if not text:
        return Requisites()

    result = Requisites()
    flat_text = re.sub(r"[  \t]+", " ", text)
    developer_block, participant_block = _parties(text)

    number = NUMBER_RE.search(text)
    if number:
        result.contract_number = number.group(1).strip(" .,;")

    result.contract_date = _contract_date(text)
    result.contract_price = parse_price(text)
    result.due_date = _due_date(text, result.contract_date)

    design_number = DESIGN_NUMBER_RE.search(text)
    if design_number:
        result.apartment = design_number.group(1)
    else:
        flat = FLAT_RE.search(text)
        if flat:
            result.apartment = flat.group(1)

    area = AREA_RE.search(text)
    if area:
        result.area = _to_decimal(area.group(1))

    project = PROJECT_RE.search(text)
    if project:
        result.project = _clean(project.group(1))

    for pattern in OBJECT_ADDRESS_RES:
        address = pattern.search(flat_text)
        if address:
            result.object_address = _address(address.group(1))
            break

    result.client_name = _client_name(participant_block)

    birth = BIRTH_RE.search(participant_block)
    if birth:
        result.client_birth_date = parse_date(birth.group(1) or birth.group(2) or "")

    result.client_passport = _passport(participant_block)
    result.client_snils = _snils(participant_block)

    person_inn = INN_PERSON_RE.search(participant_block)
    if person_inn:
        result.client_inn = person_inn.group(1)
    else:
        # В шапке иска ИНН стоит отдельной строкой, без слова «ИНН».
        # Двенадцать цифр подряд в блоке стороны — это он и есть.
        bare = BARE_INN_RE.search(participant_block[:1500])
        if bare:
            result.client_inn = bare.group(1)

    client_address = CLIENT_ADDRESS_RE.search(re.sub(r"\s+", " ", participant_block))
    if client_address:
        result.client_address = _address(client_address.group(1))

    result.developer_name = _developer_name(developer_block)

    # ИНН юридического лица — десять цифр, физического — двенадцать.
    company_inn = INN_COMPANY_RE.search(developer_block)
    if company_inn:
        result.developer_inn = company_inn.group(1)

    ogrn = OGRN_RE.search(developer_block)
    if ogrn:
        result.developer_ogrn = ogrn.group(1)

    # Претензия и иск пересказывают договор, и данные из них те же самые.
    # У прочих документов совпадающие числа значат другое: в решении суда
    # это присуждённая сумма, а не цена договора.
    if doc_type not in ("ddu", "ddu_amendment", "assignment", "claim", "lawsuit", ""):
        result.contract_price = None
        result.due_date = None

    return result
