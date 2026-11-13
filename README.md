# The Recipe Box

A static recipe website, fed by an AI import agent:

1. **Import**: give `tools/add_recipe.py` a recipe URL. It fetches the page, and Claude strips the life story, ads and filler, then saves a clean recipe to `recipes/<name>.json`.
2. **Build**: `tools/build.py` turns every recipe into a static site in `site/`, with search, tag filters, printable recipe pages and a **"What should I make?" randomizer**.
3. **Host**: put `site/` anywhere that serves static files (GitHub Pages, Netlify, Cloudflare Pages, or your own server).

You only need Python 3.9 or newer. There's nothing to `pip install`.

## Quick start

```bash
python tools/build.py
python -m http.server -d site 8000
# open http://localhost:8000
```

Seven sample recipes are included so the site and the randomizer have something to show. Delete the files in `recipes/` whenever you like.

## Adding recipes

### 1. Get a Claude API key (recommended)

Create a key at https://console.anthropic.com, then set it in your terminal:

```bash
# macOS / Linux
export ANTHROPIC_API_KEY="sk-ant-..."

# Windows PowerShell
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

The default model is `claude-haiku-5-5`, which is fast and costs a fraction of a cent per recipe. To use a different one, pass `--model claude-sonnet-5-5` or set `RECIPE_MODEL`.

**No key?** Most recipe sites embed structured recipe data (schema.org) in the page, and the script will format that directly. You just won't get Claude's cleanup (shorter steps, useful notes, sensible tags). You can force this mode with `--no-ai`.

### 2. Import

```bash
# one recipe, then rebuild the site
python tools/add_recipe.py https://www.example.com/best-chili --build

# several at once
python tools/add_recipe.py URL1 URL2 URL3

# a list in a text file (one URL per line, # for comments)
python tools/add_recipe.py --list urls.txt --build

# add your own tags
python tools/add_recipe.py URL --tags "family favorite,freezer"

# preview without saving
python tools/add_recipe.py URL --dry-run
```

**Site blocks the script (403 error)?** Save the page from your browser (Ctrl/Cmd+S, "Webpage, HTML only") and run:

```bash
python tools/add_recipe.py --file saved-page.html --url https://www.example.com/best-chili
```

**Recipe from a cookbook, a card or a text message?** Type or paste it into a `.txt` file. This one needs the API key:

```bash
python tools/add_recipe.py --text grandmas-chili.txt
```

URLs you've already imported are skipped. Use `--force` to re-import.

### 3. Edit by hand

Each recipe is a readable JSON file in `recipes/`. Fix a typo, change a tag or add a note, then run `python tools/build.py`. The file name becomes the page URL.

```json
{
  "title": "Weeknight Chicken Fajitas",
  "description": "One sentence about the dish.",
  "source_url": "https://...",
  "source_name": "Site name",
  "image": "https://... (optional)",
  "servings": "4",
  "prep_time": "10 min",
  "cook_time": "20 min",
  "total_time": "30 min",
  "tags": ["dinner", "chicken", "quick"],
  "ingredients": [{"group": "", "items": ["1 lb chicken", "..."]}],
  "steps": [{"group": "", "items": ["Do this.", "Then this."]}],
  "notes": ["Optional tips."],
  "added": "2026-11-12"
}
```

Use `group` for components such as "For the sauce". Leave it as `""` for a single list.

## The randomizer

- The big **What should I make?** button on the home page spins through your recipes and lands on one.
- It picks **from whatever you've filtered to**. Click the `dinner` tag (or search "chicken") first, and it only picks from those.
- Press **R** on the home page to spin.
- `random.html` sends you straight to a random recipe, which makes a good bookmark or phone home-screen shortcut. `random.html?tag=dinner` limits it to one tag.

## Recipe pages

- Tick off ingredients as you gather them, and tap a step to mark it done.
- **Keep screen on** stops your phone from sleeping while you cook (in browsers that support it).
- **Print** gives you a clean layout without the page chrome.
- Every recipe links back to the site it came from.

## Customizing

- Site title and tagline: `site.json`
- Colors and fonts: `assets/style.css` (the variables at the top). Dark mode is automatic.
- Page layout: `tools/build.py`

## Hosting

**GitHub Pages (automatic):** push this folder to a GitHub repo. In the repo, go to *Settings → Pages* and set *Source* to **GitHub Actions**. The included workflow (`.github/workflows/pages.yml`) rebuilds and publishes the site every time you push a new recipe.

**Netlify / Cloudflare Pages:** set the build command to `python tools/build.py` and the publish directory to `site`. Or run the build yourself and drag the `site/` folder onto Netlify Drop.

## A note on images

When a recipe has an image, the site links to the original site's photo instead of copying it. Some sites block that, and a colored letter tile shows instead. You can always put your own photo URL in the `image` field.
