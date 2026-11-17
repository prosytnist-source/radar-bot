"""ШІ-синтез однієї події: що відомо / де розходяться / погляд кожного видання (українською й англійською)."""
from __future__ import annotations

import json
import re

from .rank import Ranked
from .report import label

SYSTEM = """You are a careful, neutral news-synthesis editor for a bilingual (Ukrainian and English) multi-perspective news digest.
Rules:
1. Use ONLY the headlines and snippets provided. Never add facts, numbers, names or quotes that are not in them.
2. EVIDENCE IS MANDATORY. Every statement you make about what an outlet says must come with a short VERBATIM quote (at least 12 characters, copied exactly from that outlet's headline or snippet, in the text's original language, no ellipses, no paraphrase) in the "evidence" / "quote" field. Statements without a quote that really appears in that outlet's text will be deleted by a program.
3. "known": facts stated by TWO OR MORE outlets (give a quote from each). A fact from only one outlet may still be listed but with one quote only; it will be shown as "according to <outlet>".
4. "differences": ONLY genuine conflicts (different facts, numbers, causes, or opposing interpretations). Give a quote from each side (at least two outlets). Different emphasis, different topics in short snippets, or numbers that may refer to different periods are NOT differences, unless the texts themselves present them as conflicting. If there are no conflicts return an empty list. Never invent disagreement.
5. You only see headlines and short snippets, not full articles. NEVER conclude that an outlet "does not mention", "omits", or is "the only outlet" to report something: absence from a snippet proves nothing.
6. "outlets": at most 5 outlets, only those whose text adds something distinct to the main story (a unique fact, framing or detail DIRECTLY about the event). Skip tangential details. Outlets that merely repeat the consensus must be left out (they are listed as links automatically). Do not start a sentence with the outlet name.
7a. Never write a caveat saying that only headlines/snippets were analysed or that details are missing: the footer already says it.
7. Outlets flagged state-funded or unverified funding are a perspective, not proof. Do NOT mention ownership or funding in caveats unless that outlet is the sole source of a specific claim.
8. Neutral wording, no opinions, no loaded adjectives. Write Ukrainian (uk) and English (en) versions of every text field; keep them equivalent. Do not hedge with "or" when a snippet is clear; if a number or claim is attributed to officials, say so.
8a. COHERENCE: all items in a cluster must describe the SAME event. Set "same_event" to false if the cluster mixes unrelated events; list in "off_topic" the ids of outlets whose item is about a different event than the main story (they will be removed). If fewer than two outlets remain on the main event, set "same_event" to false.
8b. HEADLINE: at most 90 characters, no trailing period, names the event (who/what happened), never stronger than the facts below it. Any number in the headline must appear in the texts. Name the main person, organisation or country (e.g. \"Trump\", \"Estonia\"); avoid vague nouns like \"discussion\", \"events\" or \"situation\".
8c. CONTEXT: ONE sentence of background (why this matters / who is who) taken from the texts, with a verbatim quote as evidence. If the texts give no such background, leave context empty strings and an empty evidence list.
9. SELF-SUFFICIENT: the reader will not open the links (they are in another language), so the post alone must say what happened: who, what, where, and the key number or consequence, using ONLY the texts. Give 3 items in "known" whenever the texts support them (never fewer than 2 unless the texts hold only one fact), and fill "context" whenever the texts allow. Limits: "known" at most 3 items, "differences" at most 2, "caveats" at most 2, each sentence at most 25 words.
Return JSON only, exactly in this schema:
{"category":"war|politics|economy|society|tech|science|health|environment|culture|sport|other",
 "region":"EXACTLY ONE of: Ukraine-Russia, Middle East, USA, EU, UK, Asia, Africa, Latin America, World. Any event involving Ukraine or Russia (including strikes, talks, sanctions, border incidents with Russia) is Ukraine-Russia. Use English only.",
 "same_event":true,"off_topic":[],
 "importance":1-10 (global significance, not number of outlets),
 "headline":{"uk":"","en":""},
 "context":{"uk":"","en":"","evidence":[{"id":"<outlet id>","quote":"<verbatim>"}]},
 "known":[{"uk":"","en":"","evidence":[{"id":"<outlet id>","quote":"<verbatim>"}]}],
 "differences":[{"uk":"","en":"","evidence":[{"id":"<outlet id>","quote":"<verbatim>"},{"id":"<other id>","quote":"<verbatim>"}]}],
 "outlets":[{"id":"<outlet id>","uk":"","en":"","quote":"<verbatim>"}],
 "caveats":{"uk":[""],"en":[""]}}"""


LANG_NOTE = {
    ("uk",): "OUTPUT LANGUAGE: write ONLY the Ukrainian (uk) fields; set every English (en) field to an empty string.",
    ("uk", "en"): "",
}
FOCUS_NOTE = ("CHANNEL FOCUS: this channel is 'Радар': what the world's leading outlets say ABOUT UKRAINE. Frame every post from that angle: "
              "the headline names what is happening regarding Ukraine; in \"outlets\" prefer outlets from DIFFERENT countries and for each describe that outlet's OWN angle "
              "(what it stresses, whom it quotes, how it frames Ukraine's position), not a repeat of the common facts. Include sceptical or critical framings when the texts contain them; "
              "never filter out unflattering views and never add praise. An outlet flagged state-funded is quoted as that outlet's/government's position, never as established fact. "
              "Mention the country of an outlet in the text only if it is needed to understand the view.")
BATCH_NOTE = ('The user message holds several independent events (EVENT 1, EVENT 2, ...). Treat each separately; never mix facts between events. '
              'Return {"events":[{"event":<number>, ...the schema above...}, ...]} with one object per event.')


BRIEF_NOTE = ('BRIEF MODE: for each event return only headline, category, region, importance, same_event, off_topic and exactly ONE item in "known" (the key fact, with evidence). '
              'Leave "differences", "outlets" and "caveats" empty and context empty.')


def build_batch_prompt(rs: list[Ranked], sources: dict[str, dict]) -> str:
    return "\n\n".join(f"=== EVENT {n} ===\n{build_prompt(r, sources)}" for n, r in enumerate(rs, 1))


def system_for(langs=("uk", "en"), batch: bool = False, brief: bool = False) -> str:
    return "\n".join(x for x in (SYSTEM, FOCUS_NOTE, LANG_NOTE.get(tuple(langs), ""), BRIEF_NOTE if brief else "", BATCH_NOTE if batch else "") if x)


def build_prompt(r: Ranked, sources: dict[str, dict]) -> str:
    lines = [f"Event cluster: {r.sources} outlets, latest item {r.cluster.latest:%Y-%m-%d %H:%M} UTC.", "Items:"]
    seen: set[str] = set()
    for it in sorted(r.cluster.items, key=lambda i: i.published, reverse=True):
        if it.source_id in seen:
            continue
        seen.add(it.source_id)
        src = sources.get(it.source_id, {})
        lines.append(f"- id={it.source_id} | outlet={it.source_name} | profile={label(src)} | published={it.published:%Y-%m-%d %H:%M} UTC")
        lines.append(f"  headline: {it.title}")
        if it.summary:
            lines.append(f"  snippet: {it.summary[:500]}")
    return "\n".join(lines)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
CATEGORIES = {"war", "politics", "economy", "society", "tech", "science", "health", "environment", "culture", "sport", "other"}
SOFT_CATS = {"culture", "sport"}
MIN_QUOTE = 12


class BadSynthesis(ValueError):
    def __init__(self, msg: str, off: tuple = ()):
        super().__init__(msg)
        self.off = tuple(off)  # видання, які модель вважає окремою подією (для розбиття кластера)


def _norm(t: str) -> str:
    return re.sub(r"[\W_]+", " ", t.lower().replace("’", "'")).strip()


def texts_for(r: Ranked) -> dict[str, str]:
    """Усі тексти (заголовки й анонси) кожного видання: проти них перевіряємо цитати моделі."""
    out: dict[str, str] = {}
    for it in r.cluster.items:
        out[it.source_id] = out.get(it.source_id, "") + " " + it.title + " " + it.summary
    return out


def _quote_ok(ev, texts_norm: dict[str, str]) -> str | None:
    if not isinstance(ev, dict):
        return None
    sid, q = ev.get("id"), _norm(str(ev.get("quote", "")))
    if sid in texts_norm and len(q) >= MIN_QUOTE and q in texts_norm[sid]:
        return sid
    return None


def _lst(v) -> list[str]:
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def _pair(d, key: str):
    d = d.get(key) if isinstance(d, dict) else None
    d = d if isinstance(d, dict) else {}
    return {l: _lst(d.get(l)) for l in ("uk", "en")}


def _text(d, key: str):
    d = d.get(key) if isinstance(d, dict) else None
    d = d if isinstance(d, dict) else {}
    return {l: str(d.get(l, "")).strip() for l in ("uk", "en")}


def parse_batch(raw: str, rs: list[Ranked], langs=("uk", "en")) -> list:
    """Для пакетної відповіді: список (parsed | BadSynthesis) у порядку подій."""
    try:
        data = json.loads(_FENCE.sub("", raw.strip()))
        evs = data["events"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise BadSynthesis(f"не пакет JSON: {e}") from e
    by_n = {}
    for pos, ev in enumerate(evs if isinstance(evs, list) else [], 1):
        if isinstance(ev, dict):
            try:
                by_n[int(ev.get("event", pos))] = ev
            except (TypeError, ValueError):
                by_n[pos] = ev
    out = []
    for n, r in enumerate(rs, 1):
        try:
            if n not in by_n:
                raise BadSynthesis("модель пропустила подію")
            out.append((parse_synthesis(json.dumps(by_n[n]), texts_for(r), langs), json.dumps(by_n[n], ensure_ascii=False)))
        except BadSynthesis as e:
            out.append((e, None))
    return out


def parse_synthesis(raw: str, texts: dict[str, str], langs=("uk", "en")) -> dict:
    """Розбирає й перевіряє відповідь моделі. Твердження без дослівної цитати з тексту видання відкидаються."""
    try:
        data = json.loads(_FENCE.sub("", raw.strip()))
    except json.JSONDecodeError as e:
        raise BadSynthesis(f"не JSON: {e}") from e
    if not isinstance(data, dict):
        raise BadSynthesis("очікувався JSON-об'єкт")
    off = {str(i) for i in (data.get("off_topic") or []) if str(i) in texts} if isinstance(data.get("off_topic"), list) else set()
    if data.get("same_event") is False or len(set(texts) - off) < min(2, len(texts)):
        raise BadSynthesis("кластер неоднорідний (різні події) або менше двох видань на головній події", sorted(off))
    hv = data.get("headline")
    if isinstance(hv, str) and hv.strip():  # деякі моделі повертають рядок замість {uk,en}
        data["headline"] = {"uk": hv.strip(), "en": ""}
    head = _text(data, "headline")
    if any(not head[l] for l in langs):
        raise BadSynthesis("немає заголовка однією з мов")
    texts = {k: v for k, v in texts.items() if k not in off}
    for l in langs:  # заголовок: без крапки, не задовгий, числа підтверджені текстами
        head[l] = head[l].rstrip(" .")
        if len(head[l]) > 110:
            raise BadSynthesis(f"заголовок задовгий ({len(head[l])} симв.)")
    alltext = " ".join(texts.values())
    nums = set(re.findall(r"\d+", alltext))
    for n in re.findall(r"\d+", head["uk"] + " " + head["en"]):
        if n not in nums:
            raise BadSynthesis(f"число {n} у заголовку не підтверджене текстами")
    tn = {k: _norm(v) for k, v in texts.items()}
    dropped = 0
    ctx = data.get("context")
    context = None
    if isinstance(ctx, dict) and all(str(ctx.get(l, "")).strip() for l in langs):
        if any(_quote_ok(e, tn) for e in (ctx.get("evidence") or [])):
            context = {l: str(ctx.get(l, "")).strip() for l in ("uk", "en")}
        else:
            dropped += 1

    def items(key: str):
        v = data.get(key)
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    known = []
    for k in items("known"):
        ids = {i for i in (_quote_ok(e, tn) for e in (k.get("evidence") or [])) if i}
        if not all(str(k.get(l, "")).strip() for l in langs) or not ids:
            dropped += 1
            continue
        known.append({"uk": str(k["uk"]).strip(), "en": str(k.get("en", "")).strip(), "by": next(iter(ids)) if len(ids) == 1 else None})
    diffs = []
    for k in items("differences"):
        ids = {i for i in (_quote_ok(e, tn) for e in (k.get("evidence") or [])) if i}
        if len(ids) < 2 or not all(str(k.get(l, "")).strip() for l in langs):
            dropped += 1
            continue
        diffs.append({"uk": str(k.get("uk", "")).strip(), "en": str(k.get("en", "")).strip()})
    outlets = []
    for o in items("outlets"):
        if _quote_ok({"id": o.get("id"), "quote": o.get("quote")}, tn) and str(o.get("uk", "")).strip():
            outlets.append({"id": o["id"], "uk": str(o["uk"]).strip(), "en": str(o.get("en", "")).strip()})
        else:
            dropped += 1
    try:
        imp = max(1, min(10, int(data.get("importance", 5))))
    except (TypeError, ValueError):
        imp = 5
    cat = str(data.get("category", "other")).lower()
    return {
        "category": cat if cat in CATEGORIES else "other",
        "region": norm_region(data.get("region", "World")),
        "importance": imp,
        "headline": head,
        "context": context,
        "known": known[:3],
        "differences": diffs[:2],
        "outlets": outlets[:5],
        "caveats": _pair(data, "caveats"),
        "off_topic": sorted(off),
        "dropped": dropped,
    }


REGIONS = {"ukraine-russia", "middle east", "usa", "eu", "uk", "asia", "africa", "latin america", "world"}


def norm_region(v: str) -> str:
    v = str(v).strip().lower()
    if v in REGIONS:
        return v
    if any(k in v for k in ("ukrain", "russia", "україн", "росі", "рос")):
        return "ukraine-russia"
    return "world"


# Аудиторія українська: Україна й безпека поруч важать більше, віддалені регіони менше (при однаковій оцінці важливості).
REGION_BONUS = {"ukraine-russia": 2.0, "eu": 0.8, "usa": 0.3, "uk": 0.0, "middle east": 0.0, "world": 0.0, "asia": -0.5, "africa": -0.7, "latin america": -0.7}


def select(synths: list[tuple[Ranked, dict]], top: int, max_per_region: int = 3, include_soft: bool = False, min_importance: int = 0) -> list[tuple[Ranked, dict]]:
    """Остаточний відбір: важливість від моделі, обмеження на регіон, культура/спорт — лише за прапором."""
    pool = [x for x in synths if (include_soft or x[1]["category"] not in SOFT_CATS) and x[1]["importance"] >= min_importance]
    # важливість за оцінкою моделі + охоплення (кількість видань, не більше 8): історії, які висвітлює багато видань, не губляться
    pool.sort(key=lambda x: (x[0].single_source, -(x[1]["importance"] + 0.6 * min(x[0].sources - len(x[1].get("off_topic", [])), 8) + REGION_BONUS.get(norm_region(x[1]["region"]), 0.0)), -x[0].score))
    from .state import similar_headlines
    out, per = [], {}
    for r, s in pool:
        reg = norm_region(s["region"])
        if per.get(reg, 0) >= max_per_region:
            continue
        if any(similar_headlines(s["headline"]["uk"] or s["headline"]["en"], o["headline"]["uk"] or o["headline"]["en"]) for _, o in out):
            continue  # той самий сюжет, оброблений як окрема подія
        per[reg] = per.get(reg, 0) + 1
        out.append((r, s))
        if len(out) >= top:
            break
    return out


DIGEST_SYSTEM = """You write the EVENING POST "What the world said about Ukraine today" for a Ukrainian channel, from the day's top stories (headlines and snippets of several foreign outlets each). Show the PICTURE of the day: what the world focused on, where outlets from different countries agree and where their angles differ.
Rules: use ONLY the provided texts; no new facts. Every point needs a short VERBATIM quote (at least 12 characters, exactly as in the text) from an outlet that supports it, with that outlet's id. Neutral wording, at most 22 words per point. Write Ukrainian only.
Return JSON only: {"headline":"<one line, Ukrainian>","points":[{"uk":"","evidence":[{"id":"<outlet id>","quote":"<verbatim>"}]}],"watch":"<one line about what to watch next, Ukrainian, or empty>"}
Give 4 to 6 points, one per distinct story, most important first. Prefer outlets from different countries across points, and in a point say whose angle it is when that is the point."""


def build_digest_prompt(rs: list[Ranked], sources: dict[str, dict]) -> str:
    return build_batch_prompt(rs, sources)


def parse_digest(raw: str, rs: list[Ranked]) -> dict:
    try:
        data = json.loads(_FENCE.sub("", raw.strip()))
    except json.JSONDecodeError as e:
        raise BadSynthesis(f"не JSON: {e}") from e
    if not isinstance(data, dict) or not str(data.get("headline", "")).strip():
        raise BadSynthesis("немає заголовка підсумку")
    tn: dict[str, str] = {}
    for r in rs:
        for k, v in texts_for(r).items():
            tn[k] = tn.get(k, "") + " " + _norm(v)
    pts = []
    for k in data.get("points") or []:
        if not isinstance(k, dict) or not str(k.get("uk", "")).strip():
            continue
        ids = [i for i in (_quote_ok(e, tn) for e in (k.get("evidence") or [])) if i]
        if ids:
            pts.append({"uk": str(k["uk"]).strip(), "by": ids[0]})
    if len(pts) < 3:
        raise BadSynthesis("замало підтверджених пунктів")
    return {"headline": str(data["headline"]).strip(), "points": pts[:6], "watch": str(data.get("watch", "")).strip()}
