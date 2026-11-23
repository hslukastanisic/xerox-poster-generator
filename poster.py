#!/usr/bin/env python3
"""Punk-photocopy poster generator.

    python poster.py                        # every image in images/ -> posters/
    python poster.py images/ out/           # explicit folders
    python poster.py images/ --variants=3   # 3 posters per image
    python poster.py --reroll               # new random layout/colours
    python poster.py image.jpg              # single poster

Event text is drawn at random from event_info.json.
"""


import hashlib
import json
import sys
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"

BASE_W, BASE_H = 1240, 1754
ALLOW_LANDSCAPE = True
LANDSCAPE_LUCK = 0.30
LIGHT_BG_CHANCE = 0.50     # share of posters with a pastel field instead of a dark one
TITLE_AT_TOP = 0.50

# (name, accent) — the ink is derived from the accent, so every pair is harmonious
ACCENTS = [
    ("pink",     (238, 168, 190)),
    ("mint",     (168, 218, 188)),
    ("sky",      (156, 198, 228)),
    ("butter",   (243, 206, 132)),
    ("lavender", (196, 178, 228)),
    ("peach",    (247, 184, 154)),
    ("sage",     (190, 212, 164)),
    ("lilac",    (216, 168, 214)),
    ("seafoam",  (148, 214, 206)),
    ("apricot",  (245, 194, 126)),
    ("clay",     (226, 176, 168)),
    ("paper",    (226, 226, 220)),   # keeps a few genuine B&W posters in the series
]

_SKIP = ("emoji", "symbol", "wingding", "dingbat", "icon", "math",
         "braille", "lastresort", "awesome", "material")
_SCRIPT = ("script", "hand", "brush", "marker", "cursive", "chancery", "comic",
           "caveat", "pacifico", "indie", "dancing", "allura", "sacramento",
           "kalam", "architect", "segoepr", "segoesc", "freestyle", "chalk",
           "handwriting", "pen")
_SERIF = ("serif", "times", "georgia", "garamond", "baskerville", "playfair",
          "book", "roman", "cambria", "constantia", "palatino", "didot",
          "caslon", "merriweather", "lora", "crimson", "rockwell", "clarendon",
          "century", "slab", "cochin", "hoefler", "bodon")
_BOLD = ("black", "heavy", "bold", "impact", "anton", "archivo", "oswald",
         "bebas", "haettenschweiler", "franklin", "condensed", "compressed",
         "poster", "display", "grotesk", "grotesque", "expanded", "fat", "chunk")


def _font_roots():
    roots = [FONT_DIR]
    #if sys.platform == "darwin":
    #    roots += [Path("/System/Library/Fonts"),
    #              Path("/System/Library/Fonts/Supplemental"),
    #              Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    #elif sys.platform.startswith("win"):
    #    roots += [Path("C:/Windows/Fonts"),
    #              Path.home() / "AppData/Local/Microsoft/Windows/Fonts"]
    #else:
    #    roots += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
    #              Path.home() / ".fonts", Path.home() / ".local/share/fonts"]
    #return [r for r in roots if r.is_dir()]
    return roots


@lru_cache(maxsize=None)
def _ok(path):
    try:
        m = ImageFont.truetype(path, 40).getmask("A")
        return m.size[0] > 0 and m.size[1] > 0
    except Exception:
        return False


@lru_cache(maxsize=None)
def load_fonts():
    paths, seen = [], set()
    for root in _font_roots():
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            for p in sorted(root.rglob(ext)):
                if p.name in seen or any(s in p.stem.lower() for s in _SKIP):
                    continue
                seen.add(p.name)
                paths.append(str(p))

    pools = {"display": [], "serif": [], "italic": [], "script": [], "sans": []}
    for p in paths:
        if not _ok(p):
            continue
        n = Path(p).stem.lower()
        italic = "italic" in n or "oblique" in n
        script = any(k in n for k in _SCRIPT)
        serif = any(k in n for k in _SERIF)
        bold = any(k in n for k in _BOLD)
        if script:
            pools["script"].append(p)
        elif serif:
            pools["italic" if italic else "serif"].append(p)
        elif not italic:
            pools["sans"].append(p)
            if bold:
                pools["display"].append(p)
        if italic and not script:
            pools["italic"].append(p)

    every = [p for v in pools.values() for p in v] or paths
    if not every:
        raise SystemExit(f"No usable fonts found. Put .ttf files in {FONT_DIR}")
    for role in list(pools):
        if not pools[role]:
            pools[role] = list(every)
    return pools


_MEASURE = ImageDraw.Draw(Image.new("L", (4, 4)))


def text_width(s, font, tracking=0.0):
    if not s:
        return 0.0
    return sum(_MEASURE.textlength(c, font=font) for c in s) + tracking * (len(s) - 1)


def draw_tracked(d, xy, s, font, fill, tracking=0.0):
    x, y = xy
    for c in s:
        d.text((x, y), c, font=font, fill=fill)
        x += _MEASURE.textlength(c, font=font) + tracking

def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))

def palette_from(accent, rng):
    """Deep ink from the accent's hue + a little jitter, so repeats still differ."""
    ink = tuple(max(6, int(c * 0.13 + 4)) for c in accent)
    ink = tuple(int(np.clip(c + rng.integers(-3, 4), 0, 255)) for c in ink)
    paper = tuple(int(np.clip(c + rng.integers(-9, 10), 0, 255)) for c in accent)
    return ink, paper

def fit_size(text, path, target_w, tracking_ratio=-0.02, lo=24, hi=460):
    f = ImageFont.truetype(path, 100)
    w = text_width(text, f, tracking_ratio * 100)
    if w <= 0:
        return lo
    size = int(100 * target_w / w)
    for _ in range(4):
        size = max(lo, min(hi, size))
        f = ImageFont.truetype(path, size)
        w = text_width(text, f, tracking_ratio * size)
        if w <= 0:
            return size
        size = int(size * target_w / w)
    return max(lo, min(hi, size))


def wrap(text, path, size, max_w):
    f = ImageFont.truetype(path, size)
    lines, cur = [], ""
    for word in str(text).split():
        cand = (cur + " " + word).strip()
        if not cur or text_width(cand, f) <= max_w:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def safe_paste(base, im, x, y):
    x, y = int(round(x)), int(round(y))
    cx0, cy0 = max(0, x), max(0, y)
    cx1, cy1 = min(base.width, x + im.width), min(base.height, y + im.height)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    piece = im.crop((cx0 - x, cy0 - y, cx1 - x, cy1 - y))
    if piece.mode == "RGBA":
        base.paste(piece, (cx0, cy0), piece.getchannel("A"))
    else:
        base.paste(piece, (cx0, cy0))


# ------------------------------------------------------------------- title
def render_title(text, path, target_w, color):
    words = [w for w in str(text).upper().split() if w]
    if not words:
        return None

    size = fit_size(" ".join(words), path, target_w)
    plans = [(" ".join(words), size)]

    if size < 150 and len(words) > 1:
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            m = min(fit_size(a, path, target_w), fit_size(b, path, target_w))
            if best is None or m > best[0]:
                best = (m, a, b)
        if best and best[0] > size * 1.15:
            plans = [(best[1], best[0]), (best[2], best[0])]

    tiles = []
    for line, size in plans:
        f = ImageFont.truetype(path, size)
        tr = -0.025 * size
        l, t, r, b = f.getbbox(line)
        w = int(text_width(line, f, tr)) + 10
        h = (b - t) + 10
        img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        draw_tracked(ImageDraw.Draw(img), (5 - l, 5 - t), line, f, color + (255,), tr)
        tiles.append(img)

    gap = int(0.05 * plans[0][1])
    bw = max(t.width for t in tiles)
    bh = sum(t.height for t in tiles) + gap * (len(tiles) - 1)
    block = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    y = 0
    for t in tiles:
        block.alpha_composite(t, ((bw - t.width) // 2, y))
        y += t.height + gap
    return block


# ------------------------------------------------------------------- photo
def _fs():
    return getattr(Image, "Dither", Image).FLOYDSTEINBERG


def halftone(img, cell=6):
    a = np.asarray(img, dtype=np.float32) / 255.0
    h, w = a.shape
    out = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(out)
    scale = (cell / 2.0) * 1.15
    for y in range(0, h - cell + 1, cell):
        for x in range(0, w - cell + 1, cell):
            dark = 1.0 - float(a[y:y + cell, x:x + cell].mean())
            r = scale * float(np.sqrt(max(dark, 0.0)))
            if r < 0.5:
                continue
            cx, cy = x + cell / 2.0, y + cell / 2.0
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
    return out


def print_effect(img, rng, mode):
    a = np.asarray(img, dtype=np.float32)
    a = np.clip((a - 45.0) * (255.0 / 165.0), 0, 255)
    img = Image.fromarray(a.astype(np.uint8))

    if mode == "dither":
        img = img.convert("1", dither=_fs()).convert("L")
    elif mode == "halftone":
        img = halftone(img, cell=int(rng.integers(4, 8)))
    else:
        img = img.filter(ImageFilter.GaussianBlur(float(rng.uniform(0.4, 0.9))))
        a = np.asarray(img, dtype=np.float32)
        img = Image.fromarray(
            np.clip((a - 115.0) * 2.2 + 128.0, 0, 255).astype(np.uint8))

    a = np.asarray(img, dtype=np.float32)
    a += rng.normal(0.0, float(rng.uniform(4.0, 9.0)), a.shape)
    m = rng.random(a.shape)
    a[m > 0.9975] = 0.0
    a[m < 0.0025] = 255.0
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def duotone(img, ink, paper):
    a = np.asarray(img, dtype=np.float32) / 255.0
    out = np.empty(a.shape + (3,), dtype=np.uint8)
    for i in range(3):
        out[..., i] = np.clip(ink[i] + (paper[i] - ink[i]) * a, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def prepare_photo(src, bw, bh, ink, paper, rng):
    im = ImageOps.exif_transpose(src).convert("L")
    s = min(bw / im.width, bh / im.height)
    tw, th = max(1, int(im.width * s)), max(1, int(im.height * s))

    cover = tw * th < 0.55 * bw * bh
    if cover:
        s = max(bw / im.width, bh / im.height)
        tw, th = int(im.width * s + 0.5), int(im.height * s + 0.5)

    mode = str(rng.choice(np.array(["grain", "grain", "halftone", "dither"])))
    work = min(tw, 1000)
    g = im.resize((work, max(1, int(th * work / tw))), Image.LANCZOS)
    g = print_effect(g, rng, mode).resize((tw, th), Image.LANCZOS)
    out = duotone(g, ink, paper)

    if out.width > bw or out.height > bh:          # cover crop: clamp to the box
        out = ImageOps.fit(out, (bw, bh), Image.LANCZOS, centering=(0.5, 0.45))
    return out


# ------------------------------------------------------------------ scraps
def make_scrap(lines, path, size, rng, bg, fg, tracking_ratio=0.0, outline=None):
    f = ImageFont.truetype(path, size)
    tr = tracking_ratio * size
    boxes = [f.getbbox(l) for l in lines]
    line_h = max(b - t for (_, t, _, b) in boxes)
    inner_w = int(max(text_width(l, f, tr) for l in lines)) + 10
    inner_h = line_h * len(lines) + int(size * 0.14) * (len(lines) - 1) + 10
    pad = int(size * float(rng.uniform(0.26, 0.44)))

    img = Image.new("RGBA", (inner_w + 2 * pad, inner_h + 2 * pad), bg + (255,))
    d = ImageDraw.Draw(img)
    if outline is not None:
        d.rectangle([1, 1, img.width - 2, img.height - 2],
                    outline=outline + (255,), width=max(2, size // 16))

    y = pad + 5
    for line, (l, t, r, b) in zip(lines, boxes):
        draw_tracked(d, (pad + 5 - l, y - t), line, f, fg + (255,), tr)
        y += line_h + int(size * 0.14)

    return img.rotate(float(rng.uniform(-4.5, 4.5)), expand=True,
                      resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))


def make_text_scrap(text, path, size, max_w, rng, bg, fg,
                    tracking_ratio=0.0, outline=None):
    lines = wrap(text, path, size, max_w)
    while len(lines) > 2 and size > 16:
        size = int(size * 0.92)
        lines = wrap(text, path, size, max_w)
    return make_scrap(lines, path, size, rng, bg, fg, tracking_ratio, outline)



def overlaps(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def place_scraps(scraps, region, rng, gap=18):
    x0, y0, x1, y1 = region
    placed, out = [], []

    for sc in scraps:
        x = y = rect = None
        for _ in range(150):
            if sc.width > 0.6 * (x1 - x0):
                x = x0 + (x1 - x0 - sc.width) / 2
            elif rng.random() < 0.5:
                x = x0 + float(rng.uniform(0.01, 0.20)) * (x1 - x0)
            else:
                x = x1 - sc.width - float(rng.uniform(0.01, 0.20)) * (x1 - x0)
            x = max(x0, min(x1 - sc.width, x))

            ylo = y0 + 0.02 * (y1 - y0)
            yhi = max(ylo, y1 - 0.02 * (y1 - y0) - sc.height)
            y = max(y0, min(y1 - sc.height, float(rng.uniform(ylo, yhi))))

            cand = (x - gap, y - gap, x + sc.width + gap, y + sc.height + gap)
            rect = cand
            if all(not overlaps(cand, r) for r in placed):
                break

        if rect is None:                       # no candidate at all: park it
            x, y = x0 + 8, y0 + 8
            rect = (x, y, x + sc.width, y + sc.height)

        placed.append(rect)
        out.append((x, y, sc))

    return out


# ---------------------------------------------------------------- distress
def distress(img, rng, ink, paper):
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    a = np.asarray(
        Image.fromarray(a.astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(float(rng.uniform(0.2, 0.5)))),
        dtype=np.float32)
    a += rng.normal(0.0, float(rng.uniform(2.5, 5.0)), a.shape)
    m = rng.random(a.shape[:2])
    a[m < 0.00012] = np.array(ink, dtype=np.float32)
    a[m > 1 - 0.00012] = np.array(paper, dtype=np.float32)
    h = a.shape[0]
    for _ in range(2):
        band = int(rng.integers(1, 3))
        yy = int(rng.integers(0, max(1, h - band)))
        shift = int(rng.integers(1, 4)) * (1 if rng.random() > 0.5 else -1)
        a[yy:yy + band] = np.roll(a[yy:yy + band], shift, axis=1)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ----------------------------------------------------------------- poster
def build_poster(src, event, out_path, seed, fonts, accent=None):
    rng = np.random.default_rng(seed)

    if accent is None:
        accent = ACCENTS[int(rng.integers(0, len(ACCENTS)))]
    pal_name, base = accent
    ink, paper = palette_from(base, rng)

    # half the posters are a pastel field with dark type, half a dark field
    light = rng.random() < LIGHT_BG_CHANCE
    bg        = paper if light else ink
    title_col = ink if light else paper
    scrap_bg  = mix(paper, (255, 255, 255), 0.30) if light else paper
    scrap_edge = ink if light else None

    W, H = BASE_W, BASE_H
    if ALLOW_LANDSCAPE and src.width > src.height * 1.2 and rng.random() < LANDSCAPE_LUCK:
        W, H = BASE_H, BASE_W

    canvas = Image.new("RGB", (W, H), bg)

    title_font = str(fonts["display"][int(rng.integers(0, len(fonts["display"])))])
    title = render_title(event.get("artist", ""), title_font,
                         W * float(rng.uniform(0.97, 1.15)), title_col)

    pad = int(BASE_H * float(rng.uniform(0.018, 0.042)))
    band = (title.height + pad) if title else 0
    top = rng.random() < TITLE_AT_TOP

    if title and top:
        photo_box = (0, band, W, BASE_H)
    elif title:
        photo_box = (0, 0, W, BASE_H - band)
    else:
        photo_box = (0, 0, BASE_W, BASE_H)

    bx0, by0, bx1, by1 = photo_box
    bw_box, bh_box = bx1 - bx0, by1 - by0
    photo = prepare_photo(src, bw_box, bh_box, ink, paper, rng)
    safe_paste(canvas, photo,
               bx0 + (bw_box - photo.width) // 2,
               by0 + (bh_box - photo.height) // 2)

    if title:                                    # after the photo: can't be buried
        ty = pad // 2 if top else H - band + pad // 2
        tx = (W - title.width) / 2 + float(rng.uniform(-14, 14))
        safe_paste(canvas, title, tx, ty)

    roles = [("date", "display", 0.046, 0.0),
             ("venue", "serif", 0.040, 0.0),
             ("location", "italic", 0.026, 0.0),
             ("price", "script", 0.034, -0.01)]
    used, scraps = set(), []
    for key, role, rel, track in roles:
        txt = str(event.get(key) or "").strip()
        if not txt:
            continue
        pool = [p for p in fonts[role] if p not in used] or fonts[role]
        path = str(pool[int(rng.integers(0, len(pool)))])
        used.add(path)
        size = max(16, int(W * rel))
        scraps.append(make_text_scrap(txt, path, size, int(W * 0.62), rng,
                                      scrap_bg, ink, tracking_ratio=track,
                                      outline=scrap_edge))

    if top:
        region = (int(0.03 * W), int(0.40 * H), int(0.97 * W), int(0.985 * H))
    else:
        region = (int(0.03 * W), int(0.015 * H), int(0.97 * W), int(0.60 * H))

    for x, y, sc in place_scraps(scraps, region, rng):
        safe_paste(canvas, sc, x, y)

    canvas = distress(canvas, rng, ink, paper)
    canvas = canvas.rotate(float(rng.uniform(-0.6, 0.6)),
                           resample=Image.BICUBIC, fillcolor=bg)
    canvas.save(out_path, dpi=(150, 150))
    print(f"  {out_path.name}  [{pal_name}/{'light' if light else 'dark'}]  "
          f"title={'top' if top else 'bottom'}  seed={seed}")
    return out_path


# ------------------------------------------------------------------- input
def field(event, key):
    for k in FIELDS[key]:
        v = event.get(k)
        if v not in (None, "", []):
            return v
    return ""


def resolve_image(event, base_dir):
    raw = str(field(event, "image") or "")
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        return None                      # download these first
    p = Path(raw)
    if not p.is_absolute():
        p = base_dir / p
    return p if p.is_file() else None


def slug(s, n=40):
    keep = [c.lower() if c.isalnum() else "-" for c in s]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:n] or "poster"


# ------------------------------------------------------------------- input
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
INFO_KEYS = ("artist", "date", "venue", "location", "price")
DEFAULT_RUN_SEED = 1991


def slug(s, n=40):
    keep = [c.lower() if c.isalnum() else "-" for c in s]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:n] or "poster"


def load_info(path):
    """Read {field: [values]} and validate that every field has values."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit(f"{path}: expected an object with keys "
                         f"{', '.join(INFO_KEYS)}")
    info = {}
    for k in INFO_KEYS:
        vals = raw.get(k)
        if isinstance(vals, (str, int, float)):
            vals = [vals]
        if not isinstance(vals, list) or not vals:
            raise SystemExit(f"{path}: missing or empty list for '{k}'")
        info[k] = [str(v) for v in vals]
    return info


class Deck:
    """Draw values without repeats, reshuffling only when the pool runs out.

    This is what stops a folder of 12 images from getting the same band
    three times: the first 20 posters drawn from a 20-value list are unique.
    """

    def __init__(self, values, rng):
        self.values = list(values) or [""]
        self.rng = rng
        self.bag = []

    def draw(self):
        if not self.bag:
            self.bag = [self.values[int(i)]
                        for i in self.rng.permutation(len(self.values))]
        return self.bag.pop()


def find_images(folder):
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.suffix.lower() in IMG_EXT)


def random_event(info):
    rng = np.random.default_rng(int.from_bytes(os.urandom(4), "big"))
    return {k: info[k][int(rng.integers(0, len(info[k])))] for k in INFO_KEYS}


def write_manifest(directory, name="posters.json"):
    """Index a poster folder so the HTML grid can read it."""
    directory = Path(directory)
    items = []
    for p in find_images(directory):
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception:
            continue
        items.append({
            "src": p.name,
            "w": w,
            "h": h,
            "title": p.stem.replace("-", " ").replace("_", " ").upper(),
        })
    out = directory / name
    out.write_text(json.dumps({"count": len(items), "posters": items}, indent=2),
                   encoding="utf-8")
    print(f"manifest: {out} ({len(items)} posters)")
    return out


def run_batch(images_dir, out_dir=None, info_path=None, variants=1, reseed=False):
    images_dir = Path(images_dir)
    if not images_dir.is_dir():
        raise SystemExit(f"Not a folder: {images_dir}")

    images = find_images(images_dir)
    if not images:
        raise SystemExit(f"No images in {images_dir} "
                         f"(looked for {' '.join(IMG_EXT)})")

    out_dir = Path(out_dir) if out_dir else images_dir.parent / "posters"
    out_dir.mkdir(parents=True, exist_ok=True)

    info = load_info(info_path or HERE / "event_info.json")
    fonts = load_fonts()

    run_seed = (int.from_bytes(os.urandom(4), "big") if reseed
                else DEFAULT_RUN_SEED)
    rng = np.random.default_rng(run_seed)

    decks = {k: Deck(info[k], rng) for k in INFO_KEYS}
    accents = Deck(ACCENTS, rng)
    variants = max(1, int(variants))

    print(f"{len(images)} image(s) -> {out_dir}  "
          f"(variants={variants}, run seed {run_seed})")

    made = skipped = 0
    for img_path in images:
        for v in range(variants):
            event = {k: d.draw() for k, d in decks.items()}
            accent = accents.draw()

            key = f"{run_seed}|{img_path.name}|{v}"
            seed = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
            stem = slug(f"{event['artist']}-{img_path.stem}")
            out = out_dir / f"{stem}-{seed % 10000:04d}.png"

            try:
                with Image.open(img_path) as im:
                    im.load()
                    build_poster(im, event, out, seed, fonts, accent=accent)
            except Exception as exc:      # one broken file must not kill the run
                print(f"  skip {img_path.name}: {type(exc).__name__}: {exc}")
                skipped += 1
                continue
            made += 1

    write_manifest(out_dir)
    print(f"done: {made} poster(s)"
          + (f", {skipped} skipped" if skipped else "")
          + f" -> {out_dir}")


def parse_args(argv):
    positional, opts, i = [], {}, 1
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                key, val = key.split("=", 1)
            elif key == "info" and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                i += 1
                val = argv[i]
            else:
                val = True
            opts[key] = val
        else:
            positional.append(a)
        i += 1
    return positional, opts


def main(argv):
    positional, opts = parse_args(argv)

    info = opts.get("info")
    if not isinstance(info, str):
        info = None
    variants = int(opts.get("variants") or 1)
    reseed = bool(opts.get("reroll") or opts.get("reseed"))

    # python poster.py            -> ./images  ->  ./posters
    if not positional:
        run_batch(HERE / "images", HERE / "posters", info, variants, reseed)
        return

    target = Path(positional[0])

    # python poster.py images/ [outdir/]
    if target.is_dir():
        out = Path(positional[1]) if len(positional) > 1 else target.parent / "posters"
        run_batch(target, out, info, variants, reseed)
        return

    # python poster.py one.jpg [out.png]  -> single poster, random event info
    if target.is_file() and target.suffix.lower() in IMG_EXT:
        event = random_event(load_info(info or HERE / "event_info.json"))
        fonts = load_fonts()
        out = (Path(positional[1]) if len(positional) > 1
               else target.with_name(f"{target.stem}-poster.png"))
        seed = int.from_bytes(os.urandom(4), "big")
        with Image.open(target) as im:
            im.load()
            build_poster(im, event, out, seed, fonts)
        return

    raise SystemExit(f"Not an image or image folder: {target}")


if __name__ == "__main__":
    main(sys.argv)

