"""Комплектность документов по стадиям дела.

Отвечает на вопрос «чего не хватает, чтобы идти дальше». Наборы разные:
для претензии достаточно договора и подтверждения оплаты, для иска нужен
уже полный комплект.
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
    "claim": [
        Requirement("ddu", "Основание требований"),
        Requirement("payment", "Подтверждение оплаты по договору"),
        Requirement("passport", "Данные для претензии и доверенности"),
        Requirement("act", "Подтверждает дату передачи", optional=True),
        Requirement("expert_report", "Для требований по недостаткам", optional=True),
    ],
    "suit_filed": [
        Requirement("ddu", "Основание требований"),
        Requirement("payment", "Подтверждение оплаты по договору"),
        Requirement("passport", "Данные истца"),
        Requirement("claim", "Досудебный порядок"),
        Requirement("power_of_attorney", "Полномочия представителя"),
        Requirement("developer_reply", "Если ответ был", optional=True),
        Requirement("act", "Подтверждает дату передачи", optional=True),
        Requirement("expert_report", "Для требований по недостаткам", optional=True),
    ],
    "writ": [
        Requirement("court_decision", "Основание для исполнительного листа"),
    ],
}

# Стадии без своего набора проверяются по ближайшей, где набор задан.
FALLBACK = {
    "new": "claim", "qualification": "claim", "contract": "claim", "documents": "claim",
    "claim_wait": "claim", "expertise": "suit_filed", "hearings": "suit_filed",
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
