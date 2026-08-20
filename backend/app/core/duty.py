"""Государственная пошлина по иску о взыскании неустойки.

Считается по статье 333.19 Налогового кодекса — той её редакции, что
действует с 9 сентября 2024 года: Федеральный закон от 12.07.2024
№ 176-ФЗ переписал шкалу целиком, и суммы в ней отличаются от прежних в
разы. Шкала живёт в коде, а не в редактируемом конфиге, намеренно: это
не параметр практики, который юрист подбирает под свой суд, а закон,
меняющийся раз в двадцать лет. Опечатка в такой таблице не бросается в
глаза и даёт правдоподобно неверное число — поэтому каждая ступень здесь
закрыта тестом, а стык ступеней проверяется на непрерывность.

Дольщик — потребитель, и по пункту 3 статьи 17 Закона о защите прав
потребителей и подпункту 4 пункта 2 статьи 333.36 НК от пошлины
освобождён. Освобождение не безусловно: при цене иска свыше миллиона
пошлина платится с превышения (пункт 3 статьи 333.36 НК). Именно этот
случай и считается чаще всего, потому что цена ДДУ давно перевалила за
миллион, а неустойка от неё — нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple

# Ступень шкалы: с какой цены иска действует, фиксированная часть и процент
# с суммы превышения над нижней границей.
Step = Tuple[Decimal, Decimal, Decimal]

SCALE: List[Step] = [
    (Decimal(0),           Decimal(4_000),   Decimal(0)),
    (Decimal(100_000),     Decimal(4_000),   Decimal("3")),
    (Decimal(300_000),     Decimal(10_000),  Decimal("2.5")),
    (Decimal(500_000),     Decimal(15_000),  Decimal("2")),
    (Decimal(1_000_000),   Decimal(25_000),  Decimal("1")),
    (Decimal(3_000_000),   Decimal(45_000),  Decimal("0.7")),
    (Decimal(8_000_000),   Decimal(80_000),  Decimal("0.35")),
    (Decimal(24_000_000),  Decimal(136_000), Decimal("0.3")),
    (Decimal(50_000_000),  Decimal(214_000), Decimal("0.2")),
    (Decimal(100_000_000), Decimal(314_000), Decimal("0.15")),
]

# Потолок для последней ступени — прямо назван в законе.
MAXIMUM = Decimal(900_000)

# Порог, до которого потребитель не платит вовсе.
CONSUMER_FREE_LIMIT = Decimal(1_000_000)


def _rubles(amount: Decimal) -> str:
    """«1 500 000» — с неразрывными пробелами, как сумма в документе."""
    return f"{int(amount):,}".replace(",", "\u00a0")


def _round(amount: Decimal) -> Decimal:
    """Пошлина исчисляется в полных рублях (пункт 6 статьи 52 НК)."""
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def duty_for_value(claim_value: Decimal) -> Decimal:
    """Пошлина по имущественному иску, если бы истец не имел льготы."""
    claim_value = Decimal(claim_value)
    if claim_value <= 0:
        return Decimal(0)

    threshold, base, percent = SCALE[0]
    for step in SCALE:
        if claim_value > step[0]:
            threshold, base, percent = step

    amount = base + (claim_value - threshold) * percent / 100
    return _round(min(amount, MAXIMUM))


@dataclass(frozen=True)
class Duty:
    """Сколько платить и почему именно столько."""

    amount: Decimal
    claim_value: Decimal
    exempt: bool
    explanation: str

    @property
    def full(self) -> Decimal:
        """Пошлина без учёта льготы — то, что платил бы не потребитель."""
        return duty_for_value(self.claim_value)


def duty_for_claim(claim_value: Optional[Decimal], *, consumer: bool = True) -> Duty:
    """Пошлина по иску дольщика.

    `claim_value` — цена иска, то есть сумма денежных требований.
    Компенсация морального вреда в неё не входит: это требование
    неимущественное, и у потребителя оно пошлиной не облагается.
    """
    if claim_value is None:
        claim_value = Decimal(0)
    claim_value = Decimal(claim_value)

    if not consumer:
        amount = duty_for_value(claim_value)
        return Duty(
            amount=amount, claim_value=claim_value, exempt=False,
            explanation=(
                f"Госпошлина по цене иска {_rubles(claim_value)} руб. — "
                f"{_rubles(amount)} руб. (статья 333.19 НК)."
            ),
        )

    if claim_value <= CONSUMER_FREE_LIMIT:
        return Duty(
            amount=Decimal(0), claim_value=claim_value, exempt=True,
            explanation=(
                "Госпошлина не уплачивается: цена иска не превышает 1 000 000 руб., "
                "истец — потребитель (пункт 3 статьи 17 Закона о защите прав "
                "потребителей, подпункт 4 пункта 2 статьи 333.36 НК)."
            ),
        )

    full = duty_for_value(claim_value)
    threshold = duty_for_value(CONSUMER_FREE_LIMIT)
    amount = full - threshold
    return Duty(
        amount=amount, claim_value=claim_value, exempt=False,
        explanation=(
            f"Цена иска превышает 1 000 000 руб., поэтому пошлина уплачивается "
            f"с превышения: {_rubles(full)} − {_rubles(threshold)} = "
            f"{_rubles(amount)} руб. "
            f"(пункт 3 статьи 333.36 НК)."
        ),
    )
