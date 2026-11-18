"""«Питання дня» (16:00) і «Експертна думка Кота-Радара» (21:00).
16:00 — банер «кіт опитує» + анонімне опитування Telegram: питання з різних сфер (культура, освіта, наука, політика, спорт, бізнес, здоров'я, суспільство, технології, мандрівки),
сфера й питання щодня різні, без повторів по колу (закритий перелік нейтральних питань). 21:00 — опитування закривається, кіт-експерт публікує підсумок голосів і свою думку.
Підсумок рахує програма (числа не вигадуються); модель лише пише думку, і кожна цифра в ній перевіряється. Раз на тиждень (неділя, після допису) власнику в приват — статистика сфер і відповідей."""
from __future__ import annotations

import html
import json
import pathlib
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import llm, publish

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = "Europe/Kyiv"
BANNER_DIR = ROOT / "state" / "banners"
FALLBACK_IMG = ROOT / "assets" / "brand" / "news-cat.jpg"

Q = {
    "Культура": [
        ("Що найкраще допомагає відчути себе українцем?", ["Мова й література", "Музика й кіно", "Традиції та свята", "Історія й пам'ять"]),
        ("Як ви найчастіше знайомитеся з культурою?", ["Книжки", "Кіно й серіали", "Концерти й театр", "Соцмережі та відео"]),
        ("На що державі варто витрачати більше культурних коштів?", ["Бібліотеки й читання", "Кіно й музика", "Музеї та пам'ятки", "Сучасне мистецтво"]),
        ("Скільки українського контенту ви споживаєте щодня?", ["Майже весь", "Більшість", "Приблизно половину", "Менше половини"]),
    ],
    "Освіта": [
        ("Чого найбільше бракує сучасній школі?", ["Практичних навичок", "Сучасних підручників", "Підтримки вчителів", "Уваги до психологічного стану дітей"]),
        ("Яка навичка найважливіша для дитини?", ["Критичне мислення", "Іноземні мови", "Цифрова грамотність", "Уміння працювати з людьми"]),
        ("Що варто змінити у вищій освіті?", ["Більше практики на підприємствах", "Менше формальностей", "Гнучкі програми", "Зв'язок із наукою"]),
        ("Як ви вчитеся новому дорослим?", ["Онлайн-курси", "Книжки й статті", "Від колег і друзів", "Практика на ділі"]),
    ],
    "Наука і технології": [
        ("Яка технологія найбільше змінить наше життя за 5 років?", ["Штучний інтелект", "Відновлювана енергетика", "Медичні технології", "Автономний транспорт"]),
        ("Чи користуєтеся ви штучним інтелектом у щоденних справах?", ["Щодня", "Іноді", "Пробував(ла) раз-два", "Не користуюся"]),
        ("Чому варто інвестувати в науку насамперед?", ["Оборонні технології", "Медицина", "Енергетика", "Освіта і молоді вчені"]),
        ("Що найбільше турбує вас у цифровому світі?", ["Приватність даних", "Шахрайство", "Дезінформація", "Залежність від екранів"]),
    ],
    "Політика": [
        ("Що найважливіше для довіри до політика?", ["Чесність і прозорість", "Результати роботи", "Досвід і професіоналізм", "Збіг цінностей зі мною"]),
        ("Де ви найчастіше берете політичні новини?", ["Телеграм-канали", "Сайти новин", "Відео й подкасти", "Розмови з близькими"]),
        ("Що найбільше впливає на ваш вибір на виборах?", ["Програма", "Особистість кандидата", "Репутація партії", "Думка рідних і друзів"]),
        ("Що найбільше зміцнить довіру до держави?", ["Прозорість рішень", "Боротьба з корупцією", "Швидкі послуги", "Чесна комунікація"]),
    ],
    "Спорт": [
        ("Який спорт вам найближчий?", ["Футбол", "Біг і ходьба", "Силові й фітнес", "Єдиноборства й інші"]),
        ("Що найбільше заважає займатися спортом?", ["Брак часу", "Брак мотивації", "Втома", "Доступність і ціни"]),
        ("Чи дивитеся ви спортивні трансляції?", ["Регулярно", "Лише великі турніри", "Рідко", "Ніколи"]),
        ("Що найбільше надихає в українському спорті?", ["Перемоги на міжнародній арені", "Історії характерів", "Дитячий і аматорський спорт", "Паралімпійський рух"]),
    ],
    "Бізнес і гроші": [
        ("Що для малого бізнесу найважливіше сьогодні?", ["Доступні кредити", "Прості податки", "Захист від шахрайства", "Освітні програми"]),
        ("Як ви найчастіше платите?", ["Карткою", "Телефоном", "Готівкою", "Онлайн-переказами"]),
        ("Що ви робите, якщо з'являються зайві гроші?", ["Збираю на подушку безпеки", "Витрачаю на досвід і подорожі", "Допомагаю іншим", "Інвестую або вкладаю в навчання"]),
        ("Чому ви купуєте в українських виробників?", ["Підтримка економіки", "Якість", "Ціна", "Довіра до бренду"]),
    ],
    "Здоров'я і добробут": [
        ("Що найбільше впливає на ваше самопочуття?", ["Сон", "Харчування", "Рух", "Спокій і настрій"]),
        ("Як ви турбуєтеся про психічне здоров'я?", ["Розмови з близькими", "Хобі й природа", "Спеціаліст", "Поки не замислююся"]),
        ("Як часто ви ходите до лікаря без потреби?", ["Раз на рік", "Раз на кілька років", "Лише коли болить", "Майже ніколи"]),
        ("Який спосіб відпочити вам найкращий?", ["Прогулянка", "Книга чи кіно", "Зустріч із друзями", "Тиша й сон"]),
    ],
    "Суспільство і життя": [
        ("Що найбільше об'єднує людей зараз?", ["Спільна мета", "Волонтерство", "Спільні цінності", "Місцеві ініціативи"]),
        ("Як ви підтримуєте тих, хто поруч?", ["Словом", "Часом і допомогою", "Грошима", "Роботою чи досвідом"]),
        ("Що найбільше цінуєте у людях?", ["Щирість", "Відповідальність", "Гумор", "Доброта"]),
        ("Що зараз потрібне вашому місту найбільше?", ["Дороги й транспорт", "Безпека", "Зелені зони", "Послуги й сервіс"]),
    ],
    "Мандрівки та дозвілля": [
        ("Куди вас тягне найбільше?", ["Гори", "Море", "Міста й культура", "Тиха природа"]),
        ("Що ви берете із собою в дорогу обов'язково?", ["Книгу", "Навушники", "Фотоапарат чи телефон", "Смачні ласощі"]),
        ("Який вихідний вам найближчий?", ["Вдома з родиною", "У дорозі", "З друзями", "Окремо від усіх"]),
        ("Що ви плануєте в наступну відпустку?", ["Подорож Україною", "Поїздка за кордон", "Відпочинок вдома", "Ще не думав(ла)"]),
    ],
}


def pool() -> list[tuple[str, str, list[str]]]:
    return [(sph, q, opts) for sph, items in Q.items() for q, opts in items]


def pick(day) -> tuple[int, tuple[str, str, list[str]]]:
    """Питання дня: перемішаний, але без повторів порядок; кожне коло — новий порядок."""
    p = pool()
    n = day.toordinal()
    order = list(range(len(p)))
    random.Random(n // len(p)).shuffle(order)
    i = order[n % len(p)]
    return i, p[i]


def _load(st) -> dict:
    try:
        return json.loads((st.dir / "ask.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(st, d: dict) -> None:
    (st.dir / "ask.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _img(key: str) -> pathlib.Path:
    p = BANNER_DIR / f"{key}.jpg"
    return p if p.exists() else FALLBACK_IMG


def run_ask(st, now: datetime, token: str, chat: str, api=publish.api, send_photo=publish.send_photo) -> str:
    local = now.astimezone(ZoneInfo(TZ))
    i, (sph, q, opts) = pick(local.date())
    d = _load(st)
    cap = f"<b>Питання дня від Кота-Радара 🐱</b>\n<i>{html.escape(sph, quote=False)}</i>\n\nГолосуйте нижче. О 21:00 кіт-експерт підсумує й дасть свою думку."
    send_photo(token, chat, _img("ask"), cap)
    res = api("sendPoll", token, {"chat_id": chat, "question": q[:300], "options": json.dumps(opts, ensure_ascii=False), "is_anonymous": "true", "allows_multiple_answers": "false"})
    d["open"] = {"message_id": res["result"]["message_id"], "day": local.date().isoformat(), "q": q, "sphere": sph, "options": opts, "idx": i}
    _save(st, d)
    return f"питання надіслано: {sph}"


SYSTEM = (
    "Ти Кіт-Радар: тепло-іронічний, мудрий кіт-експерт україномовного каналу. Пишеш короткий висновок до опитування читачів. Мова: жива розмовна українська, прості речення, "
    "трохи народного гумору, але без вульгарності. Правила: 1) число або відсоток можна згадати ЛИШЕ з блоку ДАНІ, інших цифр не пиши; 2) не вигадуй фактів про світ, посилань, імен, "
    "організацій і досліджень: це твоя думка й життєва порада, а не звіт; 3) не агітуй за партії та політиків, не став діагнозів, не жартуй про війну, втрати й страждання; "
    "4) не називай результат «думкою українців»: це лише голоси читачів каналу. Поверни JSON {\"text\": \"...\"}: 3–4 речення (до 520 символів): що показали голоси, твоя думка, одна порада."
)


def _percent(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


def expert_text(q: str, opts: list[str], counts: list[int], total: int, key: str | None, call=llm.generate_json) -> str:
    lead = max(range(len(opts)), key=lambda i: counts[i]) if total else 0
    if key:
        data = f"Питання: {q}\nУсього голосів: {total}\n" + "\n".join(f"- {o}: {c} ({_percent(c, total)}%)" for o, c in zip(opts, counts))
        allowed = {str(total)} | {str(c) for c in counts} | {str(_percent(c, total)) for c in counts}
        for mdl in (llm.DEFAULT_MODEL, llm.FALLBACK_MODEL):
            try:
                text = str(json.loads(call(SYSTEM, "ДАНІ:\n" + data, mdl, key, retries=1, timeout=35)).get("text", "")).strip()
            except Exception:  # noqa: BLE001
                continue
            if 80 <= len(text) <= 640 and all(n in allowed for n in re.findall(r"\d+", text)):
                return text
    if not total:
        return "Цього разу голосів немає, тож відповім сам: найкраща відповідь на таке питання — та, яку ви можете пояснити собі чесно. Спробуйте завтра, а я поки заварю чай."
    return (f"Найбільше голосів — за «{opts[lead]}». Це лише голоси читачів каналу, а не вся країна, але напрям видно. "
            "Моя порада така: не поспішайте з висновками, а перевіряйте їх на власному досвіді.")


def run_expert(st, now: datetime, token: str, chat: str, key: str | None, api=publish.api, send_photo=publish.send_photo, send=publish.send, call=llm.generate_json) -> str:
    d = _load(st)
    o = d.get("open")
    if not o:
        return "відкритого питання немає (опитування о 16:00 не було)"
    try:
        res = api("stopPoll", token, {"chat_id": chat, "message_id": o["message_id"]}).get("result", {})
    except SystemExit as exc:
        d["open"] = None
        _save(st, d)
        return f"не вдалося закрити опитування: {exc}"
    counts = [int(x.get("voter_count", 0)) for x in res.get("options", [])] or [0] * len(o["options"])
    total = int(res.get("total_voter_count", sum(counts)))
    text = expert_text(o["q"], o["options"], counts, total, key, call)
    lines = [f"• {html.escape(op, quote=False)} — {_percent(c, total)}% ({c})" for op, c in zip(o["options"], counts)] if total else []
    cap = (f"<b>Експертна думка Кота-Радара 🐱</b>\n<i>{html.escape(o['sphere'], quote=False)}: {html.escape(o['q'], quote=False)}</i>\n\n"
           + ("\n".join(lines) + f"\n<i>Усього голосів: {total}. Це голоси читачів каналу.</i>\n\n" if total else "") + html.escape(text, quote=False))
    if len(cap) <= 1000:
        send_photo(token, chat, _img("expert"), cap)
    else:
        send_photo(token, chat, _img("expert"), f"<b>Експертна думка Кота-Радара 🐱</b>\n<i>{html.escape(o['q'], quote=False)}</i>")
        send(token, chat, cap.split("\n\n", 1)[1], None)
    d.setdefault("history", []).append({"day": o["day"], "sphere": o["sphere"], "q": o["q"], "options": o["options"], "counts": counts, "total": total})
    d["history"] = d["history"][-400:]
    d["open"] = None
    _save(st, d)
    return f"експертну думку опубліковано (голосів {total})"


def weekly_report(st, now: datetime, days: int = 7) -> str | None:
    """Текст для власника: що цікавить читачів за тиждень (сфери, популярні відповіді)."""
    cut = (now - timedelta(days=days)).date().isoformat()
    rows = [h for h in _load(st).get("history", []) if h["day"] >= cut]
    if not rows:
        return None
    by: dict[str, list[int]] = {}
    for h in rows:
        by.setdefault(h["sphere"], []).append(h["total"])
    out = [f"<b>Тижнева статистика «Питання дня» ({len(rows)} опитувань)</b>", "", "<b>Активність за сферами (середньо голосів):</b>"]
    for sph, v in sorted(by.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        out.append(f"• {html.escape(sph, quote=False)}: {sum(v) / len(v):.1f} (опитувань: {len(v)})")
    out += ["", "<b>Найпопулярніші відповіді:</b>"]
    for h in rows:
        if h["total"]:
            i = max(range(len(h["counts"])), key=lambda k: h["counts"][k])
            out.append(f"• {html.escape(h['q'], quote=False)} → «{html.escape(h['options'][i], quote=False)}» ({_percent(h['counts'][i], h['total'])}% з {h['total']})")
    out += ["", "<i>Перегляди й реакції Telegram бот-API не віддає, тому тут лише голоси опитувань.</i>"]
    return "\n".join(out)[:3900]


def run(kind: str, now: datetime, st, key: str | None, preview: bool, dry: bool = False) -> str:
    token = publish.env("TELEGRAM_BOT_TOKEN")
    chat = publish.env("TELEGRAM_OWNER_ID") if preview else publish.env("TELEGRAM_CHAT_ID")
    if kind == "ask":
        return run_ask(st, now, token, chat)
    msg = run_expert(st, now, token, chat, key)
    if now.astimezone(ZoneInfo(TZ)).weekday() == 6:
        rep = weekly_report(st, now)
        if rep:
            publish.send(token, publish.env("TELEGRAM_OWNER_ID"), rep, None)
            msg += "; тижневий звіт власнику надіслано"
    return msg
