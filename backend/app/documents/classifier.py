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
# случайное («скан_001.pdf»), а текст — это сам документ. Заголовок весит
# больше всего: русский документ начинается со своего названия, а вот
# упоминанием чужого он полон — иск целиком построен на пересказе ДДУ.
WEIGHT_TITLE = 8.0
WEIGHT_TEXT = 3.0
WEIGHT_FILENAME = 1.0

# Заголовок ищется не «где-то в начале», а именно с начала строки: иск
# упоминает договор во второй же строке, и по вхождению он читался бы как
# ДДУ. Смотрим первые строки и их склейку — распознанный PDF нередко рвёт
# длинное название на две строки.
TITLE_LINES = 5

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


def headings(text: str) -> List[str]:
    """Первые строки документа плюс их склейка — кандидаты в заголовок.

    Разбор идёт по исходному тексту, а не по схлопнутому: переводы строк
    здесь и есть разметка. Название может стоять и не первой строкой —
    выше него встречаются город и дата, — поэтому проверяются несколько.
    """
    lines = [normalize(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line][:TITLE_LINES]
    return lines + [" ".join(lines)]


def _score(
    doc_type: DocType, filename: str, text: str, title_lines: List[str]
) -> tuple[float, List[str]]:
    if not doc_type.filename_words and not doc_type.text_words and not doc_type.title_words:
        return 0.0, []

    for stop in doc_type.stop_words:
        if normalize(stop) in text:
            return 0.0, []

    score = 0.0
    signals: List[str] = []

    for phrase in doc_type.title_words:
        if any(line.startswith(normalize(phrase)) for line in title_lines):
            score += WEIGHT_TITLE
            signals.insert(0, phrase)
            break  # заголовок у документа один, дважды его не считаем

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
    title_lines = headings(text)

    scored = []
    for doc_type in DOC_TYPES:
        score, signals = _score(doc_type, clean_name, clean_text, title_lines)
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
    strength = min(best_score / (WEIGHT_TEXT + WEIGHT_FILENAME), 1.0)  # заголовок сам по себе даёт максимум
    confidence = round(min(strength * (0.6 + 0.4 * margin), 0.99), 2)

    return Guess(
        code=best_type.code,
        confidence=confidence,
        signals=best_signals[:4],
        needs_review=confidence < CONFIDENCE_THRESHOLD,
    )
