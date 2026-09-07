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


def render(grouped, total, dead, archived_on=None):
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(IST)

    cards = []
    for section, items in grouped.items():
        for it in items:
            cards.append({
                "t": it["title"],
                "s": it["summary"],
                "u": it["link"],
                "src": it["source"],
                "sec": section,
                "ago": ago(it["ts"], now),
                "also": len(set(it["also"])),
            })

    sections = list(grouped.keys())
    payload = json.dumps({"cards": cards, "sections": sections},
                         ensure_ascii=False, separators=(",", ":"))

    warn = ""
    if dead:
        warn = (f"{len(dead)} feeds did not respond: "
                f"{', '.join(sorted(set(dead))[:5])}")

    return TEMPLATE.replace("__DATA__", payload) \
                   .replace("__DATE__", stamp.strftime("%A, %-d %B")) \
                   .replace("__UPDATED__", stamp.strftime("%-I:%M %p IST")) \
                   .replace("__TOTAL__", str(total)) \
                   .replace("__ARCHIVE__", archived_on or "") \
                   .replace("__WARN__", html.escape(warn))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#101215">
<title>Daily Brief</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#FAFBFC;--card:#FFFFFF;--ink:#14161A;--dim:#5A6270;
  --rule:#E3E6EA;--accent:#0F5C57;--soft:#E8F1F0;--shadow:rgba(20,22,26,.10);
}
@media(prefers-color-scheme:dark){
  :root{--bg:#0E1013;--card:#191D23;--ink:#E8EAED;--dim:#98A0AB;
        --rule:#272C34;--accent:#6FD3C7;--soft:#16302E;--shadow:rgba(0,0,0,.5);}
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:'IBM Plex Sans',system-ui,sans-serif;overflow:hidden;
  display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}

.top{padding:14px 18px 10px;flex:0 0 auto;max-width:680px;width:100%;margin:0 auto}
.brand{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
h1{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:1.5rem;
   margin:0;letter-spacing:-.02em}
.when{font-size:.72rem;color:var(--dim);text-align:right;line-height:1.35}
.dateBtn{border:1px solid var(--rule);background:var(--card);color:var(--ink);
  font-family:inherit;font-size:.72rem;font-weight:600;padding:5px 11px;
  border-radius:99px;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.dateBtn:hover{border-color:var(--accent);color:var(--accent)}
.sheet{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:20;
  display:none;align-items:flex-end;justify-content:center}
.sheet.on{display:flex}
.sheetIn{background:var(--card);width:100%;max-width:480px;
  border-radius:18px 18px 0 0;padding:20px 18px calc(22px + env(safe-area-inset-bottom));
  max-height:70vh;overflow-y:auto}
.sheetIn h3{font-family:Newsreader,serif;font-weight:500;font-size:1.15rem;
  margin:0 0 4px}
.sheetIn p{color:var(--dim);font-size:.76rem;margin:0 0 14px}
.dates{display:flex;flex-direction:column;gap:2px}
.dRow{display:flex;justify-content:space-between;align-items:center;
  padding:11px 12px;border-radius:10px;text-decoration:none;color:var(--ink);
  font-size:.87rem;border:1px solid transparent}
.dRow:hover{background:var(--soft);border-color:var(--rule)}
.dRow.cur{background:var(--soft);color:var(--accent);font-weight:600}
.dRow span{font-size:.72rem;color:var(--dim)}
.closeS{width:100%;margin-top:14px;padding:10px;border-radius:99px;
  border:1px solid var(--rule);background:transparent;color:var(--dim);
  font-family:inherit;font-size:.82rem;cursor:pointer}
.arch{background:var(--soft);color:var(--accent);text-align:center;
  padding:7px 14px;font-size:.75rem;font-weight:600}
.arch a{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
.bar{height:3px;background:var(--rule);border-radius:99px;margin-top:12px;overflow:hidden}
.fill{height:100%;width:0;background:var(--accent);border-radius:99px;
      transition:width .25s ease}
.tabs{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;
      margin-top:11px;padding-bottom:2px}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;padding:5px 11px;border:1px solid var(--rule);
     border-radius:99px;background:var(--card);color:var(--dim);
     font-size:.74rem;font-weight:500;cursor:pointer;white-space:nowrap;
     font-family:inherit}
.tab[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);
     color:var(--bg)}

.stage{flex:1 1 auto;position:relative;display:flex;align-items:center;
       justify-content:center;padding:6px 18px 0;min-height:0}
.deck{position:relative;width:100%;max-width:620px;height:100%;max-height:560px}
.c{position:absolute;inset:0;background:var(--card);border:1px solid var(--rule);
   border-radius:20px;padding:26px 24px;display:flex;flex-direction:column;
   box-shadow:0 8px 28px var(--shadow);will-change:transform,opacity;
   overflow:hidden}
.c.behind{transform:scale(.955) translateY(14px);opacity:.55;
          box-shadow:0 4px 14px var(--shadow)}
.c.behind2{transform:scale(.915) translateY(27px);opacity:.28;box-shadow:none}
.c.gone{transition:transform .3s cubic-bezier(.4,0,.2,1),opacity .3s}
.badge{display:inline-flex;align-self:flex-start;gap:7px;align-items:center;
  background:var(--soft);color:var(--accent);padding:3px 10px;border-radius:99px;
  font-size:.68rem;font-weight:600;margin-bottom:14px}
.hl{font-family:Newsreader,Georgia,serif;font-weight:500;
    font-size:clamp(1.25rem,4.4vw,1.7rem);line-height:1.24;letter-spacing:-.015em;
    margin:0;color:var(--ink);text-decoration:none;display:block}
.hl:hover{color:var(--accent)}
.sum{color:var(--dim);font-size:.9rem;line-height:1.55;margin:13px 0 0;
     overflow-y:auto;flex:1 1 auto;min-height:0}
.foot{display:flex;align-items:center;gap:10px;margin-top:16px;
      padding-top:13px;border-top:1px solid var(--rule);flex:0 0 auto}
.src{font-size:.76rem;font-weight:600}
.time{font-size:.74rem;color:var(--dim);font-variant-numeric:tabular-nums}
.also{font-size:.68rem;color:var(--accent);background:var(--soft);
      padding:2px 8px;border-radius:99px;font-weight:600}
.open{margin-left:auto;font-size:.75rem;font-weight:600;color:var(--accent);
      text-decoration:none;border:1px solid var(--accent);padding:5px 13px;
      border-radius:99px}

.bottom{flex:0 0 auto;padding:14px 18px calc(16px + env(safe-area-inset-bottom));
        max-width:620px;width:100%;margin:0 auto}
.ctrls{display:flex;align-items:center;gap:12px}
.nav{flex:0 0 auto;width:46px;height:46px;border-radius:50%;
     border:1px solid var(--rule);background:var(--card);color:var(--ink);
     font-size:1.15rem;cursor:pointer;display:grid;place-items:center;
     font-family:inherit}
.nav:disabled{opacity:.3;cursor:default}
.nav:active:not(:disabled){transform:scale(.93)}
.count{flex:1 1 auto;text-align:center;font-size:.78rem;color:var(--dim);
       font-variant-numeric:tabular-nums}
.count b{color:var(--ink);font-weight:600}
.hint{text-align:center;font-size:.68rem;color:var(--dim);margin-top:9px;
      opacity:.65}
.done{position:absolute;inset:0;display:none;flex-direction:column;
      align-items:center;justify-content:center;text-align:center;gap:14px;
      padding:30px}
.done.on{display:flex}
.done h2{font-family:Newsreader,serif;font-weight:500;font-size:1.6rem;margin:0}
.done p{color:var(--dim);font-size:.87rem;margin:0;max-width:34ch;line-height:1.5}
.again{padding:9px 20px;border-radius:99px;border:1px solid var(--accent);
       background:transparent;color:var(--accent);font-weight:600;
       font-size:.82rem;cursor:pointer;font-family:inherit}
button:focus-visible,a:focus-visible,.tab:focus-visible{
  outline:2px solid var(--accent);outline-offset:3px}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>

<div id="archBar"></div>
<div class="top">
  <div class="brand">
    <h1>Daily Brief</h1>
    <div class="when">__DATE__<br>updated __UPDATED__</div>
  </div>
  <div style="margin-top:10px"><button class="dateBtn" id="dateBtn">&#128197; Purani news</button></div>
  <div class="bar"><div class="fill" id="fill"></div></div>
  <div class="tabs" id="tabs"></div>
</div>

<div class="stage">
  <div class="deck" id="deck"></div>
  <div class="done" id="done">
    <h2>Ho gaya</h2>
    <p id="doneMsg"></p>
    <button class="again" id="again">Phir se dekho</button>
  </div>
</div>

<div class="sheet" id="sheet">
  <div class="sheetIn">
    <h3>Purani news</h3>
    <p>Kisi bhi din pe tap karo</p>
    <div class="dates" id="dates">Loading...</div>
    <button class="closeS" id="closeS">Band karo</button>
  </div>
</div>

<div class="bottom">
  <div class="ctrls">
    <button class="nav" id="prev" aria-label="Previous">&#8592;</button>
    <div class="count"><b id="pos">0</b> / <span id="tot">0</span></div>
    <button class="nav" id="next" aria-label="Next">&#8594;</button>
  </div>
  <div class="hint">Swipe karo ya arrow keys dabao &nbsp;·&nbsp; card pe tap = article khulega</div>
</div>

<script>
const DATA = __DATA__;
const WARN = "__WARN__";

let filter = "all", idx = 0, deck = [];
const $ = id => document.getElementById(id);

const seen = (() => {
  try { return new Set(JSON.parse(localStorage.getItem("db_seen") || "[]")); }
  catch { return new Set(); }
})();
const saveSeen = () => {
  try { localStorage.setItem("db_seen", JSON.stringify([...seen].slice(-1200))); }
  catch {}
};

function esc(s){ const d=document.createElement("div"); d.textContent=s||""; return d.innerHTML; }

function buildTabs(){
  const t = $("tabs");
  const mk = (label, val, n) => {
    const b = document.createElement("button");
    b.className = "tab"; b.textContent = label + " " + n;
    b.setAttribute("aria-pressed", String(filter === val));
    b.onclick = () => { filter = val; idx = 0; buildTabs(); load(); };
    return b;
  };
  t.innerHTML = "";
  t.appendChild(mk("All", "all", DATA.cards.length));
  DATA.sections.forEach(s => {
    const n = DATA.cards.filter(c => c.sec === s).length;
    if (n) t.appendChild(mk(s, s, n));
  });
}

function load(){
  deck = filter === "all" ? DATA.cards.slice()
                          : DATA.cards.filter(c => c.sec === filter);
  const fresh = deck.filter(c => !seen.has(c.u));
  if (fresh.length) deck = fresh.concat(deck.filter(c => seen.has(c.u)));
  $("tot").textContent = deck.length;
  render();
}

function card(c, cls){
  const el = document.createElement("article");
  el.className = "c " + cls;
  el.innerHTML =
    '<span class="badge">' + esc(c.sec) + '</span>' +
    '<a class="hl" href="' + esc(c.u) + '" target="_blank" rel="noopener">' + esc(c.t) + '</a>' +
    (c.s ? '<p class="sum">' + esc(c.s) + '</p>' : '<div class="sum"></div>') +
    '<div class="foot"><span class="src">' + esc(c.src) + '</span>' +
    '<span class="time">' + esc(c.ago) + '</span>' +
    (c.also ? '<span class="also">+' + c.also + ' more</span>' : '') +
    '<a class="open" href="' + esc(c.u) + '" target="_blank" rel="noopener">Read</a></div>';
  return el;
}

function render(){
  const d = $("deck");
  d.innerHTML = "";
  $("done").classList.toggle("on", idx >= deck.length);
  if (idx >= deck.length){
    $("doneMsg").textContent = deck.length
      ? deck.length + " stories padh li. Agla update aane pe nayi aayengi."
      : "Is section mein abhi kuch nahi hai.";
    $("pos").textContent = deck.length;
    $("fill").style.width = "100%";
    $("prev").disabled = idx === 0; $("next").disabled = true;
    return;
  }
  for (let i = Math.min(idx + 2, deck.length - 1); i >= idx; i--){
    const cls = i === idx ? "" : (i === idx + 1 ? "behind" : "behind2");
    d.appendChild(card(deck[i], cls));
  }
  $("pos").textContent = idx + 1;
  $("fill").style.width = ((idx) / deck.length * 100) + "%";
  $("prev").disabled = idx === 0;
  $("next").disabled = false;
  swipe(d.lastElementChild);
}

function go(step){
  if (step > 0 && idx < deck.length){
    seen.add(deck[idx].u); saveSeen();
  }
  idx = Math.max(0, Math.min(deck.length, idx + step));
  render();
}

function fly(el, dir, after){
  el.classList.add("gone");
  el.style.transform = "translateX(" + (dir * 130) + "%) rotate(" + (dir * 9) + "deg)";
  el.style.opacity = "0";
  setTimeout(after, 220);
}

function swipe(el){
  if (!el) return;
  let x0 = null, y0 = null, dx = 0, moved = false;
  el.addEventListener("touchstart", e => {
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; moved = false;
  }, {passive:true});
  el.addEventListener("touchmove", e => {
    if (x0 === null) return;
    dx = e.touches[0].clientX - x0;
    const dy = e.touches[0].clientY - y0;
    if (Math.abs(dx) < Math.abs(dy)) return;
    moved = true;
    el.style.transform = "translateX(" + dx + "px) rotate(" + (dx/26) + "deg)";
    el.style.opacity = String(1 - Math.abs(dx)/460);
  }, {passive:true});
  el.addEventListener("touchend", () => {
    if (x0 === null) return;
    if (moved && Math.abs(dx) > 72){
      fly(el, dx > 0 ? 1 : -1, () => go(dx > 0 ? -1 : 1));
    } else {
      el.style.transition = "transform .2s, opacity .2s";
      el.style.transform = ""; el.style.opacity = "";
      setTimeout(() => el.style.transition = "", 200);
    }
    x0 = null; dx = 0;
  });
}

$("next").onclick = () => { const t = $("deck").lastElementChild;
  t ? fly(t, -1, () => go(1)) : go(1); };
$("prev").onclick = () => go(-1);
$("again").onclick = () => { idx = 0; render(); };

addEventListener("keydown", e => {
  if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); $("next").click(); }
  if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
  if (e.key === "Enter" && idx < deck.length) window.open(deck[idx].u, "_blank");
});

const ARCHIVED = "__ARCHIVE__";
const BASE = ARCHIVED ? "./" : "./archive/";

if (ARCHIVED){
  $("archBar").className = "arch";
  $("archBar").innerHTML = "Purani news &#183; " + ARCHIVED +
    ' &nbsp;<a href="../index.html">Aaj ki news dekho</a>';
}

function fmtDate(s){
  const d = new Date(s + "T00:00:00");
  return d.toLocaleDateString("en-IN",
    {weekday:"long", day:"numeric", month:"long"});
}

function relDay(s){
  const t = new Date(); t.setHours(0,0,0,0);
  const d = new Date(s + "T00:00:00");
  const n = Math.round((t - d) / 86400000);
  if (n === 0) return "Aaj";
  if (n === 1) return "Kal";
  return n + " din pehle";
}

let datesLoaded = false;
async function openSheet(){
  $("sheet").classList.add("on");
  if (datesLoaded) return;
  const box = $("dates");
  try {
    const r = await fetch(BASE + "dates.json", {cache:"no-store"});
    const list = await r.json();
    if (!list.length){ box.textContent = "Abhi koi purana din nahi hai."; return; }
    box.innerHTML = "";
    list.forEach(d => {
      const a = document.createElement("a");
      a.className = "dRow" + (d === ARCHIVED ? " cur" : "");
      a.href = (ARCHIVED ? "./" : "./archive/") + d + ".html";
      a.innerHTML = fmtDate(d) + "<span>" + relDay(d) + "</span>";
      box.appendChild(a);
    });
    datesLoaded = true;
  } catch {
    box.textContent = "Archive abhi nahi bana. Kal se dikhega.";
  }
}

$("dateBtn").onclick = openSheet;
$("closeS").onclick = () => $("sheet").classList.remove("on");
$("sheet").onclick = e => { if (e.target === $("sheet")) $("sheet").classList.remove("on"); };
addEventListener("keydown", e => {
  if (e.key === "Escape") $("sheet").classList.remove("on");
});

buildTabs();
load();
if (WARN) console.warn(WARN);
</script>
</body>
</html>
"""


def main():
    feeds = json.loads((ROOT / "feeds.json").read_text())
    print("Fetching feeds...")
    items, dead = collect(feeds)
    grouped, total = filter_and_group(items, list(feeds))

    docs = ROOT / "docs"
    arch = docs / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    today = datetime.now(IST).strftime("%Y-%m-%d")

    # Live page
    (docs / "index.html").write_text(
        render(grouped, total, dead), encoding="utf-8")

    # Dated snapshot (overwritten by the later run on the same day)
    (arch / f"{today}.html").write_text(
        render(grouped, total, dead, archived_on=today), encoding="utf-8")

    # Index of available dates, newest first
    dates = sorted(
        (p.stem for p in arch.glob("*.html")
         if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)),
        reverse=True)[:120]
    (arch / "dates.json").write_text(json.dumps(dates), encoding="utf-8")

    # Prune snapshots older than the 120 we keep
    keep = set(dates)
    for p in arch.glob("*.html"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem) and p.stem not in keep:
            p.unlink()

    print(f"\n{total} stories, {len(grouped)} sections")
    print(f"archive: {len(dates)} day(s) available")
    if dead:
        print(f"{len(dead)} feed(s) failed: {', '.join(sorted(set(dead)))}")


if __name__ == "__main__":
    main()
