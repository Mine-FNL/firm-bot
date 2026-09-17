"""Render the demo GIF: a 6-step UI walkthrough that loops.

Frames depict, at a browser-window scale, what an operator would see:

  0. Browser open at localhost:8000 — drag-drop zone empty
  1. PDF hovering the drop zone
  2. After ingest: small "9 chunks indexed" badge
  3. Question typed in chat
  4. Answer streaming in
  5. Final answer with [acme_msa.pdf:p.1] citation + source pane

Rendered with Pillow at 1200x720, 24 frames per step = 144 frames
total at ~12 FPS → ~12 s loop. Output: docs/assets/marketing/demo.gif.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("docs/assets/marketing")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1200, 720
PALETTE = {
    "bg": (15, 23, 42),
    "panel": (30, 41, 59),
    "border": (71, 85, 105),
    "text": (241, 245, 249),
    "dim": (148, 163, 184),
    "blue": (96, 165, 250),
    "violet": (167, 139, 250),
    "green": (74, 222, 128),
    "amber": (251, 191, 36),
    "red": (239, 68, 68),
}


def find_font(*candidates: str, size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F = {
    "title": find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=24),
    "h1": find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=32),
    "h2": find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22),
    "body": find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=20),
    "small": find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=16),
    "mono": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=18),
    "mono_big": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", size=22),
    "tiny": find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=14),
}


def browser_chrome(img: Image.Image, d: ImageDraw.ImageDraw, title: str = "firm-bot — acme") -> None:
    # Window background already on img; draw the chrome bar
    chrome_h = 56
    d.rectangle((0, 0, W, chrome_h), fill=(40, 40, 45))
    # traffic lights
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((20 + i * 26, 18, 36 + i * 26, 34), fill=color)
    # URL bar
    d.rounded_rectangle((140, 14, W - 30, 42), radius=14, fill=(70, 70, 75))
    d.text((160, 18), f"🔒  http://localhost:8000  ·  acme", fill=(220, 220, 220), font=F["small"])


def app_shell(img: Image.Image, d: ImageDraw.ImageDraw) -> None:
    # Sidebar
    sidebar_w = 240
    d.rectangle((0, 56, sidebar_w, H), fill=(22, 28, 45))
    d.text((24, 80), "firm-bot", fill=PALETTE["blue"], font=F["h1"])
    d.text((24, 130), "Firm: acme LLP", fill=PALETTE["text"], font=F["body"])
    d.text((24, 160), "9 chunks", fill=PALETTE["dim"], font=F["small"])
    d.text((24, 200), "Models", fill=PALETTE["dim"], font=F["small"])
    d.text((24, 224), "  • qwen2.5-coder:14b", fill=PALETTE["text"], font=F["small"])
    d.text((24, 244), "  • judge: 7b", fill=PALETTE["text"], font=F["small"])

    d.text((24, H - 200), "Citations", fill=PALETTE["dim"], font=F["small"])
    d.text((24, H - 175), "100% coverage", fill=PALETTE["green"], font=F["small"])
    d.text((24, H - 150), "p50: 1.4s", fill=PALETTE["text"], font=F["small"])
    d.text((24, H - 130), "p95: 2.2s", fill=PALETTE["text"], font=F["small"])

    # Main panel
    main_x = sidebar_w + 12
    d.rectangle((main_x, 68, W - 12, H - 12), fill=PALETTE["panel"], outline=PALETTE["border"], width=2)


def frame_blank() -> Image.Image:
    img = Image.new("RGB", (W, H), PALETTE["bg"])
    d = ImageDraw.Draw(img)
    browser_chrome(img, d)
    app_shell(img, d)
    return img


def wrap_text(d: ImageDraw.ImageDraw, text: str, x: int, y: int, max_chars: int, line_h: int, font, fill) -> int:
    words = text.split()
    line = ""
    yy = y
    for w in words:
        if len(line) + len(w) + 1 > max_chars:
            d.text((x, yy), line, fill=fill, font=font)
            yy += line_h
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        d.text((x, yy), line, fill=fill, font=font)
        yy += line_h
    return yy


# Frame builders --------------------------------------------------------------

def frame_0() -> Image.Image:
    img = frame_blank()
    d = ImageDraw.Draw(img)
    d.text((290, 110), "Drag PDFs, EML, or DOCX here", fill=PALETTE["text"], font=F["h1"])
    d.text((290, 160), "or click to browse", fill=PALETTE["dim"], font=F["h2"])

    # Drop zone
    x0, y0, x1, y1 = 290, 220, W - 60, 480
    d.rounded_rectangle((x0, y0, x1, y1), radius=18, outline=PALETTE["blue"], width=3)
    d.text((x0 + 40, y0 + 40), "📄", fill=PALETTE["blue"], font=F["h1"])
    d.text((x0 + 40, y0 + 110), "Drop files to ingest", fill=PALETTE["text"], font=F["h2"])
    d.text((x0 + 40, y0 + 150), "PDF · EML · DOCX", fill=PALETTE["dim"], font=F["small"])

    # terminal hint at bottom
    d.text((290, 540), "$ firm-bot serve", fill=PALETTE["violet"], font=F["mono_big"])
    d.text((290, 575), "Uvicorn running on http://127.0.0.1:8000", fill=PALETTE["dim"], font=F["small"])
    d.text((290, 605), "Press Ctrl+C to quit", fill=PALETTE["dim"], font=F["small"])
    return img


def frame_1() -> Image.Image:
    img = frame_0()
    d = ImageDraw.Draw(img)
    # hovered file in the drop zone
    x0, y0, x1, y1 = 290, 220, W - 60, 480
    d.rounded_rectangle((x0 + 20, y0 + 200, x1 - 20, y0 + 240), radius=10, fill=PALETTE["violet"], outline=PALETTE["text"], width=2)
    d.text((x0 + 40, y0 + 208), "📄  acme_msa.pdf  (218 KB)", fill=PALETTE["text"], font=F["body"])
    return img


def frame_2() -> Image.Image:
    img = frame_blank()
    d = ImageDraw.Draw(img)
    d.text((290, 110), "Ingested ✓", fill=PALETTE["green"], font=F["h1"])
    d.text((290, 160), "9 chunks indexed from 2 documents", fill=PALETTE["dim"], font=F["h2"])

    # Stats row
    yy = 220
    for label, val in [("Files", "2"), ("Chunks", "9"), ("Re-ranked", "off"), ("Judge", "ok")]:
        d.rounded_rectangle((290, yy, 540, yy + 90), radius=12, fill=PALETTE["panel"], outline=PALETTE["border"], width=1)
        d.text((310, yy + 12), label, fill=PALETTE["dim"], font=F["small"])
        d.text((310, yy + 36), val, fill=PALETTE["text"], font=F["h1"])
        yy += 100

    d.text((290, 530), "Source preview", fill=PALETTE["text"], font=F["h2"])
    d.text((290, 570), "▸ acme_msa.pdf  (5 sections, p.1–4)", fill=PALETTE["blue"], font=F["body"])
    d.text((290, 600), "▸ nda.pdf  (4 sections, p.1–3)", fill=PALETTE["blue"], font=F["body"])
    return img


def frame_3() -> Image.Image:
    img = frame_blank()
    d = ImageDraw.Draw(img)
    d.text((290, 110), "Ask anything about your firm's documents.", fill=PALETTE["text"], font=F["h2"])

    # Question bubble
    d.rounded_rectangle((310, 200, 1080, 270), radius=14, fill=PALETTE["blue"])
    wrap_text(d, "What's the cap on liability in the MSA?", 330, 222, 50, 30, F["body"], PALETTE["bg"])
    return img


def frame_4() -> Image.Image:
    img = frame_3()
    d = ImageDraw.Draw(img)
    # Answer bubble, partially filled
    d.rounded_rectangle((310, 290, 1080, 460), radius=14, fill=PALETTE["panel"], outline=PALETTE["border"], width=1)
    d.text((330, 305), "Answer", fill=PALETTE["dim"], font=F["small"])
    partial = "The cap on liability in the MSA is the"
    wrap_text(d, partial, 330, 330, 60, 28, F["body"], PALETTE["text"])
    # caret
    d.rectangle((330 + len(partial.split()[-1]) * 12, 330, 330 + len(partial.split()[-1]) * 12 + 4, 358), fill=PALETTE["text"])
    return img


def frame_5() -> Image.Image:
    img = frame_3()
    d = ImageDraw.Draw(img)
    # Full answer bubble
    d.rounded_rectangle((310, 290, 1080, 510), radius=14, fill=PALETTE["panel"], outline=PALETTE["border"], width=1)
    d.text((330, 305), "Answer", fill=PALETTE["dim"], font=F["small"])
    body = (
        "The cap on liability is the fees paid by Client "
        "in the twelve (12) months preceding the claim, "
        "excluding claims arising from gross negligence."
    )
    yy = wrap_text(d, body, 330, 330, 56, 28, F["body"], PALETTE["text"])
    # citation marker, highlighted
    d.text((330, yy + 6), "[acme_msa.pdf:p.1]", fill=PALETTE["violet"], font=F["mono"])

    # Bottom: source pane preview
    d.rounded_rectangle((310, 530, 1080, 660), radius=14, fill=(20, 30, 55), outline=PALETTE["violet"], width=2)
    d.text((330, 545), "Source: acme_msa.pdf  p.1  § 4.2 Limitation of Liability", fill=PALETTE["violet"], font=F["small"])
    excerpt = (
        '"In no event shall either party\u2019s total liability '
        'exceed the fees paid in the twelve (12) months preceding '
        'the event giving rise to the claim, except for claims '
        'of gross negligence or willful misconduct."'
    )
    wrap_text(d, excerpt, 330, 572, 60, 22, F["small"], PALETTE["text"])

    # Guard verdict at the bottom-right corner
    d.rounded_rectangle((970, 670, 1080, 700), radius=12, fill=PALETTE["green"])
    d.text((982, 676), "✓ cited", fill=PALETTE["bg"], font=F["small"])
    return img


def render_gif() -> Path:
    base_frames = [frame_0, frame_1, frame_2, frame_3, frame_4, frame_5]
    # 18 frames per step → smooth ~1.2s per step at 15 fps; 6 steps = 7.2s loop
    per_step = 18
    frames: list[Image.Image] = []
    palette_frames: list[Image.Image] = []
    for builder in base_frames:
        static = builder()
        # quantize once for GIF palette stability
        p = static.convert("P", palette=Image.ADAPTIVE, colors=128)
        for _ in range(per_step):
            frames.append(static.copy())
            palette_frames.append(p.copy())
    out = OUT / "demo.gif"
    palette_frames[0].save(
        out,
        save_all=True,
        append_images=palette_frames[1:],
        duration=80,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return out


if __name__ == "__main__":
    p = render_gif()
    print(f"wrote {p} ({p.stat().st_size:,} bytes, {p.stat().st_size / 1024:.1f} KB)")