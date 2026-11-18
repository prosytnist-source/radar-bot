"""Крапельна подача: кожен запуск публікує НЕ БІЛЬШЕ ОДНОГО допису з черги, щоб канал жив рівномірно.
Запускати часто (наприклад, кожні 15–30 хв): python3 -m digest.drip
Правила: нічні години (23:00–07:00 за Києвом) — лише термінове (важливість ≥ 9); інтервал між постами залежить від розміру черги (15–60 хв);
застарілі (> --max-age годин) дописи відкидаються; вищу важливість — першою."""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import control, deliver, publish
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent
URGENT = 9


def interval_minutes(n: int) -> float:
    return min(30.0, max(15.0, 240.0 / max(n, 1)))


def choose(q: list[dict], now: datetime, last: datetime | None, tz: str = "Europe/Kyiv", night=(23, 7)) -> dict | None:
    if not q:
        return None
    urgent = [e for e in q if e["importance"] >= URGENT]
    if urgent:
        return sorted(urgent, key=lambda e: e["created"])[0]
    hour = now.astimezone(ZoneInfo(tz)).hour
    if hour >= night[0] or hour < night[1]:
        return None
    if last and now - last < timedelta(minutes=interval_minutes(len(q))):
        return None
    return sorted(q, key=lambda e: (-e["importance"], e["created"]))[0]


def _limit(e: dict, a) -> float:
    """Гарячі новини (важливість ≥ 9) швидко втрачають цінність: живуть у черзі менше, ніж решта."""
    return getattr(a, "max_age_urgent", 4.0) if e["importance"] >= URGENT else a.max_age


def _created(e: dict) -> datetime:
    t = datetime.fromisoformat(e["created"])
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _drop_before(a) -> datetime | None:
    v = getattr(a, "drop_before", None)
    if not v:
        return None
    return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)


def step(a, st: State, now: datetime) -> dict | None:
    """Один цикл подачі: команди керування, вибір допису, надсилання. Повертає надісланий допис (або None)."""
    try:
        control.sync(st, publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"))
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"(команди керування недоступні: {exc})", file=sys.stderr)
    if st.paused():
        print("⏸ Пауза (/stop): нічого не публікую.")
        return None
    full = st.load_queue()
    q = [e for e in full if now - datetime.fromisoformat(e["created"]) <= timedelta(hours=_limit(e, a))]
    cut = _drop_before(a)
    if cut:  # разове очищення: усе, створене до вказаного моменту, прибрати з черги й дозволити згенерувати свіжу версію
        old = [e for e in q if _created(e) < cut]
        if old and not a.dry:
            for e in old:
                st.forget(e["headline"])
            print(f"Очищено застарілих постів: {len(old)} (створені до {cut.isoformat(timespec='minutes')}).")
        q = [e for e in q if _created(e) >= cut]
    if not a.dry:
        for e in full:
            if e not in q:
                st.log_event("expired", e["headline"], now)
    e = choose(q, now, st.last_sent())
    if not e:
        last = st.last_sent()
        wait = ""
        if q and last:
            left = interval_minutes(len(q)) - (now - last).total_seconds() / 60
            if left > 0:
                wait = f"; наступний через ~{left:.0f} хв"
        print(f"Черга: {len(q)}; зараз нічого публікувати (інтервал, ніч або порожньо){wait}. Остання публікація: {last.isoformat(timespec='minutes') if last else 'ніколи'}.")
        if not a.dry:
            st.save_queue(q)
        return None
    print(f"Публікую: {e['headline']} (важливість {e['importance']}); у черзі лишиться {len(q) - 1}")
    if a.dry:
        return None
    try:
        deliver.send_entry(e, publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID"), st, now)
    except SystemExit as exc:
        print(f"✗ не надіслано: {exc}", file=sys.stderr)
        st.save_queue(q)  # лишаємо в черзі, спробуємо наступного разу
        return None
    q.remove(e)
    st.set_last_sent(now)
    st.log_event("sent", e["headline"], now)
    st.save_queue(q)
    return e


# ---------- безперервний режим (GitHub Actions) ----------
def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def apply_sent(st: State, sent: list[tuple[dict, datetime]]) -> None:
    """Повторно застосувати вже надіслані дописи до свіжого стану (після git reset): прибрати з черги, оновити «останню публікацію»."""
    if not sent:
        return
    heads = {e["headline"] for e, _ in sent}
    st.save_queue([x for x in st.load_queue() if x["headline"] not in heads])
    st.set_last_sent(max(t for _, t in sent))
    for e, t in sent:
        st.log_event("sent", e["headline"], t)


def push_state() -> bool:
    git("add", "state")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return True
    git("-c", "user.name=radar-bot", "-c", "user.email=radar-bot@users.noreply.github.com", "commit", "-qm", "state: drip")
    return git("push", "-q").returncode == 0


def silence_delay(now_kyiv: datetime) -> float:
    """Секунд до найближчої 09:00:00 за Києвом (від'ємне — вже минула сьогодні)."""
    return (now_kyiv.replace(hour=9, minute=0, second=0, microsecond=0) - now_kyiv).total_seconds()


def fixed_tick(a, poll: float, end: float, last_try: dict) -> None:
    """Щоденні пости (свято, курс, пальне, «Визначні постаті» 12:00, «Історичний факт» 17:00, «Кіт-Радар» 22:00) зсередини безперервного запуску. «Хвилину мовчання» прибрано за рішенням власника."""
    from . import fixed
    now = time.time()
    for kind in ("holiday", "rates", "fuel", "figure", "fact", "cat"):  # запас до radar-fixed: не частіше раз на 10 хв, щоб не засипати повідомленнями про збій
        if now - last_try.get(kind, 0) >= 600:
            last_try[kind] = now
            fixed.main(["--kind", kind])


def loop(a, poll: float = 60.0) -> int:
    """Працює a.loop хвилин: кожну хвилину бере свіжий стан із репозиторію, виконує крок і одразу публікує стан назад."""
    end = time.time() + a.loop * 60
    last_try: dict = {}
    pending: list[tuple[dict, datetime]] = []  # надіслані, але ще не збережені в репозиторії (щоб не повторити)
    while True:
        try:
            if a.git:
                git("fetch", "-q", "origin", "main")
                git("reset", "-q", "--hard", "origin/main")
            st = State(ROOT / "state")
            apply_sent(st, pending)
            now = datetime.now(timezone.utc)
            e = step(a, st, now)
            if e:
                pending.append((e, now))
            if getattr(a, "fixed", False):
                fixed_tick(a, poll, end, last_try)
            if getattr(a, "daily", False):
                from . import poll as poll_mod, toprating  # не «poll»: так називається пауза між циклами
                for name, fn in (("опитування", poll_mod.tick), ("топ-рейтинг", toprating.tick)):
                    try:
                        print(f"[{name}]", fn(st, datetime.now(timezone.utc)))
                    except Exception as exc:  # noqa: BLE001
                        print(f"[{name}] збій: {exc}", file=sys.stderr)
            if getattr(a, "evening", False):
                from . import evening
                for name, fn in (("збір дня", evening.collect_tick), ("вечірній огляд", evening.tick)):
                    try:
                        print(f"[{name}]", fn(st, datetime.now(timezone.utc)))
                    except Exception as exc:  # noqa: BLE001
                        print(f"[{name}] збій: {exc}", file=sys.stderr)
            if getattr(a, "gen_every", 0):
                from . import gen
                print("[свіжа порція]", gen.tick(st, datetime.now(timezone.utc), a.gen_every))
            if getattr(a, "watch", False):
                from . import watch
                print("[ранній сигнал]", watch.tick(st, datetime.now(timezone.utc), watch.load_cfg()))
            if a.git:
                if push_state():
                    pending.clear()
                else:
                    print("(не вдалося зберегти стан; повторю в наступному циклі)", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ збій циклу: {exc}", file=sys.stderr)
        if time.time() + poll >= end:
            break
        time.sleep(poll)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evening", action="store_true", help="щодня збирати матеріали й ввечері випускати один аналітичний огляд (замість потоку коротких постів)")
    ap.add_argument("--gen-every", type=float, default=0, help="у безперервному режимі: раз на стільки хвилин (вдень) генерувати невелику свіжу порцію в чергу; 0 — вимкнено")
    ap.add_argument("--daily", action="store_true", help="у безперервному режимі: щоденне опитування читачів і вечірній «Топ-рейтинг» о 21:00")
    ap.add_argument("--max-age", type=float, default=8.0, help="скільки годин пост може чекати в черзі (вечірня порція має дожити до ранку)")
    ap.add_argument("--max-age-urgent", type=float, default=4.0, help="скільки годин у черзі живе гаряча новина (важливість ≥ 9)")
    ap.add_argument("--drop-before", help="UTC 'YYYY-MM-DDTHH:MM': прибрати з черги пости, створені раніше (безпечно лишати в команді: на пізніші пости не діє)")
    ap.add_argument("--fixed", action="store_true", help="у безперервному режимі публікувати щоденні пости (свято, курс, пальне, хвилина мовчання о 09:00:00)")
    ap.add_argument("--watch", action="store_true", help="у безперервному режимі стежити за телеграм-каналами з watch.json (ранній сигнал)")
    ap.add_argument("--now", help="фіксований час UTC 'YYYY-MM-DDTHH:MM' (для перевірки)")
    ap.add_argument("--dry", action="store_true", help="лише показати, що було б надіслано")
    ap.add_argument("--loop", type=float, default=0, help="працювати безперервно стільки хвилин (для Actions); 0 — один крок")
    ap.add_argument("--poll", type=float, default=60, help="пауза між циклами, секунд")
    ap.add_argument("--git", action="store_true", help="у безперервному режимі синхронізувати state через git")
    a = ap.parse_args(argv)
    if a.loop:
        return loop(a, a.poll)
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    step(a, State(ROOT / "state"), now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
