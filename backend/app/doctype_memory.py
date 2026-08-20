"""Память о том, как юрист называет свои документы.

Правила в классификаторе описывают документы вообще: заголовок, обороты,
слова в имени файла. Но каждая практика называет файлы по-своему —
«ои_претензия», «трек иск», «дду скан», — и правилам эти привычки
неизвестны.

Здесь система запоминает исправления. Юрист поменял тип руками — значит,
правила ошиблись, и в имени файла почти наверняка было слово, по которому
человек понял всё сразу. Это слово и запоминается. Со второго-третьего
исправления такие файлы начинают определяться сами.

Учит любой ручной выбор типа — и исправление, и подтверждение уже
стоящего. Первое говорит «правила ошиблись», второе — «в этот раз всё
верно, запомни надёжнее»; и то и другое сказано человеком про конкретное
имя файла.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .documents.classifier import normalize
from .documents.types import type_title
from .models import TypeHint

# Слова короче этого ни о чём не говорят.
MIN_WORD = 4

# Служебные слова из имён файлов: они встречаются у документов всех типов
# и, запомнившись, начали бы тянуть классификацию куда попало.
STOP_WORDS = {
    "скан", "копия", "файл", "документ", "итог", "новый", "final", "copy",
    "scan", "file", "document", "img", "image", "photo", "фото", "версия",
    "печать", "подпись", "готово", "правка",
}

# Одно исправление весит столько. Порог перевеса — ниже.
LEARN_WEIGHT = 2

# С этого веса память спорит с уверенным правилом; вдвое меньше хватает,
# чтобы поправить догадку, в которой система и сама не уверена.
OVERRIDE_WEIGHT = 4


def words(filename: str) -> List[str]:
    """Осмысленные слова из имени файла.

    Хеши и случайные наборы (`h6xj8aap1rmerfli`) отбрасываются: они
    уникальны для файла и запоминать их бессмысленно — второй раз такое
    имя не встретится.
    """
    stem = re.sub(r"\.[a-z0-9]{1,5}$", "", normalize(filename or ""))
    found = []
    for word in re.split(r"[^a-zа-я0-9]+", stem):
        if len(word) < MIN_WORD or word in STOP_WORDS or word.isdigit():
            continue
        # Смесь букв и цифр длиной от восьми — почти наверняка хеш.
        if len(word) >= 8 and any(char.isdigit() for char in word):
            continue
        found.append(word)
    return found


def remember(session: DbSession, filename: str, doc_type: str) -> int:
    """Запоминает, что файл с такими словами в имени — документ этого типа."""
    learned = 0
    for word in words(filename):
        hint = session.scalars(
            select(TypeHint).where(TypeHint.word == word, TypeHint.doc_type == doc_type)
        ).first()
        if hint is None:
            hint = TypeHint(word=word, doc_type=doc_type, weight=LEARN_WEIGHT)
            session.add(hint)
        else:
            hint.weight += LEARN_WEIGHT
            hint.updated_at = datetime.now(timezone.utc)
        learned += 1
    return learned


def suggest(session: DbSession, filename: str) -> Optional[tuple]:
    """Тип по прошлым исправлениям и его вес, если память что-то помнит."""
    found = words(filename)
    if not found:
        return None

    # Вес типа — вес самого «наученного» слова, а не сумма всех.
    # Суммировать нельзя: одно исправление сразу добавляет несколько слов
    # из одного имени, и их сумма выглядела бы как несколько подтверждений.
    # Настоящее подтверждение — это когда одно и то же слово исправляют
    # снова, уже на другом файле.
    scores: Dict[str, int] = {}
    for hint in session.scalars(select(TypeHint).where(TypeHint.word.in_(found))):
        scores[hint.doc_type] = max(scores.get(hint.doc_type, 0), hint.weight)

    if not scores:
        return None

    best = max(scores.items(), key=lambda item: item[1])
    return best if best[1] >= LEARN_WEIGHT else None


def refine(session: DbSession, guess, filename: str):
    """Поправляет догадку правил тем, что система уже усвоила.

    Память вмешивается в двух случаях: правила не уверены в своём ответе,
    либо память видела такое слово несколько раз и уверена сильнее их.
    В остальном правила остаются главными: они объяснимы, а память —
    статистика по привычкам, и ошибку в ней разглядеть труднее.
    """
    learned = suggest(session, filename)
    if learned is None:
        return guess

    doc_type, weight = learned
    if doc_type == guess.code:
        return guess

    if weight >= OVERRIDE_WEIGHT or guess.needs_review:
        guess.code = doc_type
        guess.needs_review = weight < OVERRIDE_WEIGHT
        guess.signals = [f"по прошлым исправлениям такие файлы — «{type_title(doc_type)}»"]
    return guess
