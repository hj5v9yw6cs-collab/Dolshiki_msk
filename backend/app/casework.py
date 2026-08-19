"""Предметная модель ведения дела: стадии, услуги, сроки.

Стадии заданы здесь списком, а не в базе: на потоке в 30 дел в месяц
редактор стадий — лишняя сущность, а порядок этапов у дел по 214-ФЗ
устойчивый. Если понадобится менять — правится этот файл, история дел
не ломается, потому что в базе хранится код стадии.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Stage:
    code: str
    title: str
    hint: str = ""
    is_final: bool = False


STAGES: List[Stage] = [
    Stage("new", "Новое", "Заявка принята, юрист ещё не связался"),
    Stage("qualification", "Квалификация", "Выясняем перспективы и считаем сумму"),
    Stage("contract", "Договор с клиентом", "Согласуем условия и подписываем"),
    Stage("documents", "Сбор документов", "Собираем ДДУ, акт, платёжки"),
    Stage("claim", "Претензия", "Готовим и направляем застройщику"),
    Stage("claim_wait", "Ожидание ответа", "Идёт срок на ответ по претензии"),
    Stage("expertise", "Экспертиза", "Назначена или проводится экспертиза"),
    Stage("suit_filed", "Иск подан", "Заявление направлено в суд"),
    Stage("hearings", "Заседания", "Дело рассматривается судом"),
    Stage("decision", "Решение", "Решение вынесено, ждём вступления в силу"),
    Stage("writ", "Исполнительный лист", "Получаем и предъявляем лист"),
    Stage("money", "Деньги получены", "Взыскание исполнено"),
    Stage("closed", "Закрыто", "Работа по делу завершена", is_final=True),
    Stage("rejected", "Отказ", "Не берём дело или клиент отказался", is_final=True),
]

STAGE_BY_CODE: Dict[str, Stage] = {stage.code: stage for stage in STAGES}
STAGE_ORDER: Dict[str, int] = {stage.code: index for index, stage in enumerate(STAGES)}

SERVICE_TYPES = {
    "delay": "Неустойка за просрочку передачи",
    "defects": "Недостатки отделки",
    "acceptance": "Помощь в приёмке",
    "other": "Другое",
}

REGIONS = {
    "msk": "Москва и область",
    "kzn": "Казань и Татарстан",
    "other": "Другой регион",
}

ROLES = {
    "manager": "Руководитель",
    "lawyer": "Юрист",
}

# Срок на ответ по претензии. Значение по умолчанию, в карточке правится руками.
CLAIM_RESPONSE_DAYS = 10


def is_valid_stage(code: str) -> bool:
    return code in STAGE_BY_CODE


def stage_title(code: str) -> str:
    stage = STAGE_BY_CODE.get(code)
    return stage.title if stage else code


def default_claim_deadline(sent_on: date) -> date:
    return sent_on + timedelta(days=CLAIM_RESPONSE_DAYS)


@dataclass(frozen=True)
class Deadline:
    """Ближайший срок по делу — то, из-за чего дела разваливаются."""

    kind: str
    title: str
    due_on: date
    days_left: int

    @property
    def is_overdue(self) -> bool:
        return self.days_left < 0

    @property
    def is_soon(self) -> bool:
        return 0 <= self.days_left <= 3


def next_deadline(case, today: Optional[date] = None) -> Optional[Deadline]:
    """Ближайший неистёкший срок, а если все просрочены — самый ранний."""
    today = today or date.today()
    candidates: List[Deadline] = []

    def add(kind: str, title: str, value) -> None:
        if not value:
            return
        due = value.date() if hasattr(value, "date") else value
        candidates.append(Deadline(kind, title, due, (due - today).days))

    if case.stage not in ("closed", "rejected", "money"):
        add("claim_response", "Ответ на претензию", case.claim_response_deadline)
        add("hearing", "Судебное заседание", case.next_hearing_on)
        add("appeal", "Срок обжалования", case.appeal_deadline)

    if not candidates:
        return None
    overdue = [item for item in candidates if item.is_overdue]
    if overdue:
        return min(overdue, key=lambda item: item.due_on)
    return min(candidates, key=lambda item: item.due_on)


def stage_catalog() -> List[dict]:
    return [
        {"code": stage.code, "title": stage.title, "hint": stage.hint, "is_final": stage.is_final}
        for stage in STAGES
    ]
