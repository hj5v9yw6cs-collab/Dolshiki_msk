"""Комплектность документов по стадиям дела.

Отвечает на вопрос «чего не хватает, чтобы идти дальше», и только на
него. Проверяются три документа — ДДУ, претензия, исковое, — а не весь
подшиваемый комплект: остальное практика собирает и без напоминаний.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set

from .types import type_title


@dataclass(frozen=True)
class Requirement:
    doc_type: str
    why: str
    optional: bool = False


BY_STAGE: Dict[str, List[Requirement]] = {
    # Проверяются три документа, а не весь комплект. Остальное — паспорт,
    # договор услуг, квитанция, отчёты об отслеживании — практика собирает
    # и без напоминаний, и требовать их значило бы держать карточку красной
    # там, где на самом деле всё в порядке. Красный значок должен означать
    # «дальше идти нельзя», иначе на него перестают смотреть.
    "claim": [
        Requirement("ddu", "Основание требований"),
    ],
    "claim_wait": [
        Requirement("ddu", "Основание требований"),
        Requirement("claim", "Досудебный порядок"),
    ],
    # Порядок — тот, в котором комплект подшивается для подачи.
    "suit_filed": [
        Requirement("lawsuit", "Само требование к застройщику"),
        Requirement("ddu", "Основание требований"),
        Requirement("claim", "Досудебный порядок"),
    ],
    "writ": [
        Requirement("court_decision", "Основание для исполнительного листа"),
    ],
}

# Стадии без своего набора проверяются по ближайшей, где набор задан.
FALLBACK = {
    "new": "claim", "qualification": "claim", "contract": "claim", "documents": "claim",
    "expertise": "suit_filed", "hearings": "suit_filed",
    "decision": "writ", "money": "writ", "closed": "writ", "rejected": "claim",
}


def requirements_for(stage: str) -> List[Requirement]:
    if stage in BY_STAGE:
        return BY_STAGE[stage]
    return BY_STAGE.get(FALLBACK.get(stage, "claim"), [])


def build(stage: str, present_types: Iterable[str]) -> dict:
    """Чек-лист для карточки дела."""
    present: Set[str] = {code for code in present_types if code}
    items = []
    missing_required = 0

    for requirement in requirements_for(stage):
        is_present = requirement.doc_type in present
        if not is_present and not requirement.optional:
            missing_required += 1
        items.append({
            "doc_type": requirement.doc_type,
            "title": type_title(requirement.doc_type),
            "why": requirement.why,
            "optional": requirement.optional,
            "present": is_present,
        })

    return {
        "items": items,
        "missing_required": missing_required,
        "required_total": sum(1 for item in items if not item["optional"]),
        "ready": missing_required == 0,
    }
