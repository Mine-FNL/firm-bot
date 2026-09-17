"""Render the benchmark chart — firm_bot vs naive vs other baselines.

Output: docs/assets/marketing/benchmark.png (1600x900)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("docs/assets/marketing")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1600, 900
BG_TOP = (15, 23, 42)
BG_BOTTOM = (30, 27, 75)
ACCENT_BLUE = (96, 165, 250)
ACCENT_GREEN = (74, 222, 128)
TEXT = (241, 245, 249)
TEXT_DIM = (148, 163, 184)
RED_NO = (239, 68, 68)
PANEL_BG = (30, 41, 59)


def find_font(*c: str, size: int) -> ImageFont.FreeTypeFont:
    for path in c:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def vertical_gradient(size, top, bottom):
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


def render() -> Path:
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    d = ImageDraw.Draw(img)

    f_title = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=52)
    f_sub = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=28)
    f_axis = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22)
    f_bar = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=36)
    f_small = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=20)
    f_legend = find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22)

    d.text((80, 60), "CUAD benchmark — precision@k", fill=ACCENT_BLUE, font=f_title)
    d.text((80, 130), "10 contracts · 26 questions · Apple M4 · all-MiniLM-L6-v2", fill=TEXT_DIM, font=f_sub)

    # Chart area
    chart_x0 = 100
    chart_y0 = 240
    chart_w = 1300
    chart_h = 500
    d.rectangle((chart_x0 - 4, chart_y0 - 4, chart_x0 + chart_w + 4, chart_y0 + chart_h + 4), outline=PANEL_BG, width=2)

    # Y-axis ticks at 0.0, 0.2, 0.4, 0.6
    y_max = 0.6
    for tick in [0.0, 0.2, 0.4, 0.6]:
        y = chart_y0 + chart_h - int((tick / y_max) * chart_h)
        d.line((chart_x0, y, chart_x0 + chart_w, y), fill=(50, 60, 80), width=1)
        d.text((chart_x0 - 60, y - 12), f"{tick:.1f}", fill=TEXT_DIM, font=f_small)
    d.text((20, chart_y0 + chart_h // 2 - 30), "precision@k", fill=TEXT_DIM, font=f_small)

    # Bars
    bars = [
        ("naive\n(sliding)", 0.462, RED_NO),
        ("BM25 only", 0.448, (200, 100, 100)),
        ("dense only", 0.481, (180, 130, 90)),
        ("BM25 + dense\n(no rerank)", 0.510, (200, 180, 90)),
        ("firm_bot\n(smart chunker)", 0.538, ACCENT_GREEN),
        ("firm_bot + rerank", 0.538, (60, 180, 100)),
    ]
    bar_w = 160
    gap = (chart_w - bar_w * len(bars)) // (len(bars) + 1)
    for i, (label, val, color) in enumerate(bars):
        x = chart_x0 + gap + i * (bar_w + gap)
        bar_h = int((val / y_max) * chart_h)
        y_top = chart_y0 + chart_h - bar_h
        d.rounded_rectangle((x, y_top, x + bar_w, chart_y0 + chart_h), radius=8, fill=color)
        # value label above bar
        d.text((x + bar_w // 2 - 28, y_top - 50), f"{val:.3f}", fill=TEXT, font=f_bar)
        # bar label below
        for j, line in enumerate(label.split("\n")):
            d.text((x + 14, chart_y0 + chart_h + 16 + j * 28), line, fill=TEXT, font=f_axis)

    # Highlight the lift
    d.text((80, 820), "+7.6pp lift vs naive chunker  ·  +5.6pp vs dense-only  ·  reranker adds zero on this fixture", fill=ACCENT_GREEN, font=f_legend)

    out = OUT / "benchmark.png"
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out


if __name__ == "__main__":
    p = render()
    print(f"wrote {p} ({p.stat().st_size:,} bytes)")