#!/usr/bin/env python
"""Сверка JS-ядра демо с серверным ядром на Python.

Демо-страница считает в браузере, боевой виджет — на сервере. Две
реализации обязаны давать одинаковые цифры, иначе демо вводит в
заблуждение. Скрипт прогоняет обе по случайным и краевым случаям и
сравнивает итог, разбивку по сегментам и исключённые периоды.

    ../.venv/bin/python demo/parity_check.py [число_случаев]
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.calculator import (  # noqa: E402
    DefectsInput,
    DelayInput,
    ExpenseInput,
    calculate_defects,
    calculate_delay,
)
from app.core.legal_config import load_config  # noqa: E402
from app.presenters import result_to_dict  # noqa: E402

CONFIG_PATH = ROOT / "backend" / "config" / "legal-config.json"
ENGINE_PATH = ROOT / "demo" / "engine.js"
TODAY = date(2026, 8, 17)

RATE_MODES = ["on_obligation_date", "on_actual_date", "per_segment", "manual", "on_claim_date"]


def run_js(cases: list[dict]) -> list[dict]:
    """Считает те же случаи движком demo/engine.js в Node."""
    script = f"""
const engineApi = require({json.dumps(str(ENGINE_PATH))});
const config = require({json.dumps(str(CONFIG_PATH))});
const engine = engineApi.createEngine(config);
const today = engineApi.toDay({json.dumps(TODAY.isoformat())});
const cases = JSON.parse(require("fs").readFileSync(process.env.CASES_PATH, "utf8"));
const out = cases.map(function (item) {{
  try {{
    const result = item.mode === "delay"
      ? engine.calcDelay(item.payload, today)
      : engine.calcDefects(item.payload, today);
    return {{ ok: true, result: result }};
  }} catch (error) {{
    return {{ ok: false, error: error.message }};
  }}
}});
process.stdout.write(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(cases, handle, ensure_ascii=False)
        cases_path = handle.name
    try:
        completed = subprocess.run(
            ["node", "-e", script],
            capture_output=True, text=True, env={**os.environ, "CASES_PATH": cases_path},
        )
        if completed.returncode != 0:
            raise RuntimeError("Node упал:\n" + completed.stderr[-3000:])
    finally:
        Path(cases_path).unlink(missing_ok=True)
    return json.loads(completed.stdout)


def run_python(case: dict, config) -> dict:
    payload = case["payload"]
    expenses = [
        ExpenseInput(title=e["title"], amount=Decimal(e["amount"]), code=e["code"])
        for e in payload.get("expenses", [])
    ]
    shared = dict(
        rate_mode=payload.get("rate_mode", ""),
        manual_rate=Decimal(payload["manual_rate"]) if payload.get("manual_rate") else None,
        claim_date=date.fromisoformat(payload["claim_date"]) if payload.get("claim_date") else None,
        moral_harm=Decimal(payload.get("moral_harm") or 0),
        include_consumer_penalty=payload.get("include_consumer_penalty", True),
        expenses=expenses,
        today=TODAY,
    )
    if case["mode"] == "delay":
        result = calculate_delay(
            DelayInput(
                contract_price=Decimal(payload["contract_price"]),
                due_date=date.fromisoformat(payload["due_date"]),
                actual_date=date.fromisoformat(payload["actual_date"]) if payload.get("actual_date") else None,
                is_individual=payload.get("is_individual", True),
                **shared,
            ),
            config,
        )
    else:
        result = calculate_defects(
            DefectsInput(
                repair_cost=Decimal(payload["repair_cost"]),
                demand_served_date=date.fromisoformat(payload["demand_served_date"]),
                satisfied_date=date.fromisoformat(payload["satisfied_date"]) if payload.get("satisfied_date") else None,
                expertise_cost=Decimal(payload.get("expertise_cost") or 0),
                include_repair_cost_in_total=payload.get("include_repair_cost_in_total", True),
                **shared,
            ),
            config,
        )
    return result_to_dict(result)


def comparable(result: dict) -> dict:
    """Оставляет только то, что обязано совпадать до копейки."""
    return {
        "total": result["total"],
        "period_days": result["period"]["days"],
        "period_start": result["period"]["start"],
        "period_end": result["period"]["end"],
        "segments": [
            {
                "start": s["start"], "end": s["end"], "days": s["days"],
                # Ставку сравниваем числом: Python отдаёт литерал из конфига
                # ("16.0"), JS нормализует ("16"). В интерфейсе используется
                # rate_display, где обе дают одинаковое "16%".
                "rate": float(s["rate"].replace(",", ".")), "amount": s["amount"],
                "capped_from": float(s["rate_before_cap"].replace(",", ".")) if s["rate_before_cap"] else None,
                "formula": s["formula"],
            }
            for s in result["segments"]
        ],
        "excluded": [{"start": e["start"], "end": e["end"], "days": e["days"]} for e in result["excluded"]],
        "lines": [{"code": l["code"], "amount": l["amount"]} for l in result["lines"]],
        "notes": result["notes"],
        "warnings": result["warnings"],
    }


def random_date(start: date, end: date, rng: random.Random) -> date:
    return start + timedelta(days=rng.randrange((end - start).days + 1))


def build_cases(count: int, rng: random.Random) -> list[dict]:
    cases: list[dict] = []

    # Краевые случаи: границы мораториев, високосный год, нулевая просрочка.
    fixed = [
        ("delay", {"contract_price": "8500000", "due_date": "2021-12-30", "actual_date": "2025-09-15"}),
        ("delay", {"contract_price": "1000000", "due_date": "2022-06-10", "actual_date": "2022-07-10"}),
        ("delay", {"contract_price": "1000000", "due_date": "2022-03-28", "actual_date": "2022-03-29"}),
        ("delay", {"contract_price": "1000000", "due_date": "2023-06-29", "actual_date": "2023-07-02"}),
        ("delay", {"contract_price": "1000000", "due_date": "2020-02-01", "actual_date": "2020-03-01"}),
        ("delay", {"contract_price": "1000000", "due_date": "2022-02-01", "actual_date": "2022-01-15"}),
        ("delay", {"contract_price": "1000000", "due_date": "2022-02-01", "actual_date": "2022-02-01"}),
        ("delay", {"contract_price": "3333333", "due_date": "2021-12-01", "actual_date": "2022-01-31",
                   "rate_mode": "per_segment"}),
        ("delay", {"contract_price": "7777777", "due_date": "2024-01-01", "actual_date": None,
                   "rate_mode": "per_segment", "moral_harm": "50000"}),
        ("delay", {"contract_price": "1", "due_date": "2023-01-01", "actual_date": "2023-01-02"}),
        ("defects", {"repair_cost": "300000", "demand_served_date": "2022-01-01", "satisfied_date": "2022-01-21"}),
        ("defects", {"repair_cost": "300000", "demand_served_date": "2023-01-01", "satisfied_date": "2025-12-31"}),
        ("defects", {"repair_cost": "450000", "demand_served_date": "2025-07-01", "satisfied_date": None,
                     "expertise_cost": "45000"}),
        ("defects", {"repair_cost": "100000", "demand_served_date": "2022-01-01", "satisfied_date": "2022-01-05"}),
    ]
    for mode, payload in fixed:
        cases.append({"mode": mode, "payload": payload})

    earliest = date(2018, 1, 1)
    for _ in range(count):
        mode = rng.choice(["delay", "defects"])
        rate_mode = rng.choice(RATE_MODES)
        start = random_date(earliest, date(2025, 12, 1), rng)
        finished = rng.random() < 0.7
        end = random_date(start, TODAY, rng) if finished else None

        payload = {
            "rate_mode": rate_mode,
            "moral_harm": str(rng.choice([0, 0, 15000, 50000])),
            "include_consumer_penalty": rng.random() < 0.8,
            "expenses": [],
        }
        if rate_mode == "manual":
            payload["manual_rate"] = str(rng.choice([7.5, 16, 16.5, 21]))
        if rate_mode == "on_claim_date":
            payload["claim_date"] = random_date(date(2023, 1, 1), TODAY, rng).isoformat()
        if rng.random() < 0.4:
            payload["expenses"] = [
                {"title": "Госпошлина", "amount": str(rng.randrange(400, 60000)), "code": "duty"},
                {"title": "Представитель", "amount": str(rng.randrange(10000, 90000)), "code": "lawyer"},
            ]

        if mode == "delay":
            payload["contract_price"] = str(rng.randrange(500_000, 40_000_000))
            payload["due_date"] = start.isoformat()
            payload["actual_date"] = end.isoformat() if end else None
            payload["is_individual"] = rng.random() < 0.85
        else:
            payload["repair_cost"] = str(rng.randrange(30_000, 3_000_000))
            payload["demand_served_date"] = start.isoformat()
            payload["satisfied_date"] = end.isoformat() if end else None
            payload["expertise_cost"] = str(rng.choice([0, 35000, 45000, 60000]))
            payload["include_repair_cost_in_total"] = rng.random() < 0.9

        cases.append({"mode": mode, "payload": payload})
    return cases


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    rng = random.Random(20260817)
    config = load_config(CONFIG_PATH)
    cases = build_cases(count, rng)

    js_results = run_js(cases)
    mismatches = []
    compared = 0
    both_failed = 0

    for case, js in zip(cases, js_results):
        try:
            py = comparable(run_python(case, config))
            py_error = None
        except Exception as exc:  # ошибки ввода тоже должны совпадать
            py, py_error = None, str(exc)

        if py_error:
            if js["ok"]:
                mismatches.append({"case": case, "reason": "Python отказал, JS посчитал", "python": py_error})
            else:
                both_failed += 1
            continue

        if not js["ok"]:
            mismatches.append({"case": case, "reason": "JS отказал, Python посчитал", "js": js["error"]})
            continue

        compared += 1
        got = comparable(js["result"])
        if got != py:
            diff = {k: {"python": py[k], "js": got[k]} for k in py if py[k] != got[k]}
            mismatches.append({"case": case, "reason": "расхождение", "diff": diff})

    print(f"Случаев всего:        {len(cases)}")
    print(f"Сравнено успешных:    {compared}")
    print(f"Обе реализации отказали (ожидаемо): {both_failed}")
    print(f"Расхождений:          {len(mismatches)}")

    for item in mismatches[:5]:
        print("\n--- расхождение ---")
        print(json.dumps(item, ensure_ascii=False, indent=2)[:1600])

    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
