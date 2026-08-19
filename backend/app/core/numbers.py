"""Числа прописью.

В претензии и иске сумма пишется дважды: цифрами и словами. Расхождение
между ними — повод для спора, поэтому слова получаются из того же числа,
что и цифры, а не набираются руками.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Tuple

ONES_MALE = (
    "", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
)
ONES_FEMALE = (
    "", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
)
TEENS = (
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
)
TENS = (
    "", "", "двадцать", "тридцать", "сорок", "пятьдесят",
    "шестьдесят", "семьдесят", "восемьдесят", "девяносто",
)
HUNDREDS = (
    "", "сто", "двести", "триста", "четыреста", "пятьсот",
    "шестьсот", "семьсот", "восемьсот", "девятьсот",
)

# Разряды: название в трёх формах и род единиц этого разряда.
SCALES: Tuple[Tuple[Tuple[str, str, str], bool], ...] = (
    (("", "", ""), True),                              # единицы
    (("тысяча", "тысячи", "тысяч"), False),            # женский род
    (("миллион", "миллиона", "миллионов"), True),
    (("миллиард", "миллиарда", "миллиардов"), True),
)

RUBLES = ("рубль", "рубля", "рублей")
KOPEKS = ("копейка", "копейки", "копеек")


def plural(number: int, forms: Tuple[str, str, str]) -> str:
    """Форма слова при числе: 1 рубль, 2 рубля, 5 рублей."""
    number = abs(number) % 100
    if 11 <= number <= 19:
        return forms[2]
    last = number % 10
    if last == 1:
        return forms[0]
    if 2 <= last <= 4:
        return forms[1]
    return forms[2]


def _under_thousand(value: int, male: bool) -> List[str]:
    ones = ONES_MALE if male else ONES_FEMALE
    words: List[str] = []

    if value // 100:
        words.append(HUNDREDS[value // 100])
    remainder = value % 100

    if 10 <= remainder <= 19:
        words.append(TEENS[remainder - 10])
    else:
        if remainder // 10:
            words.append(TENS[remainder // 10])
        if remainder % 10:
            words.append(ones[remainder % 10])
    return words


def number_to_words(value: int) -> str:
    """Целое число прописью: 15613672 -> «пятнадцать миллионов …»."""
    if value == 0:
        return "ноль"

    words: List[str] = []
    if value < 0:
        words.append("минус")
        value = -value

    groups: List[int] = []
    while value:
        groups.append(value % 1000)
        value //= 1000

    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        names, male = SCALES[index] if index < len(SCALES) else (("", "", ""), True)
        words.extend(_under_thousand(group, male))
        if names[0]:
            words.append(plural(group, names))

    return " ".join(word for word in words if word)


def money_to_words(amount: Decimal) -> str:
    """Сумма прописью так, как её пишут в документах.

    15613672.30 -> «Пятнадцать миллионов шестьсот тринадцать тысяч
    шестьсот семьдесят два рубля 30 копеек».

    Копейки цифрами — так принято и так короче: их всё равно читают как
    число, а не как слово.
    """
    amount = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rubles = int(amount)
    kopeks = int((amount - rubles) * 100)

    words = number_to_words(rubles)
    return (
        f"{words[:1].upper()}{words[1:]} {plural(rubles, RUBLES)} "
        f"{kopeks:02d} {plural(kopeks, KOPEKS)}"
    )
