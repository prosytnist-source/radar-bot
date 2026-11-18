"""Мінімальний клієнт Gemini API (REST, без залежностей). Ключ беремо з середовища або з файлу ~/.multiview.env — ніколи не з коду."""
from __future__ import annotations

import json
import os
import pathlib
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-4-hydrogen"
FALLBACK_MODEL = "gemini-3.5-flash-lite"
ENV_FILE = pathlib.Path.home() / ".multiview.env"


class LLMError(RuntimeError):
    pass


def is_busy(exc: BaseException) -> bool:
    """Ліміт (429) або перевантаження моделі (503): варто спробувати іншу модель."""
    t = str(exc)
    return "HTTP 429" in t or "HTTP 503" in t or "Timeout" in t


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise LLMError("Не знайдено ключ Gemini. Збережіть його у файлі ~/.multiview.env (див. README).")
    return key


def _call(url: str, key: str, payload: dict | None, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=data, method="POST" if data else "GET", headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def list_models(key: str) -> list[str]:
    out = _call(f"{API}/models?pageSize=200", key, None)
    return sorted(m["name"].removeprefix("models/") for m in out.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", []))


def generate_json(system: str, prompt: str, model: str, key: str, retries: int = 2, timeout: int = 120) -> str:
    """Повертає текст відповіді (очікуємо JSON). На 429/5xx чекає й повторює; після вичерпання — LLMError."""
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    last = ""
    for attempt in range(retries):
        try:
            out = _call(f"{API}/models/{model}:generateContent", key, payload, timeout)
            parts = out["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {body}"
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise LLMError(last) from e
        except (URLError, OSError, KeyError, IndexError, json.JSONDecodeError) as e:  # OSError охоплює TimeoutError і обриви з'єднання
            last = f"{'Timeout' if isinstance(e, TimeoutError) or 'timed out' in str(e) else type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(3)
                continue
            raise LLMError(last) from e
    raise LLMError(last)
