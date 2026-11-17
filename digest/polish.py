"""Літературна вичитка: головна модель виправляє лише мову (слова, відмінки, стиль) у найважливіших постах.
Жодних нових фактів: числа мають збігатися, довжина — майже та сама; інакше лишаємо оригінал."""
from __future__ import annotations

import json
import re
from collections import Counter

from . import llm

SYSTEM = """You are a meticulous Ukrainian copy editor for a news channel.
You get a JSON object whose values are Ukrainian sentences written by a weaker model. Return the SAME JSON object (identical keys) with each value corrected.
Rules: fix wrong or invented words (calques, non-existent words), grammar, case endings, word order and style so it sounds like natural, neutral journalistic Ukrainian.
Do NOT add, remove or change any facts, names, numbers, dates or attributions. Do NOT make sentences longer than the original by more than 20 %. Keep headlines without a final period.
Return JSON only."""


def fields(s: dict) -> dict[str, str]:
    f = {"headline": s["headline"]["uk"]}
    if s.get("context"):
        f["context"] = s["context"]["uk"]
    for n, k in enumerate(s.get("known", [])):
        f[f"known{n}"] = k["uk"]
    for n, k in enumerate(s.get("differences", [])):
        f[f"diff{n}"] = k["uk"]
    for n, k in enumerate(s.get("outlets", [])):
        f[f"outlet{n}"] = k["uk"]
    return f


def valid(orig: dict[str, str], new) -> bool:
    """Відповідь прийнятна, лише якщо ключі ті самі, числа ті самі, довжина в межах, заголовок без крапки і ≤110 символів."""
    if not isinstance(new, dict) or set(new) != set(orig):
        return False
    for k, o in orig.items():
        n = new[k]
        if not isinstance(n, str) or not n.strip():
            return False
        if Counter(re.findall(r"\d+", o)) != Counter(re.findall(r"\d+", n)):
            return False
        if not (0.6 <= len(n) / max(len(o), 1) <= 1.4):
            return False
    h = new["headline"].strip()
    return len(h.rstrip(" .")) <= 110


def put(s: dict, new: dict[str, str]) -> None:
    s["headline"]["uk"] = new["headline"].strip().rstrip(" .")
    if "context" in new:
        s["context"]["uk"] = new["context"].strip()
    for n, k in enumerate(s.get("known", [])):
        k["uk"] = new[f"known{n}"].strip()
    for n, k in enumerate(s.get("differences", [])):
        k["uk"] = new[f"diff{n}"].strip()
    for n, k in enumerate(s.get("outlets", [])):
        k["uk"] = new[f"outlet{n}"].strip()


def apply(s: dict, model: str, key: str, cache=None) -> bool:
    """Вичитує пост на місці. Будь-яка помилка чи сумнівна відповідь — лишаємо оригінал (повертає False).
    cache — файл, де зберігається результат, щоб повторний запуск не витрачав запит."""
    orig = fields(s)
    if cache is not None and cache.exists():
        try:
            new = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            new = {}
        if new and valid(orig, new):
            put(s, new)
            return True
        return False
    try:
        raw = llm.generate_json(SYSTEM, json.dumps(orig, ensure_ascii=False), model, key, retries=1)
        new = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
    except (llm.LLMError, json.JSONDecodeError, TypeError):
        return False
    ok = valid(orig, new) and new != orig
    if cache is not None:
        cache.write_text(json.dumps(new if ok else {}, ensure_ascii=False), encoding="utf-8")
    if not ok:
        return False
    put(s, new)
    return True
