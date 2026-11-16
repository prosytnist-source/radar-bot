"""Запуск: python3 -m digest.run --window day --top 8 --out draft.md  (нічого нікуди не публікує)."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

from .cluster import Cluster, cluster_items
from .fetch import fetch_all, parse_feed
from .rank import WINDOWS_HOURS, rank
from . import control, llm, publish, state as stmod, synth, telegram_fmt
from .report import render

# Бюджет найпотужнішої моделі: ранок 2, обід 1, вечір 2, підсумок дня 1 (квота скидається ~10:00 за Києвом).
SLOTS = {
    "morning": {"window": "day", "premium": 2, "top": 10, "candidates": 16, "batch": 5},
    "noon": {"window": "hour", "premium": 1, "top": 5, "candidates": 9, "batch": 5},
    "evening": {"window": "hour", "premium": 2, "top": 8, "candidates": 13, "batch": 5},
    "digest": {"window": "day", "premium": 1, "top": 6, "candidates": 8},
}
ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", choices=list(WINDOWS_HOURS), default="day")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--min-sources", type=int, default=2)
    ap.add_argument("--threshold", type=float, default=0.25, help="поріг подібності для групування (0..1)")
    ap.add_argument("--sources", default=str(ROOT / "sources.json"))
    ap.add_argument("--fixtures", help="тека з локальними RSS-файлами замість інтернету (для перевірки)")
    ap.add_argument("--now", help="фіксований час 'YYYY-MM-DDTHH:MM' UTC (для тестів)")
    ap.add_argument("--out", help="зберегти чернетку у файл")
    ap.add_argument("--synth", action="store_true", help="етап 2: ШІ-синтез і допис UA/EN (чернетки у теці drafts/, нічого не публікує)")
    ap.add_argument("--candidates", type=int, default=8, help="скільки подій віддати моделі")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--fallback-model", default=llm.FALLBACK_MODEL, help="на що перейти, якщо ліміт основної моделі вичерпано (порожньо = не переходити)")
    ap.add_argument("--langs", default="uk", choices=["uk", "uk,en"], help="мови чернеток: uk (за замовчуванням, економить квоту) або uk,en")
    ap.add_argument("--premium", type=int, default=3, help="скільки найвидатніших подій обробити окремими запитами на головній моделі")
    ap.add_argument("--batch", type=int, default=3, help="скільки решти подій в одному запиті (на запасній моделі)")
    ap.add_argument("--max-per-region", type=int, default=3)
    ap.add_argument("--include-soft", action="store_true", help="не відкидати культуру/спорт")
    ap.add_argument("--dry-prompt", action="store_true", help="показати запит до моделі без виклику (ключ не потрібен)")
    ap.add_argument("--list-models", action="store_true", help="показати моделі, доступні вашому ключу")
    ap.add_argument("--publish", action="store_true", help="після генерації надіслати пости в канал (TELEGRAM_CHAT_ID), не повторюючи вже опубліковане; поважає паузу /stop")
    ap.add_argument("--enqueue", action="store_true", help="не публікувати одразу, а поставити пости в чергу: їх рівномірно випускатиме python3 -m digest.drip")
    ap.add_argument("--no-dedupe", action="store_true", help="не відкидати події, про які вже писали")
    ap.add_argument("--slot", choices=list(SLOTS), help="готовий режим запуску: morning | noon | evening | digest (бюджет преміум-запитів і вікно)")
    args = ap.parse_args(argv)
    if args.slot:
        ap.set_defaults(**SLOTS[args.slot])
        args = ap.parse_args(argv)

    if args.list_models:
        print("\n".join(llm.list_models(llm.load_key())))
        return 0

    st = stmod.State(ROOT / "state")
    if args.publish or args.enqueue:
        try:
            control.sync(st, publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"))
        except SystemExit:
            pass  # власника не налаштовано: команди зупинки недоступні, але публікація працює
        except Exception as exc:  # noqa: BLE001
            print(f"  (команди керування недоступні: {exc})", file=sys.stderr)
        if st.paused():
            print("⏸ Канал на паузі (/stop). Запуск пропущено; відновити: /start у боті або python3 -m digest.control --start", file=sys.stderr)
            return 0
    cfg = json.loads(pathlib.Path(args.sources).read_text(encoding="utf-8"))
    sources = [s for s in cfg["sources"] if s.get("enabled", True)]
    by_id = {s["id"]: s for s in sources}
    now = datetime.fromisoformat(args.now).replace(tzinfo=timezone.utc) if args.now else datetime.now(timezone.utc)

    if args.fixtures:
        items, errors = [], {}
        for s in sources:
            p = pathlib.Path(args.fixtures) / f"{s['id']}.xml"
            if p.exists():
                items.extend(parse_feed(p.read_bytes(), s["id"], s["name"]))
    else:
        items, errors = fetch_all(sources)

    ok = len({i.source_id for i in items})
    print(f"Джерел із даними: {ok}/{len(sources)}; матеріалів: {len(items)}", file=sys.stderr)
    for sid, err in errors.items():
        print(f"  ✗ {sid}: {err}", file=sys.stderr)

    pool = args.candidates if args.synth or args.dry_prompt else args.top
    ranked = rank(cluster_items(items, args.threshold), now, args.window, args.min_sources, pool)
    if args.synth or args.dry_prompt:
        return run_synth(ranked, by_id, now, cfg.get("timezone", "Europe/Kyiv"), args)
    text = render(ranked, by_id, now, cfg.get("timezone", "Europe/Kyiv"), args.window)
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
        print(f"Чернетку збережено: {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def run_synth(ranked, by_id, now, tz, args) -> int:
    langs = tuple(args.langs.split(","))
    if args.dry_prompt:
        print(synth.system_for(langs, batch=True), end="\n\n---\n\n")
        print(synth.build_batch_prompt(ranked[:2], by_id))
        return 0
    key = llm.load_key()
    if args.slot == "digest":
        return run_digest(ranked, by_id, now, tz, args, key)
    cache = ROOT / "cache"
    cache.mkdir(exist_ok=True)
    state = {"model": args.model}
    st = stmod.State(ROOT / "state")
    if (args.publish or args.enqueue) and not args.no_dedupe:
        before = len(ranked)
        ranked = [r for r in ranked if not st.is_duplicate(r, now)]
        if before != len(ranked):
            print(f"  (пропущено подій, про які вже писали: {before - len(ranked)})", file=sys.stderr)

    def ck_of(r, brief=False):
        h = hashlib.sha1(("\n".join(sorted(i.link for i in r.cluster.items)) + "|" + ",".join(langs) + ("|brief" if brief else "")).encode()).hexdigest()[:20]
        return cache / f"{h}.json"

    def call(system, prompt, model):
        """Запит із переходом на запасну модель при 429/503. Повертає (текст, модель)."""
        waits = 0
        while True:
            try:
                return llm.generate_json(system, prompt, model, key), model
            except llm.LLMError as exc:
                if "HTTP 503" in str(exc) and (not args.fallback_model or model == args.fallback_model) and waits < 3:
                    waits += 1
                    print(f"  … {model} перевантажена, чекаю {20 * waits} с", file=sys.stderr)
                    time.sleep(20 * waits)
                    continue
                if llm.is_busy(exc) and args.fallback_model and model != args.fallback_model:
                    print(f"  ↪ модель {model} недоступна ({str(exc)[:9]}), переходжу на {args.fallback_model}", file=sys.stderr)
                    state["model"] = model = args.fallback_model
                    continue
                raise

    done, todo = {}, []
    for r in ranked:
        hit = False
        for ck in (ck_of(r), ck_of(r, True)):
            if ck.exists() and not hit:
                try:
                    done[id(r)] = (r, synth.parse_synthesis(ck.read_text(encoding="utf-8"), synth.texts_for(r), langs))
                    print(f"  ✓ [з кешу] {r.cluster.items[0].title[:60]}", file=sys.stderr)
                    hit = True
                except synth.BadSynthesis:
                    pass
        if not hit:
            todo.append(r)

    def accept(r, parsed, raw, brief=False):
        ck_of(r, brief).write_text(raw, encoding="utf-8")  # кешуємо лише відповіді, що пройшли перевірку
        done[id(r)] = (r, parsed)
        note = f" (відкинуто непідтверджених тверджень: {parsed['dropped']})" if parsed["dropped"] else ""
        print(f"  ✓ {r.cluster.items[0].title[:60]}{note}", file=sys.stderr)

    def single(r, model, allow_split=True, brief=False):
        """Окремий запит; порожній заголовок — один повтор; змішаний кластер — розбиваємо на менші групи."""
        last, offs = None, ()
        for _ in range(2):
            raw, _m = call(synth.system_for(langs, brief=brief), synth.build_prompt(r, by_id), model)
            try:
                accept(r, synth.parse_synthesis(raw, synth.texts_for(r), langs), raw, brief)
                return
            except synth.BadSynthesis as exc:
                last = exc
                offs = exc.off
                fd = ROOT / "cache" / "failed"
                fd.mkdir(parents=True, exist_ok=True)
                (fd / f"{now:%H%M%S}-{abs(hash(raw)) % 10**6}.txt").write_text(raw, encoding="utf-8")  # для діагностики
                if "неоднорідний" in str(exc):
                    break
        print(f"  ✗ {r.cluster.items[0].title[:50]}: {last}", file=sys.stderr)
        if allow_split and "неоднорідний" in str(last):
            if offs:  # модель сама вказала, які видання пишуть про іншу подію: ділимо за її підказкою
                groups = [[i for i in r.cluster.items if i.source_id not in offs], [i for i in r.cluster.items if i.source_id in offs]]
                parts = rank([Cluster(items=g, vec=r.cluster.vec) for g in groups if g], now, args.window, 2, 3)
            else:
                parts = rank(cluster_items(r.cluster.items, args.threshold + 0.25), now, args.window, 2, 3)
            for sub in parts:
                if len(sub.cluster.items) < len(r.cluster.items) and not ck_of(sub).exists():
                    print(f"  ↳ розбито: {sub.cluster.items[0].title[:50]}", file=sys.stderr)
                    single(sub, model, allow_split=False, brief=brief)

    premium, bulk = todo[: args.premium], todo[args.premium :]
    stop = False
    try:
        for r in premium:  # найвидатніші історії: окремий запит на головній моделі
            try:
                single(r, state["model"])
            except llm.LLMError as exc:
                if "HTTP 429" in str(exc):
                    raise
                print(f"  ✗ пропускаю (збій моделі): {str(exc)[:60]}", file=sys.stderr)
        bulk_model = args.fallback_model or state["model"]
        for i in range(0, len(bulk), args.batch):  # решта: кілька історій в одному запиті
            chunk = bulk[i : i + args.batch]
            try:
                raw, _ = call(synth.system_for(langs, batch=True, brief=True), synth.build_batch_prompt(chunk, by_id), bulk_model)
                for r, (res, rawev) in zip(chunk, synth.parse_batch(raw, chunk, langs)):
                    if isinstance(res, Exception):
                        print(f"  ✗ {r.cluster.items[0].title[:50]}: {res}", file=sys.stderr)
                        if "заголовка" in str(res) or "неоднорідний" in str(res):
                            single(r, bulk_model, brief=True)
                    else:
                        accept(r, res, rawev, True)
            except synth.BadSynthesis as exc:
                print(f"  ✗ пакет: {exc}; обробляю історії окремо", file=sys.stderr)
                for r in chunk:
                    single(r, bulk_model, allow_split=False, brief=True)
            except llm.LLMError as exc:
                if "HTTP 429" in str(exc):
                    raise
                print(f"  ✗ пропускаю пакет (збій моделі): {str(exc)[:60]}", file=sys.stderr)
    except llm.LLMError as exc:
        print(f"  ✗ {str(exc)[:160]}", file=sys.stderr)
        print("Ліміт або перевантаження: зупиняюсь і зберігаю, що встигли. Спробуйте пізніше (ліміт оновлюється щодоби за тихоокеанським часом).", file=sys.stderr)
    chosen = synth.select(list(done.values()), args.top, args.max_per_region, args.include_soft)
    out = ROOT / "drafts" / f"{now:%Y%m%d-%H%M}-{args.window}"
    out.mkdir(parents=True, exist_ok=True)
    for n, (r, s) in enumerate(chosen, 1):
        for lang in langs:
            (out / f"{n:02d}-{lang}.html").write_text(telegram_fmt.render_post(r, s, by_id, now, lang, tz), encoding="utf-8")
        prev = pick_preview(r, by_id)
        (out / f"{n:02d}-{langs[0]}.json").write_text(json.dumps({"preview": prev, "headline": s["headline"]["uk"]}, ensure_ascii=False), encoding="utf-8")
        print(f"\n[{n}] {s['headline']['uk']}  (важливість {s['importance']}, {s['category']}, {s['region']}){' 🖼' if prev else ''}")
    print(f"\nЧернетки: {out}", file=sys.stderr)
    if args.enqueue:
        enqueue_chosen(chosen, out, langs[0], st, now)
    elif args.publish:
        publish_chosen(chosen, out, langs[0], st, now)
    return 0


def pick_preview(r, by_id) -> str | None:
    """Стаття, чия ілюстрація піде над постом: свіжа, з картинкою в RSS, не з джерела з обережністю/держфінансуванням."""
    for it in sorted(r.cluster.items, key=lambda i: i.published, reverse=True):
        src = by_id.get(it.source_id, {})
        if it.image and not src.get("caution") and src.get("type") not in ("state", "independent_exile"):
            return it.link
    return None


def enqueue_chosen(chosen, out, lang, st, now) -> None:
    q = st.load_queue()
    for n, (r, s) in enumerate(chosen, 1):
        if st.headline_seen(s["headline"]["uk"], now):
            print(f"  (повтор за змістом, пропущено: {s['headline']['uk'][:50]})", file=sys.stderr)
            continue
        meta = json.loads((out / f"{n:02d}-{lang}.json").read_text(encoding="utf-8"))
        q.append({"created": now.isoformat(), "importance": s["importance"], "headline": s["headline"]["uk"], "preview": meta.get("preview"),
                  "html": (out / f"{n:02d}-{lang}.html").read_text(encoding="utf-8")})
        st.add(r, now, s["headline"]["uk"])  # одразу вважаємо «баченим», щоб наступні запуски не додали те саме
    st.save_queue(q)
    print(f"У чергу додано: {len(chosen)}; усього в черзі: {len(q)}", file=sys.stderr)


def publish_chosen(chosen, out, lang, st, now) -> None:
    token, chat = publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID")
    sent = 0
    for n, (r, s) in enumerate(chosen, 1):
        if st.headline_seen(s["headline"]["uk"], now):
            continue
        f = out / f"{n:02d}-{lang}.html"
        meta = json.loads((out / f"{n:02d}-{lang}.json").read_text(encoding="utf-8"))
        try:
            publish.send(token, chat, f.read_text(encoding="utf-8"), meta.get("preview"))
        except SystemExit as exc:  # помилка Telegram: не зупиняємо решту й не позначаємо як опубліковане
            print(f"  ✗ не надіслано [{n}]: {exc}", file=sys.stderr)
            continue
        st.add(r, now, s["headline"]["uk"])
        sent += 1
        time.sleep(2)
    print(f"Опубліковано в канал: {sent}", file=sys.stderr)


def run_digest(ranked, by_id, now, tz, args, key) -> int:
    rs = ranked[: args.top]
    prompt = synth.build_digest_prompt(rs, by_id)
    model = args.model
    for _ in range(2):
        try:
            raw = llm.generate_json(synth.DIGEST_SYSTEM, prompt, model, key)
            d = synth.parse_digest(raw, rs)
            break
        except llm.LLMError as exc:
            if llm.is_busy(exc) and args.fallback_model and model != args.fallback_model:
                print(f"  ↪ перехід на {args.fallback_model}", file=sys.stderr)
                model = args.fallback_model
                continue
            print(f"  ✗ {str(exc)[:160]}", file=sys.stderr)
            return 0
        except synth.BadSynthesis as exc:
            print(f"  ✗ {exc}", file=sys.stderr)
    else:
        return 0
    out = ROOT / "drafts" / f"{now:%Y%m%d-%H%M}-digest"
    out.mkdir(parents=True, exist_ok=True)
    (out / "digest-uk.html").write_text(telegram_fmt.render_digest(d, rs, by_id, now, tz), encoding="utf-8")
    print(f"\n{d['headline']}\n\nЧернетки: {out}", file=sys.stderr)
    if args.publish:
        try:
            publish.send(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID"), (out / "digest-uk.html").read_text(encoding="utf-8"))
            print("Підсумок дня опубліковано.", file=sys.stderr)
        except SystemExit as exc:
            print(f"  ✗ не надіслано: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
