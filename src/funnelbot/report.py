from __future__ import annotations

import csv
import io
from typing import List

from .core import format_amount, format_date
from .schema import Funnel, Step
from .store import Store

BOM = chr(0xFEFF)


def leads_csv(store: Store) -> bytes:
    users = store.leads()
    keys = sorted({k for u in users for k in u["answers"]})
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "username", "first_name", "source", "created", "step", "consented", "blocked", "stopped",
                     "bought", *keys])
    for user in users:
        writer.writerow([
            user["id"], user["username"], user["first_name"], user["source"], format_date(user["created_at"]),
            user["step"], "yes" if user["consented_at"] else "", "yes" if user["blocked"] else "",
            "yes" if user["stopped"] else "", " ".join(store.owned_products(user["id"])),
            *[user["answers"].get(k, "") for k in keys],
        ])
    return (BOM + buffer.getvalue()).encode("utf-8")


def step_targets(step: Step) -> List[str]:
    targets: List[str] = []
    rows = [step.buttons] + [n.buttons for n in step.nudges]
    for group in rows:
        for row in group:
            for button in row:
                if button.goto:
                    targets.append(button.goto)
                elif button.pay:
                    targets.append(f"pay:{button.pay}")
                elif button.manager:
                    targets.append("manager")
    if step.pay:
        targets.append(f"pay:{step.pay}")
    if step.next:
        targets.append(step.next + (f" (after {step.wait}s)" if step.wait else ""))
    unique: List[str] = []
    for target in targets:
        if target not in unique:
            unique.append(target)
    return unique


def describe_flow(funnel: Funnel) -> List[str]:
    lines: List[str] = []
    width = max((len(s) for s in funnel.steps), default=1)
    for sid, step in funnel.steps.items():
        marks = []
        if sid == funnel.start:
            marks.append("start")
        if step.ask:
            marks.append(f"asks {step.ask.key}")
        if step.nudges:
            marks.append(f"{len(step.nudges)} nudge(s)")
        if step.paid:
            marks.append(f"after payment -> {step.paid}")
        if step.end:
            marks.append("end")
        arrows = ", ".join(step_targets(step)) or "-"
        suffix = f"   [{'; '.join(marks)}]" if marks else ""
        lines.append(f"  {sid.ljust(width)}  ->  {arrows}{suffix}")
    return lines


def describe_products(funnel: Funnel) -> List[str]:
    lines: List[str] = []
    for pid, product in funnel.products.items():
        methods = funnel.methods_for(pid)
        priced = []
        for method in methods:
            currency = funnel.payments.currency_of(method) or ""
            priced.append(f"{format_amount(product.prices[currency], currency)} via {method}")
        prices = ", ".join(priced)
        gives = []
        for rule in product.access:
            if rule.kind == "channel":
                gives.append(f"channel {rule.chat} for {rule.days} days" if rule.days else f"channel {rule.chat} forever")
            elif rule.kind == "message":
                gives.append("message" + (f" + {len(rule.files)} file(s)" if rule.files else ""))
            else:
                gives.append("manager request")
        lines.append(f"  {pid}: {product.title}: {prices or 'no payment method'}; gives: {', '.join(gives) or 'nothing'}")
    return lines
