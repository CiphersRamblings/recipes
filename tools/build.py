#!/usr/bin/env python3
"""
build.py - turn recipes/*.json into a static website in site/.

    python tools/build.py
    python -m http.server -d site 8000     # then open http://localhost:8000

Standard library only.
"""
import hashlib
import html
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = ROOT / "recipes"
ASSETS_DIR = ROOT / "assets"
OUT = ROOT / "site"

e = lambda s: html.escape(str(s or ""), quote=True)

DIE = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
       'stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4"/>'
       + "".join(f'<circle cx="{x}" cy="{y}" r="1.4" fill="currentColor" stroke="none"/>'
                 for x, y in ((8, 8), (16, 8), (12, 12), (8, 16), (16, 16)))
       + "</svg>")


def load_config():
    cfg = {"title": "The Recipe Box", "tagline": "Good food, minus the life story."}
    p = ROOT / "site.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def load_recipes():
    recipes = []
    for p in sorted(RECIPES_DIR.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"! skipping {p.name}: {err}")
            continue
        r["slug"] = p.stem  # file name is the source of truth for the URL
        r.setdefault("tags", [])
        recipes.append(r)
    return sorted(recipes, key=lambda r: r.get("title", "").lower())


def hue(slug):
    return int(hashlib.md5(slug.encode()).hexdigest()[:4], 16) % 360


def serves(r):
    s = r.get("servings", "")
    return f"Serves {s}" if s.isdigit() else s


def meta_line(r):
    return " · ".join(x for x in (r.get("total_time") or r.get("cook_time"), serves(r)) if x)


def all_items(groups):
    return [i for g in groups or [] for i in g.get("items", [])]


def json_script(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def page(title, body, depth=0, desc=""):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
{f'<meta name="description" content="{e(desc)}">' if desc else ''}
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
{body}
</body>
</html>
"""


# ---------------------------------------------------------------- index

def card(r):
    initial = (r.get("title") or "?")[0].upper()
    thumb = (f'<img src="{e(r["image"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
             if r.get("image") else f"<span>{e(initial)}</span>")
    search = " ".join([r.get("title", ""), " ".join(r["tags"]), " ".join(all_items(r.get("ingredients")))]).lower()
    tags = "".join(f"<li>{e(t)}</li>" for t in r["tags"][:3])
    return f"""<a class="card" href="recipes/{e(r['slug'])}.html" style="--hue:{hue(r['slug'])}"
   data-title="{e(r.get('title'))}" data-tags="{e('|'.join(r['tags']))}" data-search="{e(search)}"
   data-meta="{e(meta_line(r))}" data-desc="{e(r.get('description'))}">
  <div class="thumb">{thumb}</div>
  <div class="card-body">
    <h2>{e(r.get('title'))}</h2>
    <p class="meta">{e(meta_line(r))}</p>
    <ul class="mini-tags">{tags}</ul>
  </div>
</a>"""


def build_index(recipes, cfg):
    counts = Counter(t for r in recipes for t in r["tags"])
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:24]
    chips = "".join(f'<button class="chip" data-tag="{e(t)}">{e(t)} <small>{n}</small></button>' for t, n in top)
    cards = "\n".join(card(r) for r in recipes)
    body = f"""<header class="masthead">
  <div class="wrap">
    <p class="eyebrow">{len(recipes)} recipes</p>
    <h1>{e(cfg['title'])}</h1>
    <p class="tagline">{e(cfg['tagline'])}</p>
    <button class="spin-btn" id="spin" type="button">{DIE}<span id="spin-label">What should I make?</span></button>
  </div>
</header>
<main class="wrap">
  <div class="controls">
    <input id="q" type="search" placeholder="Search recipes or ingredients…" aria-label="Search recipes" autocomplete="off">
    <div class="chips" id="chips"><button class="chip is-on" data-tag="">All</button>{chips}</div>
  </div>
  <p class="count" id="count" aria-live="polite"></p>
  <div class="grid" id="grid">
{cards}
  </div>
  <p class="empty" id="empty" hidden>Nothing matches that. Try another search or tag.</p>
</main>
<dialog id="picker" aria-labelledby="pick-title">
  <p class="eyebrow">Tonight you're making</p>
  <h2 id="pick-title">…</h2>
  <p id="pick-meta" class="meta"></p>
  <p id="pick-desc"></p>
  <div class="dialog-actions">
    <a id="pick-go" class="btn primary" href="#">Let's cook it →</a>
    <button id="pick-again" class="btn" type="button">Spin again</button>
    <button id="pick-close" class="btn ghost" type="button">Close</button>
  </div>
</dialog>
<footer class="site-foot wrap">Tip: press <kbd>R</kbd> to spin. The randomizer picks from whatever you've filtered to.</footer>
<script src="index.js"></script>"""
    (OUT / "index.html").write_text(page(cfg["title"], body), encoding="utf-8")


# ---------------------------------------------------------------- recipe pages

def groups_html(groups, kind):
    out = []
    for g in groups or []:
        if g.get("group"):
            out.append(f"<h3>{e(g['group'])}</h3>")
        if kind == "ingredients":
            items = "".join(f'<li><label><input type="checkbox"><span>{e(i)}</span></label></li>' for i in g["items"])
            out.append(f'<ul class="checklist">{items}</ul>')
        else:
            items = "".join(f"<li>{e(i)}</li>" for i in g["items"])
            out.append(f'<ol class="steps">{items}</ol>')
    return "\n".join(out)


def build_recipe(r, cfg):
    facts = "".join(f"<div><dt>{label}</dt><dd>{e(r[key])}</dd></div>"
                    for label, key in (("Prep", "prep_time"), ("Cook", "cook_time"),
                                       ("Total", "total_time"), ("Serves", "servings"))
                    if r.get(key))
    tags = "".join(f'<li><a href="../index.html#tag={e(t)}">{e(t)}</a></li>' for t in r["tags"])
    hero = (f'<figure class="hero"><img src="{e(r["image"])}" alt="" referrerpolicy="no-referrer"></figure>'
            if r.get("image") else "")
    notes = ""
    if r.get("notes"):
        notes = '<aside class="notes"><h2>Notes</h2><ul>' + "".join(f"<li>{e(n)}</li>" for n in r["notes"]) + "</ul></aside>"
    if r.get("source_url"):
        source = f'Adapted from <a href="{e(r["source_url"])}" rel="noopener">{e(r.get("source_name") or r["source_url"])}</a>'
    else:
        source = e(r.get("source_name") or "House recipe")
    added = f" · Added {e(r['added'])}" if r.get("added") else ""
    body = f"""<nav class="topbar wrap">
  <a href="../index.html">← All recipes</a>
  <a href="../random.html">{DIE} Random</a>
</nav>
<main class="wrap recipe">
  <article>
    <header class="recipe-head">
      <h1>{e(r.get('title'))}</h1>
      {f'<p class="lede">{e(r["description"])}</p>' if r.get('description') else ''}
      {f'<dl class="facts">{facts}</dl>' if facts else ''}
      {f'<ul class="tags">{tags}</ul>' if tags else ''}
    </header>
    {hero}
    <div class="cols">
      <section class="ingredients">
        <h2>Ingredients</h2>
        {groups_html(r.get('ingredients'), 'ingredients')}
      </section>
      <section class="method">
        <h2>Method</h2>
        {groups_html(r.get('steps'), 'steps')}
        <p class="hint">Tap a step to mark it done.</p>
      </section>
    </div>
    {notes}
    <footer class="source">{source}{added}</footer>
    <div class="tools">
      <button class="btn" id="wake" type="button" hidden>Keep screen on</button>
      <button class="btn" type="button" onclick="window.print()">Print</button>
    </div>
  </article>
</main>
<script src="../recipe.js"></script>"""
    path = OUT / "recipes" / f"{r['slug']}.html"
    path.write_text(page(f"{r.get('title')} · {cfg['title']}", body, depth=1, desc=r.get("description", "")),
                    encoding="utf-8")


def build_random(recipes):
    data = json_script([{"slug": r["slug"], "tags": r["tags"]} for r in recipes])
    body = f"""<p class="wrap" style="padding:40px 20px">Picking something…</p>
<script>
const R = {data};
const tag = new URLSearchParams(location.search).get("tag");
let pool = tag ? R.filter(r => r.tags.includes(tag)) : R;
if (!pool.length) pool = R;
if (pool.length) location.replace("recipes/" + pool[Math.floor(Math.random() * pool.length)].slug + ".html");
else document.body.textContent = "No recipes yet.";
</script>"""
    (OUT / "random.html").write_text(page("Random recipe", body), encoding="utf-8")


def main():
    cfg = load_config()
    recipes = load_recipes()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "recipes").mkdir(parents=True)
    for asset in ASSETS_DIR.iterdir():
        shutil.copy(asset, OUT / asset.name)
    build_index(recipes, cfg)
    for r in recipes:
        build_recipe(r, cfg)
    build_random(recipes)
    (OUT / "recipes.json").write_text(json.dumps(recipes, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Built {len(recipes)} recipes into {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
