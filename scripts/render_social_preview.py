"""Render the GitHub social-preview image (1280x640 PNG).

Hand-rolled with Pillow — no external SVG renderer. Run from the
firm-bot repo root:

    python3 scripts/render_social_preview.py

Outputs `docs/assets/social-preview.png`. Commit and push, then set it
as the repo's social preview via:

    gh repo edit Mine-FNL/firm-bot --social-preview docs/assets/social-preview.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 640

# ---- palette ----------------------------------------------------------------
BG_TOP = (15, 23, 42)       # slate-950
BG_BOTTOM = (30, 41, 90)    # indigo-950 with a hint of slate
ACCENT = (96, 165, 250)     # blue-400
ACCENT_2 = (167, 139, 250)  # violet-400
TEXT = (226, 232, 240)      # slate-200
TEXT_DIM = (148, 163, 184)  # slate-400
PILL_BG = (30, 41, 59)      # slate-800


def find_font(*candidates: str, size: int) -> ImageFont.FreeTypeFont:
    """Return the first font that loads, else the default bitmap font."""
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


def draw_glow(img: Image.Image, cx: int, cy: int, r: int, color: tuple[int, int, int], alpha: float = 0.18) -> None:
    """Paint a soft circular glow by alpha-blending onto the image."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for k in range(6, 0, -1):
        rr = int(r * (k / 6))
        a = int(alpha * 255 * (k / 6))
        od.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=color + (a,))
    img.alpha_composite(overlay)


def draw_pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], text: str, font: ImageFont.FreeTypeFont) -> None:
    x0, y0, x1, y1 = xy
    radius = (y1 - y0) // 2
    draw.rounded_rectangle(xy, radius=radius, fill=PILL_BG, outline=ACCENT, width=1)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x0 + (x1 - x0 - tw) // 2 - bbox[0]
    ty = y0 + (y1 - y0 - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=TEXT, font=font)


def main() -> Path:
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")

    # Decorative glows
    draw_glow(img, cx=240, cy=180, r=260, color=ACCENT, alpha=0.20)
    draw_glow(img, cx=1080, cy=520, r=320, color=ACCENT_2, alpha=0.18)

    draw = ImageDraw.Draw(img)

    # Fonts
    f_logo = find_font(
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        size=128,
    )
    f_tagline = find_font(
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        size=32,
    )
    f_pill = find_font(
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        size=22,
    )
    f_small = find_font(
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        size=20,
    )

    # Left side: logo + tagline + pills
    draw.text((80, 170), "firm-bot", fill=ACCENT, font=f_logo)

    # Tagline
    draw.text((84, 320), "Local-first RAG for professional services.", fill=TEXT, font=f_tagline)
    draw.text((84, 360), "Citations required. Your data never leaves the box.", fill=TEXT_DIM, font=f_tagline)

    # Pills row
    pill_y = 430
    pill_h = 50
    pad = 14
    pills = ["Citations required", "Ollama-powered", "Multi-tenant", "MIT licensed"]
    cursor_x = 84
    for label in pills:
        bbox = draw.textbbox((0, 0), label, font=f_pill)
        w = bbox[2] - bbox[0] + 32
        draw_pill(draw, (cursor_x, pill_y, cursor_x + w, pill_y + pill_h), label, f_pill)
        cursor_x += w + pad

    # Bottom strip: stack labels
    draw.text((84, 540), "PDF · EML · DOCX  →  chunker  →  BM25 + dense  →  guard  →  answer", fill=TEXT_DIM, font=f_small)
    draw.text((84, 575), "github.com/Mine-FNL/firm-bot", fill=ACCENT_2, font=f_small)

    # Right side: stylized citation marker illustration
    # Draw a stack of "source cards" with bracket citations
    card_x = 760
    card_y = 130
    card_w = 440
    card_h = 380
    radius = 18

    # Card background
    draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), radius=radius, fill=(15, 23, 42), outline=ACCENT, width=2)

    # Citation header inside the card
    draw.text((card_x + 28, card_y + 26), "Q: What's the cap on liability?", fill=TEXT, font=f_tagline)

    # Answer body (multi-line, looks like a real LLM response)
    lines = [
        "The cap on liability is the fees paid by Client",
        "in the twelve (12) months preceding the claim.",
        "[acme_msa.pdf:p.1]",
        "",
        "This applies to both direct and indirect",
        "damages, excluding gross negligence.",
        "[acme_msa.pdf:p.2]",
    ]
    line_y = card_y + 90
    for i, line in enumerate(lines):
        color = ACCENT if line.startswith("[") and line.endswith("]") else TEXT
        draw.text((card_x + 28, line_y), line, fill=color, font=f_small)
        line_y += 32

    # Guard badge
    badge_x = card_x + card_w - 130
    badge_y = card_y + card_h - 50
    draw.rounded_rectangle((badge_x, badge_y, badge_x + 110, badge_y + 30), radius=15, fill=(34, 197, 94), outline=None)
    draw.text((badge_x + 16, badge_y + 4), "✓ cited", fill=(15, 23, 42), font=f_small)

    out = Path("docs/assets/social-preview.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out


if __name__ == "__main__":
    p = main()
    print(f"wrote {p} ({p.stat().st_size:,} bytes)")