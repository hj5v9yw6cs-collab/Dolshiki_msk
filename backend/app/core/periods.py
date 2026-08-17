"""Работа с периодами дат.

DateRange — отрезок, включающий обе границы. Это соответствует тому, как
считается просрочка: и первый, и последний день входят в расчёт, если
правило дня в конфиге не переключено на 'exclusive_end'.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List

DAY = timedelta(days=1)


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"Некорректный период: {self.start} > {self.end}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def overlaps(self, other: "DateRange") -> bool:
        return self.start <= other.end and other.start <= self.end

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def make_range(start: date, end: date) -> DateRange | None:
    """DateRange или None, если период пустой/отрицательный."""
    if start > end:
        return None
    return DateRange(start, end)


def subtract(base: DateRange, cuts: Iterable[DateRange]) -> List[DateRange]:
    """Вычитает из base все пересечения с cuts.

    Используется для исключения мораторных периодов из периода просрочки.
    Результат отсортирован и не содержит пересечений.
    """
    result = [base]
    for cut in sorted(cuts, key=lambda r: r.start):
        next_result: List[DateRange] = []
        for segment in result:
            if not segment.overlaps(cut):
                next_result.append(segment)
                continue
            left = make_range(segment.start, min(segment.end, cut.start - DAY))
            right = make_range(max(segment.start, cut.end + DAY), segment.end)
            if left:
                next_result.append(left)
            if right:
                next_result.append(right)
        result = next_result
    return result


def split_at(segment: DateRange, boundaries: Iterable[date]) -> List[DateRange]:
    """Режет segment по датам boundaries.

    Дата-граница становится ПЕРВЫМ днём нового куска (так работают ставки
    ЦБ: ставка действует с даты изменения включительно).
    """
    points = sorted({b for b in boundaries if segment.start < b <= segment.end})
    if not points:
        return [segment]

    pieces: List[DateRange] = []
    cursor = segment.start
    for point in points:
        piece = make_range(cursor, point - DAY)
        if piece:
            pieces.append(piece)
        cursor = point
    tail = make_range(cursor, segment.end)
    if tail:
        pieces.append(tail)
    return pieces


def intersect(a: DateRange, b: DateRange) -> DateRange | None:
    return make_range(max(a.start, b.start), min(a.end, b.end))
