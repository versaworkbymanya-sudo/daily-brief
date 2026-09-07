#!/usr/bin/env python3
"""Builds a static news dashboard from RSS feeds. No API keys, no server."""

import json
import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).parent
IST = timezone(timedelta(hours=5, minutes=30))
MAX_AGE_HOURS = 36
MAX_PER_SECTION = 22
TIMEOUT = 20


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalise(title):
    """Key for spotting the same story filed by several outlets."""
    t = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    words = [w for w in t.split() if len(w) > 3]
    return " ".join(sorted(words)[:8])


def published(entry):
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def pull(job):
    section, source, url = job
    try:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (news-dashboard)")
    except Exception as exc:
        print(f"  fail  {source}: {exc}", file=sys.stderr)
        return section, source, []
    if getattr(feed, "bozo", 0) and not feed.entries:
        print(f"  fail  {source}: unreadable feed", file=sys.stderr)
        return section, source, []

    out = []
    for e in feed.entries[:30]:
        title = clean(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        out.append({
            "title": title,
            "link": link,
            "source": source,
            "section": section,
            "summary": clean(e.get("summary"))[:220],
            "ts": published(e),
        })
    print(f"  ok    {source}: {len(out)}")
    return section, source, out


def collect(feeds):
    jobs = [(sec, name, url) for sec, lst in feeds.items() for name, url in lst]
    items, dead = [], []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for section, source, got in pool.map(pull, jobs):
            if not got:
                dead.append(source)
            items.extend(got)
    return items, dead


def filter_and_group(items, sections):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)

    fresh = []
    for it in items:
        if it["ts"] and it["ts"] < cutoff:
            continue
        if it["ts"] and it["ts"] > now + timedelta(hours=6):
            continue
        fresh.append(it)

    seen_links, seen_titles = set(), {}
    unique = []
    for it in sorted(fresh, key=lambda x: x["ts"] or now, reverse=True):
        if it["link"] in seen_links:
            continue
        key = normalise(it["title"])
        if key and key in seen_titles:
            seen_titles[key]["also"].append(it["source"])
            continue
        it["also"] = []
        seen_links.add(it["link"])
        if key:
            seen_titles[key] = it
        unique.append(it)

    grouped = {s: [] for s in sections}
    for it in unique:
        bucket = grouped.setdefault(it["section"], [])
        if len(bucket) < MAX_PER_SECTION:
            bucket.append(it)
    return {k: v for k, v in grouped.items() if v}, len(unique)


def ago(ts, now):
    if not ts:
        return ""
    mins = int((now - ts).total_seconds() // 60)
    if mins < 1:
        return "now"
    if mins < 60:
        return f"{mins}m"
    if mins < 1440:
        return f"{mins // 60}h"
    return f"{mins // 1440}d"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render(grouped, total, dead):
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(IST)

    nav = "".join(
        f'<a class="chip" href="#{slug(s)}">{html.escape(s)}'
        f'<span class="chip-n">{len(v)}</span></a>'
        for s, v in grouped.items()
    )

    blocks = []
    for section, items in grouped.items():
        rows = []
        for it in items:
            also = ""
            if it["also"]:
                n = len(set(it["also"]))
                also = f'<span class="also">+{n} more</span>'
            summary = (
                f'<p class="sum">{html.escape(it["summary"])}</p>'
                if it["summary"] else ""
            )
            rows.append(
                f'<li class="item">'
                f'<a class="hl" href="{html.escape(it["link"])}" target="_blank" '
                f'rel="noopener">{html.escape(it["title"])}</a>'
                f'{summary}'
                f'<div class="meta"><span class="src">{html.escape(it["source"])}</span>'
                f'<span class="time">{ago(it["ts"], now)}</span>{also}</div>'
                f'</li>'
            )
        blocks.append(
            f'<section id="{slug(section)}" class="sec">'
            f'<h2 class="sec-h">{html.escape(section)}'
            f'<span class="sec-n">{len(items)}</span></h2>'
            f'<ul class="list">{"".join(rows)}</ul></section>'
        )

    warn = ""
    if dead:
        warn = (
            f'<p class="warn">{len(dead)} feed(s) did not respond: '
            f'{html.escape(", ".join(sorted(set(dead))[:6]))}</p>'
        )

    return TEMPLATE.format(
        date=stamp.strftime("%A, %-d %B %Y"),
        updated=stamp.strftime("%-I:%M %p IST"),
        total=total,
        nav=nav,
        blocks="".join(blocks),
        warn=warn,
        year=stamp.year,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Daily Brief</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#FAFBFC; --panel:#FFFFFF; --ink:#14161A; --dim:#5A6270;
    --rule:#E3E6EA; --accent:#0F5C57; --accent-soft:#E8F1F0;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:#101215; --panel:#171A1F; --ink:#E8EAED; --dim:#949BA6;
      --rule:#262A31; --accent:#6FD3C7; --accent-soft:#16302E;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:'IBM Plex Sans',system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  .wrap {{ max-width:760px; margin:0 auto; padding:0 20px 80px; }}
  header {{ padding:44px 0 20px; }}
  h1 {{
    font-family:Newsreader,Georgia,serif; font-weight:500;
    font-size:clamp(2.1rem,7vw,3rem); letter-spacing:-.02em;
    margin:0 0 6px; line-height:1.05;
  }}
  .sub {{ color:var(--dim); font-size:.86rem; margin:0; }}
  .sub b {{ color:var(--ink); font-weight:600; }}
  nav {{
    position:sticky; top:0; z-index:5; background:var(--bg);
    padding:12px 0; margin-bottom:8px;
    border-bottom:1px solid var(--rule);
    display:flex; gap:7px; overflow-x:auto; scrollbar-width:none;
  }}
  nav::-webkit-scrollbar {{ display:none; }}
  .chip {{
    flex:0 0 auto; display:flex; align-items:center; gap:6px;
    padding:6px 12px; border:1px solid var(--rule); border-radius:999px;
    color:var(--ink); text-decoration:none; font-size:.8rem; font-weight:500;
    background:var(--panel); white-space:nowrap;
  }}
  .chip:hover {{ border-color:var(--accent); color:var(--accent); }}
  .chip-n {{ color:var(--dim); font-size:.72rem; }}
  .sec {{ padding-top:34px; }}
  .sec-h {{
    font-family:Newsreader,Georgia,serif; font-weight:600; font-size:1.32rem;
    margin:0 0 2px; display:flex; align-items:baseline; gap:9px;
    letter-spacing:-.01em;
  }}
  .sec-n {{ font-family:'IBM Plex Sans',sans-serif; font-size:.72rem;
            font-weight:500; color:var(--dim); }}
  .list {{ list-style:none; margin:0; padding:0;
           border-top:2px solid var(--ink); }}
  .item {{ padding:15px 0 14px; border-bottom:1px solid var(--rule); }}
  .hl {{
    color:var(--ink); text-decoration:none; font-size:1.03rem;
    font-weight:500; line-height:1.38; display:block;
  }}
  .hl:hover {{ color:var(--accent); text-decoration:underline;
               text-underline-offset:3px; }}
  .sum {{ color:var(--dim); font-size:.85rem; line-height:1.5;
          margin:5px 0 0; }}
  .meta {{ display:flex; align-items:center; gap:9px; margin-top:7px;
           font-size:.75rem; color:var(--dim); }}
  .src {{ font-weight:500; color:var(--ink); opacity:.75; }}
  .time {{ font-variant-numeric:tabular-nums; }}
  .also {{ background:var(--accent-soft); color:var(--accent);
           padding:1px 7px; border-radius:999px; font-size:.7rem;
           font-weight:500; }}
  .warn {{ margin-top:40px; padding:11px 14px; background:var(--panel);
           border:1px solid var(--rule); border-radius:8px;
           color:var(--dim); font-size:.78rem; }}
  footer {{ margin-top:46px; padding-top:18px;
            border-top:1px solid var(--rule);
            color:var(--dim); font-size:.76rem; }}
  a:focus-visible, .chip:focus-visible {{
    outline:2px solid var(--accent); outline-offset:3px; border-radius:3px;
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Daily Brief</h1>
    <p class="sub">{date} &nbsp;·&nbsp; <b>{total}</b> stories &nbsp;·&nbsp; updated {updated}</p>
  </header>
  <nav>{nav}</nav>
  {blocks}
  {warn}
  <footer>Rebuilt automatically every morning. Headlines link to the original publisher.</footer>
</div>
</body>
</html>
"""


def main():
    feeds = json.loads((ROOT / "feeds.json").read_text())
    print("Fetching feeds...")
    items, dead = collect(feeds)
    grouped, total = filter_and_group(items, list(feeds))
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(grouped, total, dead), encoding="utf-8")
    print(f"\n{total} stories across {len(grouped)} sections -> {out}")
    if dead:
        print(f"{len(dead)} feed(s) failed: {', '.join(sorted(set(dead)))}")


if __name__ == "__main__":
    main()
