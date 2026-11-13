#!/usr/bin/env python3
"""
add_recipe.py - turn a recipe web page into a clean JSON file in recipes/.

    python tools/add_recipe.py https://example.com/some-recipe
    python tools/add_recipe.py URL1 URL2 URL3 --build
    python tools/add_recipe.py --list urls.txt
    python tools/add_recipe.py --file saved-page.html --url https://example.com/some-recipe
    python tools/add_recipe.py --text grandmas-chili.txt

With ANTHROPIC_API_KEY set, Claude reads the recipe, throws away the life story,
ads and SEO filler, and returns tidy structured data.
Without a key (or with --no-ai) the script uses the structured recipe data most
recipe sites embed in the page (schema.org JSON-LD) and formats that directly.

Standard library only - no pip installs needed.
"""
import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = ROOT / "recipes"
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("RECIPE_MODEL", "claude-haiku-5-5")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SYSTEM_PROMPT = """You convert recipe web pages into clean, structured data for a personal recipe website.

Rules:
- Remove everything that is not the recipe: life stories, SEO filler, ads, "jump to recipe", ratings, comments, affiliate plugs, nutrition marketing.
- Keep EVERY ingredient, with its exact quantity and unit. Do not change amounts.
- Steps: clear, concise, imperative sentences. Keep every temperature, time, pan size and doneness cue. Do not number them. Merge fragments; split steps that do several unrelated things.
- If the recipe has components (e.g. "For the sauce", "For the dough"), group ingredients and steps under those names. Otherwise use a single group with an empty name.
- description: ONE short sentence, in your own words, saying what the dish is.
- tags: 3 to 6 lowercase tags drawn from meal type (breakfast, lunch, dinner, dessert, snack, side), main ingredient (chicken, beef, pasta...), cuisine (mexican, italian...), and diet (vegetarian, vegan, gluten-free) when clearly true. Also "quick" if total time is 30 min or less.
- notes: only genuinely useful tips from the page (substitutions, storage, make-ahead, equipment). Max 4, each one sentence. Empty list if none.
- Times like "15 min" or "1 hr 20 min". Use "" when unknown.
- servings like "4" or "12 cookies". Use "" when unknown.
- If the content is not a recipe, return {"error": "short reason"}.

Return ONLY a JSON object, no prose, no code fences, in exactly this shape:
{
  "title": "",
  "description": "",
  "servings": "",
  "prep_time": "",
  "cook_time": "",
  "total_time": "",
  "tags": [],
  "ingredients": [{"group": "", "items": [""]}],
  "steps": [{"group": "", "items": [""]}],
  "notes": []
}"""


# ---------------------------------------------------------------- fetching / parsing

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")


class PageParser(HTMLParser):
    """Collects JSON-LD blocks, <meta> tags and the page's visible text."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "aside",
            "form", "iframe", "button", "select"}
    BREAKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "br", "div", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld, self.text, self.meta = [], [], {}
        self._in_ld, self._buf, self._skip = False, [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").strip().lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
            return
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BREAKS:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.jsonld.append("".join(self._buf))
            return
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif not self._skip:
            self.text.append(data)

    def visible_text(self, limit=40000):
        t = "".join(self.text)
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t)
        return t.strip()[:limit]


def types_of(node):
    t = node.get("@type") if isinstance(node, dict) else None
    return t if isinstance(t, list) else [t]


def find_recipe(node):
    """Walk JSON-LD (lists, @graph, mainEntity...) and return the first Recipe."""
    if isinstance(node, list):
        for n in node:
            found = find_recipe(n)
            if found:
                return found
    elif isinstance(node, dict):
        if "Recipe" in types_of(node):
            return node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found = find_recipe(node[key])
                if found:
                    return found
    return None


def recipe_from_jsonld(blocks):
    for raw in blocks:
        try:
            data = json.loads(raw.strip(), strict=False)
        except json.JSONDecodeError:
            continue
        found = find_recipe(data)
        if found:
            return found
    return None


# ---------------------------------------------------------------- normalising

def clean_text(s):
    if s is None:
        return ""
    s = html.unescape(html.unescape(str(s)))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"\s+([,.;:!?)])", r"\1", s).strip()


def iso_duration(v):
    """PT1H30M -> '1 hr 30 min'. Leaves already-readable text alone."""
    if not v:
        return ""
    v = str(v).strip()
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:([\d.]+)H)?(?:([\d.]+)M)?(?:([\d.]+)S)?)?", v, re.I)
    if not m:
        return clean_text(v)
    d, h, mi, _ = m.groups()
    total = int(round(int(d or 0) * 1440 + float(h or 0) * 60 + float(mi or 0)))
    if total <= 0:
        return ""
    hrs, mins = divmod(total, 60)
    return " ".join(p for p in (f"{hrs} hr" if hrs else "", f"{mins} min" if mins else "") if p)


def pick_image(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        for x in v:
            found = pick_image(x)
            if found:
                return found
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl") or ""
    return ""


def pick_yield(v):
    if isinstance(v, list):
        vals = [clean_text(x) for x in v if clean_text(x)]
        for x in vals:  # prefer "4 servings" over "4"
            if re.search(r"[a-zA-Z]", x):
                return x
        return vals[0] if vals else ""
    return clean_text(v)


def to_list(v):
    if not v:
        return []
    if isinstance(v, str):
        return re.split(r"[,;]", v)
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(to_list(x))
        return out
    if isinstance(v, dict):
        return [v.get("name", "")]
    return [str(v)]


def make_tags(*values, limit=8):
    tags = []
    for v in values:
        for t in to_list(v):
            t = clean_text(t).lower()
            if t and len(t) <= 30 and t not in tags:
                tags.append(t)
    return tags[:limit]


STEP_PREFIX = re.compile(r"^(step\s*)?\d+\s*[.):-]?\s+", re.I)


def parse_steps(node):
    groups = [{"group": "", "items": []}]

    def add_text(text, group):
        text = re.sub(r"(?i)<\s*(br|/p|/li)[^>]*>", "\n", text)
        for line in text.split("\n"):
            line = STEP_PREFIX.sub("", clean_text(line))
            if line:
                group["items"].append(line)

    def walk(n, group):
        if isinstance(n, str):
            add_text(n, group)
        elif isinstance(n, list):
            for x in n:
                walk(x, group)
        elif isinstance(n, dict):
            if "HowToSection" in types_of(n):
                g = {"group": clean_text(n.get("name")), "items": []}
                groups.append(g)
                walk(n.get("itemListElement", []), g)
            else:
                walk(str(n.get("text") or n.get("name") or ""), group)

    walk(node, groups[0])
    return [g for g in groups if g["items"]]


def as_groups(v, strip_numbers=False):
    """Accept a list of strings or a list of {group, items} and return clean groups."""
    if not v:
        return []
    out = []
    loose = {"group": "", "items": []}
    for g in v if isinstance(v, list) else [v]:
        if isinstance(g, dict):
            items = [clean_text(x) for x in g.get("items", []) if clean_text(x)]
            if strip_numbers:
                items = [STEP_PREFIX.sub("", x) for x in items]
            if items:
                out.append({"group": clean_text(g.get("group")), "items": items})
        elif clean_text(g):
            loose["items"].append(STEP_PREFIX.sub("", clean_text(g)) if strip_numbers else clean_text(g))
    if loose["items"]:
        out.insert(0, loose)
    return out


def site_name(url, meta, ld):
    if meta.get("og:site_name"):
        return clean_text(meta["og:site_name"])
    pub = (ld or {}).get("publisher")
    if isinstance(pub, dict) and pub.get("name"):
        return clean_text(pub["name"])
    return urlparse(url).netloc.removeprefix("www.") if url else ""


def normalize_jsonld(ld):
    """Format schema.org Recipe data without AI."""
    prep, cook, total = (iso_duration(ld.get(k)) for k in ("prepTime", "cookTime", "totalTime"))
    desc = clean_text(ld.get("description"))
    if len(desc) > 160:  # SEO descriptions run long; keep the first sentence
        desc = re.split(r"(?<=[.!?])\s", desc)[0][:220]
    return {
        "title": clean_text(ld.get("name")),
        "description": desc,
        "servings": pick_yield(ld.get("recipeYield")),
        "prep_time": prep,
        "cook_time": cook,
        "total_time": total,
        "tags": make_tags(ld.get("recipeCategory"), ld.get("recipeCuisine"), ld.get("keywords"), limit=6),
        "ingredients": as_groups([clean_text(x) for x in ld.get("recipeIngredient") or ld.get("ingredients") or []]),
        "steps": parse_steps(ld.get("recipeInstructions") or []),
        "notes": [],
    }


# ---------------------------------------------------------------- Claude

def call_claude(content, model):
    key = os.environ.get("ANTHROPIC_API_KEY")
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude API error {e.code}: {e.read().decode(errors='replace')[:400]}")
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("Claude did not return JSON")
    result = json.loads(m.group(0))
    if result.get("error"):
        raise RuntimeError(f"Claude says: {result['error']}")
    return result


def trimmed_ld(ld):
    drop = {"review", "aggregateRating", "video", "author", "publisher", "comment",
            "interactionStatistic", "isPartOf", "mainEntityOfPage", "potentialAction"}
    return json.dumps({k: v for k, v in ld.items() if k not in drop}, ensure_ascii=False)[:20000]


# ---------------------------------------------------------------- pipeline

def slugify(s):
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    return re.sub(r"[\s_-]+", "-", s)[:70].strip("-") or "recipe"


def finalize(data, url="", source_name="", image=""):
    recipe = {
        "title": clean_text(data.get("title")),
        "description": clean_text(data.get("description")),
        "source_url": url,
        "source_name": source_name,
        "image": image or "",
        "servings": clean_text(data.get("servings")),
        "prep_time": clean_text(data.get("prep_time")),
        "cook_time": clean_text(data.get("cook_time")),
        "total_time": clean_text(data.get("total_time")),
        "tags": make_tags(data.get("tags")),
        "ingredients": as_groups(data.get("ingredients")),
        "steps": as_groups(data.get("steps"), strip_numbers=True),
        "notes": [clean_text(n) for n in data.get("notes") or [] if clean_text(n)],
        "added": datetime.date.today().isoformat(),
    }
    if not recipe["title"] or not recipe["ingredients"] or not recipe["steps"]:
        raise RuntimeError("Couldn't find a complete recipe (title, ingredients and steps) on that page")
    recipe["slug"] = slugify(recipe["title"])
    return recipe


def existing_sources():
    out = {}
    for p in RECIPES_DIR.glob("*.json"):
        try:
            u = json.loads(p.read_text(encoding="utf-8")).get("source_url")
            if u:
                out[u.rstrip("/")] = p.name
        except (json.JSONDecodeError, OSError):
            pass
    return out


def save(recipe, force=False):
    RECIPES_DIR.mkdir(exist_ok=True)
    path = RECIPES_DIR / f"{recipe['slug']}.json"
    if path.exists() and not force:
        n = 2
        while (RECIPES_DIR / f"{recipe['slug']}-{n}.json").exists():
            n += 1
        recipe["slug"] = f"{recipe['slug']}-{n}"
        path = RECIPES_DIR / f"{recipe['slug']}.json"
    path.write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def process_page(page_html, url, use_ai, model):
    p = PageParser()
    p.feed(page_html)
    ld = recipe_from_jsonld(p.jsonld)
    image = pick_image((ld or {}).get("image")) or p.meta.get("og:image", "")
    name = site_name(url, p.meta, ld)

    data = None
    if use_ai:
        if ld:
            content = f"Source: {url}\n\nStructured recipe data from the page:\n{trimmed_ld(ld)}"
        else:
            title = p.meta.get("og:title", "")
            content = f"Source: {url}\nPage title: {title}\n\nPage text:\n{p.visible_text()}"
        try:
            data = call_claude(content, model)
        except Exception as e:
            if not ld:
                raise
            print(f"   ! AI step failed ({e}); falling back to the page's structured data")
    if data is None:
        if not ld:
            raise RuntimeError("No structured recipe data on this page. Set ANTHROPIC_API_KEY so "
                               "Claude can read the page text instead.")
        data = normalize_jsonld(ld)
    return finalize(data, url, name, image)


def main():
    ap = argparse.ArgumentParser(description="Import recipes into recipes/ as clean JSON.")
    ap.add_argument("urls", nargs="*", help="recipe page URLs")
    ap.add_argument("--list", help="text file with one URL per line")
    ap.add_argument("--file", help="a saved .html page (for sites that block scripts)")
    ap.add_argument("--url", default="", help="source URL to credit when using --file")
    ap.add_argument("--text", help="plain-text recipe (typed up, pasted, from a cookbook) - needs AI")
    ap.add_argument("--tags", default="", help="extra comma-separated tags to add, e.g. 'family,favorite'")
    ap.add_argument("--no-ai", action="store_true", help="skip Claude; use the page's structured data only")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default {DEFAULT_MODEL})")
    ap.add_argument("--force", action="store_true", help="re-import URLs you already have / overwrite same slug")
    ap.add_argument("--dry-run", action="store_true", help="print the result instead of saving")
    ap.add_argument("--build", action="store_true", help="rebuild the site afterwards")
    args = ap.parse_args()

    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY")) and not args.no_ai
    urls = list(args.urls)
    if args.list:
        urls += [l.strip() for l in Path(args.list).read_text().splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
    if not (urls or args.file or args.text):
        ap.print_help()
        return 1

    print(f"Mode: {'Claude (' + args.model + ')' if use_ai else 'structured data only (no AI)'}")
    have = {} if args.force else existing_sources()
    extra = make_tags(args.tags)
    jobs = [("url", u) for u in urls]
    if args.file:
        jobs.append(("file", args.file))
    if args.text:
        jobs.append(("text", args.text))

    ok = 0
    for kind, item in jobs:
        print(f"-> {item}")
        try:
            if kind == "url":
                if item.rstrip("/") in have:
                    print(f"   already imported as {have[item.rstrip('/')]} (use --force to redo)")
                    continue
                recipe = process_page(fetch(item), item, use_ai, args.model)
            elif kind == "file":
                page = Path(item).read_text(encoding="utf-8", errors="replace")
                recipe = process_page(page, args.url, use_ai, args.model)
            else:
                if not use_ai:
                    raise RuntimeError("--text needs ANTHROPIC_API_KEY (Claude does the formatting)")
                txt = Path(item).read_text(encoding="utf-8", errors="replace")[:40000]
                recipe = finalize(call_claude(f"Recipe text:\n{txt}", args.model))
            recipe["tags"] = make_tags(recipe["tags"], extra)
            if args.dry_run:
                print(json.dumps(recipe, indent=2, ensure_ascii=False))
            else:
                path = save(recipe, args.force)
                print(f"   saved {path.relative_to(ROOT)}  ({recipe['title']})")
            ok += 1
        except urllib.error.HTTPError as e:
            print(f"   x site refused the request ({e.code}). Save the page from your browser "
                  f"and use --file page.html --url {item}")
        except Exception as e:
            print(f"   x {e}")

    print(f"\n{ok} of {len(jobs)} imported.")
    if ok and args.build and not args.dry_run:
        subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")], check=False)
    elif ok and not args.dry_run:
        print("Run  python tools/build.py  to rebuild the site.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
