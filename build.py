#!/usr/bin/env python3
"""Daily Brief. Builds a static news dashboard from RSS. No API keys, no server."""

import json
import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_AGE_HOURS = 36
MAX_PER_SECTION = 30
ARCHIVE_DAYS = 120

SECTIONS = {
    "Markets":       {"icon": "chart-line",     "blurb": "Sensex, rupee, gold",
                      "c": ["#E6F1FB", "#B5D4F4", "#042C53", "#185FA5", "#378ADD"]},
    "India business":{"icon": "building-store", "blurb": "Companies, deals",
                      "c": ["#EAF3DE", "#C0DD97", "#173404", "#3B6D11", "#639922"]},
    "Policy":        {"icon": "building-bank",  "blurb": "RBI, budget, tax",
                      "c": ["#FAEEDA", "#FAC775", "#412402", "#854F0B", "#EF9F27"]},
    "AI and tech":   {"icon": "cpu",            "blurb": "Models, gadgets",
                      "c": ["#EEEDFE", "#CECBF6", "#26215C", "#534AB7", "#7F77DD"]},
    "Startups":      {"icon": "rocket",         "blurb": "Funding, founders",
                      "c": ["#FBEAF0", "#F4C0D1", "#4B1528", "#993556", "#D4537E"]},
    "World":         {"icon": "world",          "blurb": "Global, politics",
                      "c": ["#E1F5EE", "#9FE1CB", "#04342C", "#0F6E56", "#1D9E75"]},
}

NUM_RE = re.compile(
    r"(?:(?:Rs\.?|₹|\$|US\$)\s?[\d,]+(?:\.\d+)?\s?"
    r"(?:lakh crore|trillion|billion|million|crore|lakh|bn|mn|cr|k)?"
    r"|[\d,]+(?:\.\d+)?\s?(?:per cent|percent|%)"
    r"|[\d,]+(?:\.\d+)?\s?(?:lakh crore|trillion|billion|crore)"
    r"|[\d,]+\s?(?:bps|basis points))",
    re.I)


def clean(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


STOP = {"said", "says", "after", "from", "with", "over", "into", "that", "this",
        "will", "than", "more", "amid", "ahead", "week", "next", "last", "year",
        "report", "reports", "could", "would", "here", "what", "make", "made"}


def tokens(title):
    t = re.sub(r"[^a-z0-9 ]", " ", (title or "").lower())
    return {w[:6] for w in t.split() if len(w) > 3 and w not in STOP}


def key_of(title):
    return " ".join(sorted(tokens(title))[:8])


def same_story(a, b):
    """Two headlines about the same event, worded differently."""
    if not a or not b:
        return False
    inter = len(a & b)
    return inter >= 3 and inter / min(len(a), len(b)) >= 0.6


def published(e):
    for k in ("published_parsed", "updated_parsed"):
        st = e.get(k)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def big_number(title, summary):
    """Pull the most quotable figure out of a story, if there is one."""
    for text in (title, summary):
        m = NUM_RE.search(text or "")
        if not m:
            continue
        val = re.sub(r"\s+", " ", m.group(0)).strip()
        val = (val.replace("per cent", "%").replace("percent", "%")
                  .replace("basis points", "bps").replace("Rs.", "₹")
                  .replace("Rs ", "₹").replace("crore", "cr")
                  .replace("trillion", "tn").replace("billion", "bn")
                  .replace("million", "mn"))
        if len(val) > 14:
            return None, ""
        after = (title or "")[m.end():].strip(" ,.")
        label = " ".join(after.split()[:3]) or " ".join((title or "").split()[:3])
        return val, label
    return None, ""


def pull(job):
    section, source, url = job
    try:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (daily-brief)")
    except Exception as exc:
        print(f"  fail  {source}: {exc}", file=sys.stderr)
        return section, source, []
    if getattr(feed, "bozo", 0) and not feed.entries:
        print(f"  fail  {source}: unreadable", file=sys.stderr)
        return section, source, []
    out = []
    for e in feed.entries[:30]:
        title, link = clean(e.get("title")), (e.get("link") or "").strip()
        if not title or not link:
            continue
        out.append({"title": title, "link": link, "source": source,
                    "section": section, "summary": clean(e.get("summary"))[:260],
                    "ts": published(e)})
    print(f"  ok    {source}: {len(out)}")
    return section, source, out


def collect(feeds):
    jobs = [(s, n, u) for s, lst in feeds.items() for n, u in lst]
    items, dead = [], []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for section, source, got in pool.map(pull, jobs):
            if not got:
                dead.append(source)
            items.extend(got)
    return items, dead


def group(items, first_seen, today):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    fresh = [i for i in items
             if not i["ts"] or (cutoff <= i["ts"] <= now + timedelta(hours=6))]

    links, keys, unique = set(), {}, []
    for it in sorted(fresh, key=lambda x: x["ts"] or now, reverse=True):
        if it["link"] in links:
            continue
        k = key_of(it["title"])
        tk = tokens(it["title"])
        hit = keys.get(k)
        if hit is None:
            for prev in unique:
                if prev["section"] == it["section"] and same_story(tk, prev["tok"]):
                    hit = prev
                    break
        if hit is not None:
            if it["source"] != hit["source"] and it["source"] not in hit["others"]:
                hit["others"].append(it["source"])
            links.add(it["link"])
            continue
        it["others"], it["key"], it["tok"] = [], k, tk
        links.add(it["link"])
        if k:
            keys[k] = it
        unique.append(it)

    for it in unique:
        k = it["key"]
        if k:
            first_seen.setdefault(k, today)
            d = (datetime.strptime(today, "%Y-%m-%d")
                 - datetime.strptime(first_seen[k], "%Y-%m-%d")).days
            it["days"] = d
        else:
            it["days"] = 0

    out = {s: [] for s in SECTIONS}
    for it in unique:
        b = out.setdefault(it["section"], [])
        if len(b) < MAX_PER_SECTION:
            b.append(it)
    return {k: v for k, v in out.items() if v}, len(unique)


def ago(ts, now):
    if not ts:
        return ""
    m = int((now - ts).total_seconds() // 60)
    if m < 60:
        return f"{max(m,1)}m"
    if m < 1440:
        return f"{m//60}h"
    return f"{m//1440}d"


def make_quiz(cards):
    """Five multiple-choice questions built from figures in today's headlines."""
    pool = [c for c in cards if c["n"] and len(c["t"]) > 30]
    seen, picks = set(), []
    for c in pool:
        if c["n"] in seen:
            continue
        seen.add(c["n"])
        picks.append(c)
        if len(picks) == 5:
            break
    if len(picks) < 3:
        return []
    allnums = [p["n"] for p in picks]
    quiz = []
    for i, c in enumerate(picks):
        sym = lambda v: v[0] if v and not v[0].isdigit() else ("%" if v.endswith("%") else "#")
        pref = [n for n in allnums if n != c["n"] and sym(n) == sym(c["n"])]
        rest = [n for n in allnums if n != c["n"] and n not in pref]
        wrong = (pref + rest)[:2]
        opts = [c["n"]] + wrong
        stem = c["t"]
        for frag in (c["n"], c["n"].replace("₹", "Rs ")):
            stem = stem.replace(frag, "____")
        quiz.append({"q": stem, "opts": opts, "a": c["n"],
                     "why": c["s"] + " · " + c["t"]})
    return quiz


def build_cards(grouped, now):
    cards = []
    for section, items in grouped.items():
        for it in items:
            n, nl = big_number(it["title"], it["summary"])
            others = sorted(set(it["others"]))
            cards.append({
                "sec": section, "t": it["title"], "p": it["summary"],
                "u": it["link"], "s": it["source"], "m": ago(it["ts"], now),
                "o": others[:4], "big": 1 if len(others) >= 2 else 0,
                "th": f"{it['days']} din se chal raha" if it["days"] >= 1 else "",
                "n": n or "", "nl": nl if n else "",
            })
    return cards


def main():
    feeds = json.loads((ROOT / "feeds.json").read_text())
    DOCS.mkdir(exist_ok=True)
    arch = DOCS / "archive"
    arch.mkdir(exist_ok=True)

    state_path = DOCS / "state.json"
    first_seen = {}
    if state_path.exists():
        try:
            first_seen = json.loads(state_path.read_text())
        except Exception:
            first_seen = {}

    now = datetime.now(timezone.utc)
    today = datetime.now(IST).strftime("%Y-%m-%d")

    print("Fetching feeds...")
    items, dead = collect(feeds)
    grouped, total = group(items, first_seen, today)
    cards = build_cards(grouped, now)
    quiz = make_quiz(cards)

    trending = sorted(
        [c for c in cards if c["o"]],
        key=lambda c: len(c["o"]), reverse=True)[:6]

    secs = [{"name": s, "icon": SECTIONS[s]["icon"], "blurb": SECTIONS[s]["blurb"],
             "c": SECTIONS[s]["c"], "n": len(v)}
            for s, v in grouped.items() if s in SECTIONS]

    payload = {"cards": cards, "secs": secs, "quiz": quiz,
               "trend": [{"t": c["t"], "n": len(c["o"]) + 1, "u": c["u"]}
                         for c in trending],
               "total": total}

    stamp = datetime.now(IST)
    page = render(payload, stamp, dead, "")
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    (arch / f"{today}.html").write_text(
        render(payload, stamp, dead, today), encoding="utf-8")

    dates = sorted((p.stem for p in arch.glob("*.html")
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)),
                   reverse=True)[:ARCHIVE_DAYS]
    (arch / "dates.json").write_text(json.dumps(dates), encoding="utf-8")
    keep = set(dates)
    for p in arch.glob("*.html"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem) and p.stem not in keep:
            p.unlink()

    cut = (datetime.now(IST) - timedelta(days=30)).strftime("%Y-%m-%d")
    first_seen = {k: v for k, v in first_seen.items() if v >= cut}
    state_path.write_text(json.dumps(first_seen), encoding="utf-8")

    print(f"\n{total} stories · {len(secs)} sections · {len(quiz)} quiz questions")
    print(f"archive: {len(dates)} day(s)")
    if dead:
        print(f"{len(dead)} feed(s) failed: {', '.join(sorted(set(dead)))}")


def render(payload, stamp, dead, archived_on):
    warn = f"{len(dead)} feeds did not respond" if dead else ""
    return TEMPLATE \
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False,
                                        separators=(",", ":"))) \
        .replace("__DATE__", stamp.strftime("%A, %-d %B")) \
        .replace("__UPDATED__", stamp.strftime("%-I:%M %p IST")) \
        .replace("__ARCHIVE__", archived_on) \
        .replace("__WARN__", html.escape(warn))


TEMPLATE = ""  # filled in by template.py at build time


if __name__ == "__main__":
    TEMPLATE = (ROOT / "template.html").read_text(encoding="utf-8")
    main()
