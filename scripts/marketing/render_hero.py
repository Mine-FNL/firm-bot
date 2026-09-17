"""Render marketing infographics for the firm-bot campaign.

Outputs (all written under docs/assets/marketing/):
  - hero.png             : 1600x900 hero banner, GitHub-OG sized
  - architecture.png     : 1600x1000 pipeline infographic
  - comparison.png       : 1600x1000 vs Harvey/Spellbook/Glean
  - why_local.png        : 1600x1000 "your data, your box" angle

All hand-rolled with Pillow. No external SVG renderer.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("docs/assets/marketing")
OUT.mkdir(parents=True, exist_ok=True)

# Palette
BG_TOP = (15, 23, 42)
BG_BOTTOM = (30, 27, 75)
ACCENT_BLUE = (96, 165, 250)
ACCENT_VIOLET = (167, 139, 250)
ACCENT_GREEN = (74, 222, 128)
ACCENT_AMBER = (251, 191, 36)
TEXT = (241, 245, 249)
TEXT_DIM = (148, 163, 184)
PANEL_BG = (30, 41, 59)
PANEL_BORDER = (71, 85, 105)
GREEN_OK = (34, 197, 94)
RED_NO = (239, 68, 68)


def find_font(*candidates: str, size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size[0]):
            px[x, y] = (r, g, b)
    return img


def soft_glow(img: Image.Image, cx: int, cy: int, r: int, color: tuple[int, int, int], alpha: float = 0.20) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for k in range(6, 0, -1):
        rr = int(r * (k / 6))
        a = int(alpha * 255 * (k / 6))
        od.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=color + (a,))
    img.alpha_composite(overlay)


# ---- HERO BANNER ------------------------------------------------------------

def render_hero() -> Path:
    W, H = 1600, 900
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    soft_glow(img, 300, 250, 380, ACCENT_BLUE, 0.22)
    soft_glow(img, 1280, 700, 420, ACCENT_VIOLET, 0.20)

    d = ImageDraw.Draw(img)
    f_logo = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=200)
    f_h1 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=54)
    f_h2 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=36)
    f_pill = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=26)

    d.text((100, 220), "firm-bot", fill=ACCENT_BLUE, font=f_logo)
    d.text((104, 440), "Local-first RAG for professional services.", fill=TEXT, font=f_h1)
    d.text((104, 510), "Citations required. Your data never leaves the box.", fill=TEXT_DIM, font=f_h2)

    # Pills
    pills = ["Citations required", "Ollama-powered", "Multi-tenant", "MIT licensed", "No telemetry"]
    x = 104
    y = 600
    for label in pills:
        bbox = d.textbbox((0, 0), label, font=f_pill)
        w = bbox[2] - bbox[0] + 40
        d.rounded_rectangle((x, y, x + w, y + 56), radius=28, outline=ACCENT_BLUE, width=2)
        d.text((x + 20, y + 12), label, fill=TEXT, font=f_pill)
        x += w + 16

    # Right side: stats card
    cx0, cy0 = 980, 160
    cw, ch = 540, 600
    d.rounded_rectangle((cx0, cy0, cx0 + cw, cy0 + ch), radius=24, fill=PANEL_BG, outline=ACCENT_VIOLET, width=3)
    f_h3 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=28)
    f_h4 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22)
    f_h5 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=56)

    d.text((cx0 + 30, cy0 + 30), "Real benchmark on CUAD", fill=ACCENT_VIOLET, font=f_h3)
    d.text((cx0 + 30, cy0 + 80), "10 contracts · 26 questions · Apple M4", fill=TEXT_DIM, font=f_h4)

    # Big number
    d.text((cx0 + 30, cy0 + 140), "0.538", fill=ACCENT_GREEN, font=f_h5)
    d.text((cx0 + 200, cy0 + 165), "precision@k", fill=TEXT_DIM, font=f_h4)
    d.text((cx0 + 30, cy0 + 220), "vs 0.462  naive chunker", fill=TEXT, font=f_h4)
    d.text((cx0 + 30, cy0 + 255), "+7.6pp lift, structure-aware", fill=ACCENT_GREEN, font=f_h4)

    # Other claims
    rows = [
        ("129 tests pass", "0 flakes"),
        ("74.47% coverage", "ruff + mypy --strict clean"),
        ("0 cloud calls", "Local-first, Ollama-powered"),
        ("4 RAGAS metrics", "Faithfulness, relevancy, precision, recall"),
    ]
    yy = cy0 + 320
    for left, right in rows:
        d.text((cx0 + 30, yy), "✓", fill=ACCENT_GREEN, font=f_h4)
        d.text((cx0 + 60, yy), left, fill=TEXT, font=f_h4)
        d.text((cx0 + 60, yy + 28), right, fill=TEXT_DIM, font=f_h4)
        yy += 64

    out = OUT / "hero.png"
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out


# ---- ARCHITECTURE INFOGRAPHIC ------------------------------------------------

def render_architecture() -> Path:
    W, H = 1600, 1000
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    soft_glow(img, 800, 500, 500, ACCENT_BLUE, 0.15)

    d = ImageDraw.Draw(img)
    f_h1 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=56)
    f_h2 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=28)
    f_h3 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=26)
    f_h4 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22)

    d.text((100, 60), "How firm-bot works", fill=ACCENT_BLUE, font=f_h1)
    d.text((100, 145), "Six stages. One local box. Zero cloud calls.", fill=TEXT_DIM, font=f_h2)

    stages = [
        ("1. Ingest", "PDF · EML · DOCX", "pypdf · email parser · python-docx · Tesseract OCR fallback", ACCENT_BLUE),
        ("2. Chunk", "Structure-aware", "Article § · Section · Title Case · WHEREAS · sentence boundary", ACCENT_VIOLET),
        ("3. Embed + index", "Per-firm store", "sentence-transformers + Chroma + BM25 pickle", ACCENT_GREEN),
        ("4. Retrieve", "Hybrid RRF", "BM25 + dense via Reciprocal Rank Fusion, k=60", ACCENT_AMBER),
        ("5. Answer", "Citation-required prompt", "qwen2.5-coder:14b · every claim must carry [file:p.4]", ACCENT_BLUE),
        ("6. Guard", "LLM-as-judge", "7B judge audits each citation; flags ungrounded claims", ACCENT_VIOLET),
    ]

    # Two columns of three
    col_w = 700
    row_h = 230
    for i, (title, sub, body, color) in enumerate(stages):
        col = i % 2
        row = i // 2
        x0 = 80 + col * (col_w + 40)
        y0 = 240 + row * (row_h + 20)
        d.rounded_rectangle((x0, y0, x0 + col_w, y0 + row_h), radius=18, fill=PANEL_BG, outline=color, width=3)
        d.text((x0 + 28, y0 + 24), title, fill=color, font=f_h3)
        d.text((x0 + 28, y0 + 70), sub, fill=TEXT, font=f_h3)
        # wrap body manually
        words = body.split()
        line = ""
        yy = y0 + 130
        for w in words:
            if len(line) + len(w) + 1 > 60:
                d.text((x0 + 28, yy), line, fill=TEXT_DIM, font=f_h4)
                yy += 30
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            d.text((x0 + 28, yy), line, fill=TEXT_DIM, font=f_h4)

    # Bottom strip
    d.text((100, 940), "github.com/Mine-FNL/firm-bot  ·  MIT  ·  Python 3.11+  ·  Ollama-powered", fill=ACCENT_VIOLET, font=f_h2)

    out = OUT / "architecture.png"
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out


# ---- COMPARISON INFOGRAPHIC --------------------------------------------------

def render_comparison() -> Path:
    W, H = 1600, 1000
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    soft_glow(img, 800, 300, 380, ACCENT_BLUE, 0.16)
    soft_glow(img, 800, 800, 400, ACCENT_GREEN, 0.13)

    d = ImageDraw.Draw(img)
    f_h1 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=52)
    f_h2 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=28)
    f_h3 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=24)
    f_h4 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=20)

    d.text((100, 60), "Why local-first wins for legal & audit", fill=ACCENT_BLUE, font=f_h1)
    d.text((100, 130), "Cloud RAG vs. firm-bot, side by side.", fill=TEXT_DIM, font=f_h2)

    cols = [
        ("Dimension", TEXT_DIM),
        ("Cloud RAG (Harvey, Spellbook, Glean)", RED_NO),
        ("firm-bot", ACCENT_GREEN),
    ]
    col_w = 470
    x0 = 80
    for i, (label, color) in enumerate(cols):
        x = x0 + i * col_w
        d.text((x, 200), label, fill=color, font=f_h3)

    rows = [
        ("Where your contracts live", "Vendor SaaS, multi-tenant", "Your box, your disk"),
        ("Who sees your queries", "Vendor + their subprocessors", "Only you"),
        ("Pricing model", "$100–$1,000+ / user / month", "Free, MIT licensed"),
        ("Citations required", "Often optional or paid", "Every claim, enforced"),
        ("Network requirement", "Internet for every query", "Air-gappable"),
        ("Model choice", "Vendor picks; vendor locks you", "Any Ollama model — swap freely"),
        ("Audit trail", "Vendor's logging", "Your logs, your retention"),
        ("Compliance burden", "DPA + vendor risk review", "Self-hosted, no vendor"),
        ("Offline usable", "No", "Yes"),
        ("Open source", "No", "Yes (MIT)"),
    ]

    yy = 260
    for i, (dim, cloud, ours) in enumerate(rows):
        if i % 2 == 0:
            d.rectangle((x0 - 8, yy - 8, x0 + 3 * col_w + 8, yy + 70), fill=(20, 30, 50))
        d.text((x0, yy), dim, fill=TEXT, font=f_h3)
        d.text((x0 + col_w, yy), cloud, fill=RED_NO, font=f_h4)
        d.text((x0 + 2 * col_w, yy), ours, fill=ACCENT_GREEN, font=f_h4)
        yy += 70

    out = OUT / "comparison.png"
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out


# ---- WHY LOCAL INFOGRAPHIC ---------------------------------------------------

def render_why_local() -> Path:
    W, H = 1600, 1000
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    soft_glow(img, 800, 500, 500, ACCENT_GREEN, 0.18)

    d = ImageDraw.Draw(img)
    f_h1 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=72)
    f_h2 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=32)
    f_h3 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=28)
    f_h4 = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22)

    d.text((100, 100), "Your client's contracts", fill=TEXT, font=f_h1)
    d.text((100, 200), "shouldn't be training someone else's model.", fill=ACCENT_GREEN, font=f_h2)

    # Four panels
    panels = [
        ("\ud83d\udee1", "Privilege preservation", "Attorney-client privilege evaporates the moment privileged docs touch a vendor's vector index. Self-hosting keeps the chain of custody in your hands."),
        ("\ud83d\udcca", "Regulatory posture", "GDPR, HIPAA, SOC2 — every cloud vendor adds a third party to your compliance review. firm-bot removes the third party."),
        ("\ud83d\udcb0", "Cost", "$100/user/month adds up. firm-bot is MIT — pay only for the hardware you already own."),
        ("\ud83d\udd0f", "Audit trail", "Your logs, your retention, your forensic story. Vendor logs are whatever the vendor keeps."),
    ]
    panel_w = 720
    panel_h = 280
    for i, (icon, title, body) in enumerate(panels):
        col = i % 2
        row = i // 2
        x = 100 + col * (panel_w + 40)
        y = 320 + row * (panel_h + 30)
        d.rounded_rectangle((x, y, x + panel_w, y + panel_h), radius=24, fill=PANEL_BG, outline=ACCENT_GREEN, width=3)
        d.text((x + 28, y + 24), title, fill=ACCENT_GREEN, font=f_h3)
        # wrap
        words = body.split()
        line = ""
        yy = y + 80
        for w in words:
            if len(line) + len(w) + 1 > 50:
                d.text((x + 28, yy), line, fill=TEXT, font=f_h4)
                yy += 30
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            d.text((x + 28, yy), line, fill=TEXT, font=f_h4)

    d.text((100, 920), "github.com/Mine-FNL/firm-bot", fill=ACCENT_BLUE, font=f_h2)

    out = OUT / "why_local.png"
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out


if __name__ == "__main__":
    for fn in (render_hero, render_architecture, render_comparison, render_why_local):
        p = fn()
        print(f"wrote {p} ({p.stat().st_size:,} bytes)")