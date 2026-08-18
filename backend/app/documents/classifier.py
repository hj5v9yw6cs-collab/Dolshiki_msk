"""Определение типа документа.

Сначала правила по имени файла и тексту — они предсказуемы, объяснимы и
не требуют внешних сервисов. Уверенность считается по числу и весу
совпавших признаков; ниже порога документ уходит в очередь ручной
проверки, а не помечается типом молча.

Порядок именно такой намеренно: юрист должен понимать, почему система
решила, что это акт, а не претензия. «Так решила модель» в карточке дела
не годится.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .types import DOC_TYPES, DocType

# Совпадение по тексту весит больше, чем по имени файла: имя часто
# случайное («скан_001.pdf»), а текст — это сам документ.
WEIGHT_TEXT = 3.0
WEIGHT_FILENAME = 1.0

# Ниже этого порога тип считается неподтверждённым.
CONFIDENCE_THRESHOLD = 0.45


@dataclass
class Guess:
    code: str
    confidence: float
    signals: List[str] = field(default_factory=list)
    needs_review: bool = True

    @property
    def explanation(self) -> str:
        if not self.signals:
            return "Признаков не найдено — тип нужно указать вручную."
        return "Совпало: " + ", ".join(f"«{signal}»" for signal in self.signals)


def normalize(value: str) -> str:
    """Приводит к нижнему регистру и схлопывает пробелы и ё."""
    text = (value or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def _score(doc_type: DocType, filename: str, text: str) -> tuple[float, List[str]]:
    if not doc_type.filename_words and not doc_type.text_words:
        return 0.0, []

    for stop in doc_type.stop_words:
        if normalize(stop) in text:
            return 0.0, []

    score = 0.0
    signals: List[str] = []

    for word in doc_type.filename_words:
        if normalize(word) in filename:
            score += WEIGHT_FILENAME
            signals.append(word)

    for phrase in doc_type.text_words:
        if normalize(phrase) in text:
            score += WEIGHT_TEXT
            signals.append(phrase)

    return score, signals


def classify(filename: str, text: str = "") -> Guess:
    """Тип документа с оценкой уверенности."""
    clean_name = normalize(filename)
    clean_text = normalize(text)

    scored = []
    for doc_type in DOC_TYPES:
        score, signals = _score(doc_type, clean_name, clean_text)
        if score > 0:
            scored.append((score, doc_type, signals))

    if not scored:
        return Guess(code="other", confidence=0.0, signals=[], needs_review=True)

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_type, best_signals = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # Уверенность определяет прежде всего сила признаков: совпадение по
    # тексту документа весомее, чем по имени файла. Отрыв от второго
    # кандидата только уточняет оценку — иначе единственная слабая догадка
    # получала бы высокий балл просто потому, что с ней некому спорить.
    total = best_score + runner_up
    margin = (best_score - runner_up) / total if total else 1.0
    strength = min(best_score / (WEIGHT_TEXT + WEIGHT_FILENAME), 1.0)
    confidence = round(min(strength * (0.6 + 0.4 * margin), 0.99), 2)

    return Guess(
        code=best_type.code,
        confidence=confidence,
        signals=best_signals[:4],
        needs_review=confidence < CONFIDENCE_THRESHOLD,
    )
