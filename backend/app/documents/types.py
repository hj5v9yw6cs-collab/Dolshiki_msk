"""Типы документов по делу и папки, в которые они раскладываются."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class DocType:
    code: str
    title: str
    folder: str
    # Слова в имени файла и в тексте, по которым тип узнаётся.
    filename_words: List[str] = field(default_factory=list)
    text_words: List[str] = field(default_factory=list)
    # Слова, которые исключают тип, даже если совпало остальное.
    stop_words: List[str] = field(default_factory=list)


FOLDERS = {
    "01_Договор": "Договор",
    "02_Оплата": "Оплата",
    "03_Приемка": "Приёмка",
    "04_Экспертиза": "Экспертиза",
    "05_Претензия": "Претензия",
    "06_Суд": "Суд",
    "07_Исполнение": "Исполнение",
    "08_Личные": "Личные документы",
    "99_Прочее": "Прочее",
}

DOC_TYPES: List[DocType] = [
    DocType(
        "ddu", "Договор долевого участия", "01_Договор",
        filename_words=["дду", "договор"],
        text_words=["участия в долевом строительстве", "долевого участия",
                    "участник долевого строительства", "застройщик обязуется передать"],
        stop_words=["дополнительное соглашение", "уступки"],
    ),
    DocType(
        "ddu_amendment", "Дополнительное соглашение", "01_Договор",
        filename_words=["допсоглашение", "дополнительное", "допник", "дс"],
        text_words=["дополнительное соглашение"],
    ),
    DocType(
        "assignment", "Договор уступки прав", "01_Договор",
        filename_words=["уступка", "цессия"],
        text_words=["уступки прав требования", "договор цессии", "цедент"],
    ),
    DocType(
        "act", "Акт приёма-передачи", "03_Приемка",
        filename_words=["акт", "приемопередаточный", "приёма"],
        text_words=["акт приема-передачи", "акт приёма-передачи",
                    "передал, а участник долевого строительства принял"],
        stop_words=["акт выполненных работ", "акт осмотра"],
    ),
    DocType(
        "defect_list", "Смотровой лист / дефектная ведомость", "03_Приемка",
        filename_words=["смотровой", "дефект", "ведомость", "замечания"],
        text_words=["смотровой лист", "дефектная ведомость", "перечень недостатков",
                    "выявленные недостатки"],
    ),
    DocType(
        "payment", "Платёжный документ", "02_Оплата",
        filename_words=["платеж", "платёж", "чек", "квитанция", "поручение", "оплата"],
        text_words=["платежное поручение", "платёжное поручение", "получатель платежа",
                    "назначение платежа"],
    ),
    DocType(
        "mortgage", "Кредитный (ипотечный) договор", "02_Оплата",
        filename_words=["ипотека", "кредит"],
        text_words=["кредитный договор", "ипотечный договор", "заемщик обязуется"],
    ),
    DocType(
        "passport", "Паспорт", "08_Личные",
        filename_words=["паспорт", "passport"],
        text_words=["паспорт гражданина российской федерации", "код подразделения",
                    "место рождения"],
    ),
    DocType(
        "expert_report", "Заключение эксперта", "04_Экспертиза",
        filename_words=["заключение", "экспертиза", "эксперт", "смета"],
        text_words=["заключение специалиста", "заключение эксперта",
                    "стоимость устранения", "экспертное заключение"],
    ),
    DocType(
        "claim", "Претензия застройщику", "05_Претензия",
        filename_words=["претензия", "требование"],
        text_words=["претензия", "в добровольном порядке", "требую выплатить"],
        stop_words=["ответ на претензию"],
    ),
    DocType(
        "developer_reply", "Ответ застройщика", "05_Претензия",
        filename_words=["ответ"],
        text_words=["ответ на претензию", "на ваше обращение", "рассмотрев вашу претензию"],
    ),
    DocType(
        "lawsuit", "Исковое заявление", "06_Суд",
        filename_words=["иск", "исковое"],
        text_words=["исковое заявление", "прошу суд", "в районный суд"],
    ),
    DocType(
        "court_ruling", "Определение суда", "06_Суд",
        filename_words=["определение"],
        text_words=["определение", "суд определил"],
    ),
    DocType(
        "court_decision", "Решение суда", "06_Суд",
        filename_words=["решение"],
        text_words=["именем российской федерации", "решил:", "суд решил"],
    ),
    DocType(
        "writ", "Исполнительный лист", "07_Исполнение",
        filename_words=["исполнительный", "ил"],
        text_words=["исполнительный лист", "подлежит исполнению"],
    ),
    DocType(
        "power_of_attorney", "Доверенность", "08_Личные",
        filename_words=["доверенность"],
        text_words=["доверенность", "уполномочивает", "настоящей доверенностью"],
    ),
    DocType("other", "Прочее", "99_Прочее"),
]

DOC_TYPE_BY_CODE: Dict[str, DocType] = {item.code: item for item in DOC_TYPES}


def type_title(code: str) -> str:
    doc_type = DOC_TYPE_BY_CODE.get(code)
    return doc_type.title if doc_type else code


def type_folder(code: str) -> str:
    doc_type = DOC_TYPE_BY_CODE.get(code)
    return doc_type.folder if doc_type else "99_Прочее"


def catalog() -> List[dict]:
    return [
        {"code": item.code, "title": item.title, "folder": item.folder,
         "folder_title": FOLDERS.get(item.folder, item.folder)}
        for item in DOC_TYPES
    ]
