"""Render the three explainer videos.

  1. why-firm-bot.mp4  (45s) — pain point: cloud RAG fails compliance
  2. what-is-it.mp4     (40s) — six-stage pipeline + chat card
  3. magic-sauce.mp4    (50s) — three technical differentiators

Same palette + typography + 1920x1080 + 24fps as demo-video.mp4.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont

OUT = Path("docs/assets/marketing")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080

BG_TOP = (15, 23, 42)
BG_BOTTOM = (30, 27, 75)
PANEL = (30, 41, 59)
BORDER = (71, 85, 105)
TEXT = (241, 245, 249)
DIM = (148, 163, 184)
BLUE = (96, 165, 250)
VIOLET = (167, 139, 250)
GREEN = (74, 222, 128)
AMBER = (251, 191, 36)
RED = (239, 68, 68)
TERMINAL_BG = (12, 12, 16)


def find_font(*c: str, size: int) -> ImageFont.FreeTypeFont:
    for path in c:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F = {
    "huge":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=180),
    "h1":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=92),
    "h2":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=56),
    "h3":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=44),
    "body":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=36),
    "small":  find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=28),
    "tiny":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22),
    "mono_lg": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=44),
    "mono_md": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=32),
    "mono_sm": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=24),
}


def gradient(size, top, bottom):
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


def glow(img, cx, cy, r, color, alpha=0.20):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for k in range(6, 0, -1):
        rr = int(r * (k / 6))
        a = int(alpha * 255 * (k / 6))
        od.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=color + (a,))
    img.alpha_composite(overlay)


def encode(frames: Iterator[Image.Image], out_path: Path, fps: int = 24) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "mjpeg",
        "-framerate", str(fps), "-i", "-",
        "-vcodec", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "23",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for img in frames:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=88)
        proc.stdin.write(buf.getvalue())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.returncode}")


def end_card(title: str, subtitle: str) -> Iterator[Image.Image]:
    """Reusable 3-second end card."""
    for _ in range(72):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 480, GREEN, 0.18)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 320, 380), title, fill=GREEN, font=F["h1"])
        d.text((W // 2 - 320, 500), subtitle, fill=DIM, font=F["body"])
        d.text((W // 2 - 320, 620), "github.com/Mine-FNL/firm-bot", fill=VIOLET, font=F["h3"])
        yield img


# ============================================================================
# Video 1: why-firm-bot (45s = 1080 frames)
# Pain point: cloud RAG fails compliance review
# ============================================================================

def video_why() -> Iterator[Image.Image]:
    # Act 1: lawyer at 11pm (12s = 288 frames)
    for f in range(288):
        img = Image.new("RGB", (W, H), (10, 14, 26))
        d = ImageDraw.Draw(img)

        # Wall clock: 11:47 PM
        t = min(1.0, f / 60)
        clock_x, clock_y = W // 2, 320
        d.ellipse((clock_x - 200, clock_y - 200, clock_x + 200, clock_y + 200), outline=DIM, width=4)
        # Hour hand
        d.line((clock_x, clock_y, clock_x, clock_y - 100), fill=TEXT, width=8)
        # Minute hand — animates from 11:47 → 11:53
        minute_angle = -90 + (f / 288) * 30  # 30 degrees over the act
        import math
        mx = clock_x + 160 * math.cos(math.radians(minute_angle))
        my = clock_y + 160 * math.sin(math.radians(minute_angle))
        d.line((clock_x, clock_y, mx, my), fill=BLUE, width=6)

        # Caption
        d.text((clock_x - 200, clock_y + 240), "Friday, 11:47 PM", fill=DIM, font=F["body"])
        d.text((W // 2 - 380, clock_y + 320), '"What is the cap on liability in this contract?"', fill=TEXT, font=F["h3"])

        if f > 144:
            d.text((W // 2 - 280, clock_y + 440), "— your client, just now", fill=DIM, font=F["small"])
        yield img

    # Act 2: cloud RAG path (16s = 384 frames)
    for f in range(384):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, 480, 540, 380, RED, 0.18)
        d = ImageDraw.Draw(img)

        d.text((100, 80), "The cloud RAG path", fill=RED, font=F["h2"])
        d.text((100, 150), "Every query leaves your perimeter.", fill=DIM, font=F["body"])

        # Animated flow: question → vendor LLM → subprocessors → ??? → ?
        stages = [
            (200, "Question", DIM),
            (520, "Vendor LLM", RED),
            (840, "Subprocessors", RED),
            (1160, "Audit logs", RED),
            (1480, "Your data", AMBER),
            (1800, "Compliance?", AMBER),
        ]
        y = 540
        for i, (x, label, color) in enumerate(stages):
            d.rounded_rectangle((x - 110, y - 50, x + 110, y + 50), radius=12, fill=PANEL, outline=color, width=3)
            d.text((x - 90, y - 16), label, fill=color, font=F["small"])

        # Animate the question flowing across
        flow_t = min(1.0, f / 200)
        flow_x = int(200 + flow_t * (1800 - 200))
        d.ellipse((flow_x - 24, y - 24, flow_x + 24, y + 24), fill=BLUE)

        # Checklist at bottom
        cy = 800
        checks = [
            ("DPA review", False),
            ("Subprocessor list", False),
            ("Audit trail ownership", False),
            ("Vendor risk assessment", False),
        ]
        for i, (label, ok) in enumerate(checks):
            yyy = cy + i * 50
            d.text((140, yyy), "✗" if not ok else "✓", fill=RED if not ok else GREEN, font=F["body"])
            d.text((200, yyy), label, fill=TEXT, font=F["body"])

        yield img

    # Act 3: the alternative (12s = 288 frames)
    for f in range(288):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 500, GREEN, 0.20)
        d = ImageDraw.Draw(img)

        d.text((W // 2 - 460, 260), "What if it never", fill=TEXT, font=F["h1"])
        d.text((W // 2 - 460, 380), "left the box?", fill=GREEN, font=F["h1"])

        d.text((W // 2 - 380, 560), "Same question. Same answer.", fill=DIM, font=F["h2"])
        d.text((W // 2 - 380, 640), "No compliance review.", fill=DIM, font=F["h2"])
        d.text((W // 2 - 380, 720), "No vendor.", fill=DIM, font=F["h2"])

        # End card text fades in
        if f > 100:
            d.text((W // 2 - 380, 880), "→ firm-bot", fill=BLUE, font=F["h1"])
            d.text((W // 2 - 380, 1000), "github.com/Mine-FNL/firm-bot", fill=VIOLET, font=F["body"])
        yield img

    # End card
    yield from end_card("firm-bot", "your data, your box")


# ============================================================================
# Video 2: what-is-it (40s = 960 frames)
# Solution overview: six-stage pipeline + chat card
# ============================================================================

def video_what() -> Iterator[Image.Image]:
    # Title (3s = 72 frames)
    for _ in range(72):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 500, BLUE, 0.20)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 380, 360), "What is firm-bot?", fill=BLUE, font=F["h1"])
        d.text((W // 2 - 380, 500), "Local-first RAG. Six stages. Zero cloud.", fill=DIM, font=F["h3"])
        yield img

    # Pipeline animation (24s = 576 frames)
    stages = [
        ("Ingest", "PDF · EML · DOCX", BLUE),
        ("Chunk", "structure-aware", VIOLET),
        ("Embed", "all-MiniLM-L6-v2", GREEN),
        ("Retrieve", "BM25 + dense RRF", AMBER),
        ("Answer", "qwen2.5-coder:14b", BLUE),
        ("Guard", "7B LLM-as-judge", VIOLET),
    ]
    panel_w = 270
    gap = 32
    total_w = len(stages) * panel_w + (len(stages) - 1) * gap
    start_x = (W - total_w) // 2
    panel_y = 380
    panel_h = 280

    for f in range(576):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 500, BLUE, 0.12)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 320, 140), "The pipeline", fill=BLUE, font=F["h2"])
        d.text((W // 2 - 280, 220), "Six stages. One box. No cloud calls.", fill=DIM, font=F["body"])

        # Per-stage progress: stages light up sequentially
        for i, (title, sub, color) in enumerate(stages):
            x = start_x + i * (panel_w + gap)
            lit = f > i * 90
            # Pulse highlight on currently-lit
            current = i == min(len(stages) - 1, f // 90)
            border_w = 5 if current else 3
            d.rounded_rectangle((x, panel_y, x + panel_w, panel_y + panel_h), radius=18, fill=PANEL, outline=color, width=border_w)

            if lit:
                # Step number + title
                d.text((x + 20, panel_y + 24), f"{i+1}.", fill=color, font=F["h2"])
                d.text((x + 80, panel_y + 30), title, fill=TEXT, font=F["h3"])
                d.text((x + 20, panel_y + 110), sub, fill=DIM, font=F["small"])
                # Active flow indicator
                if current:
                    pulse = abs(((f % 60) - 30)) / 30  # 0..1..0
                    d.ellipse((x + panel_w // 2 - 16, panel_y + 200, x + panel_w // 2 + 16, panel_y + 232), fill=color)
                    d.ellipse((x + panel_w // 2 - 8 - int(pulse * 12), panel_y + 208 - int(pulse * 12), x + panel_w // 2 + 8 + int(pulse * 12), panel_y + 224 + int(pulse * 12)), outline=color, width=2)
            else:
                d.text((x + 20, panel_y + 30), f"{i+1}. {title}", fill=DIM, font=F["h3"])

            # Arrow between panels
            if i < len(stages) - 1 and lit and f > (i + 1) * 90 - 30:
                ax = x + panel_w + 4
                d.line((ax, panel_y + panel_h // 2, ax + gap - 8, panel_y + panel_h // 2), fill=color, width=3)
                d.polygon([(ax + gap - 4, panel_y + panel_h // 2 - 8), (ax + gap - 4, panel_y + panel_h // 2 + 8), (ax + gap + 4, panel_y + panel_h // 2)], fill=color)

        # Bottom: the chat card appears after pipeline completes
        if f > 540:
            chat_alpha = min(1.0, (f - 540) / 36)
            d.rounded_rectangle((300, 800, W - 300, 1000), radius=18, fill=PANEL, outline=GREEN, width=3)
            d.text((340, 830), "What's the cap on liability?", fill=BLUE, font=F["body"])
            d.text((340, 890), "The cap on liability is the fees paid in the twelve (12) months", fill=TEXT, font=F["body"])
            d.text((340, 940), "preceding the claim. [acme_msa.pdf:p.1]", fill=VIOLET, font=F["mono_md"])
        yield img

    # Chat card zoom (8s = 192 frames)
    for f in range(192):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 500, GREEN, 0.20)
        d = ImageDraw.Draw(img)

        d.text((100, 80), "The chat card", fill=BLUE, font=F["h2"])
        d.text((100, 150), "Every claim carries a [file:page] marker.", fill=DIM, font=F["body"])

        # Big chat card
        d.rounded_rectangle((180, 240, W - 180, 700), radius=22, fill=PANEL, outline=BORDER, width=2)
        d.text((220, 280), "Q: What's the cap on liability?", fill=BLUE, font=F["h3"])
        d.line((220, 360, W - 220, 360), fill=BORDER, width=1)
        d.text((220, 400), "A: The cap on liability is the fees paid by Client in", fill=TEXT, font=F["body"])
        d.text((220, 460), "the twelve (12) months preceding the claim, except", fill=TEXT, font=F["body"])
        d.text((220, 520), "for claims of gross negligence.", fill=TEXT, font=F["body"])
        d.text((220, 600), "[acme_msa.pdf:p.1]", fill=VIOLET, font=F["mono_lg"])

        # Bottom verdict
        d.rounded_rectangle((W // 2 - 140, 820, W // 2 + 140, 880), radius=30, fill=GREEN)
        d.text((W // 2 - 100, 836), "✓ cited", fill=BG_TOP, font=F["h3"])
        yield img

    # End card
    yield from end_card("That's it.", "local-first RAG, six stages, citations enforced")


# ============================================================================
# Video 3: magic-sauce (50s = 1200 frames)
# Three differentiators in sequence
# ============================================================================

def video_magic() -> Iterator[Image.Image]:
    # Title (3s)
    for _ in range(72):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 500, VIOLET, 0.20)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 380, 360), "The magic sauce", fill=VIOLET, font=F["h1"])
        d.text((W // 2 - 380, 500), "three things cloud RAG can't do", fill=DIM, font=F["h3"])
        yield img

    # Pillar 1: structure-aware chunker (15s = 360 frames)
    for f in range(360):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)
        d.text((100, 80), "1. Structure-aware chunker", fill=VIOLET, font=F["h2"])
        d.text((100, 150), "Recognises Article §, Section, Title Case, WHEREAS.", fill=DIM, font=F["body"])

        # Two columns: naive (left, red) vs smart (right, green)
        col_w = 700
        left_x = 100
        right_x = W - col_w - 100
        col_y = 280
        col_h = 600

        d.rounded_rectangle((left_x, col_y, left_x + col_w, col_y + col_h), radius=18, fill=PANEL, outline=RED, width=3)
        d.text((left_x + 30, col_y + 30), "Naive chunker", fill=RED, font=F["h3"])
        d.text((left_x + 30, col_y + 90), "splits mid-clause", fill=DIM, font=F["body"])

        d.rounded_rectangle((right_x, col_y, right_x + col_w, col_y + col_h), radius=18, fill=PANEL, outline=GREEN, width=3)
        d.text((right_x + 30, col_y + 30), "firm_bot", fill=GREEN, font=F["h3"])
        d.text((right_x + 30, col_y + 90), "respects section boundaries", fill=DIM, font=F["body"])

        # Show the clause text being split differently
        clause = "Section 4.2 — Limitation of Liability. In no event shall either party's total liability exceed the fees paid in the twelve (12) months preceding the event giving rise to the claim, except for claims of gross negligence or willful misconduct. Section 4.3 — Indemnification. Vendor shall indemnify Client against any third-party claims arising from Vendor's gross negligence."

        # Naive: split in middle of Section 4.2 (red highlight on the split)
        # Smart: keep Section 4.2 as one chunk
        # Animate the split
        progress = min(1.0, f / 90)

        # Left column: naive split animation
        naive_split_x = left_x + 30 + int((col_w - 60) * 0.55)
        d.text((left_x + 30, col_y + 160), clause, fill=TEXT, font=F["small"])
        # Red split indicator
        d.line((naive_split_x, col_y + 150, naive_split_x, col_y + 580), fill=RED, width=4)
        d.text((naive_split_x + 8, col_y + 360), "✗ split", fill=RED, font=F["small"])
        d.text((naive_split_x + 8, col_y + 400), "mid-clause", fill=RED, font=F["small"])

        # Right column: smart — no split
        d.text((right_x + 30, col_y + 160), clause, fill=TEXT, font=F["small"])
        # Green check
        d.text((right_x + col_w - 80, col_y + 360), "✓", fill=GREEN, font=F["h1"])
        d.text((right_x + col_w - 80, col_y + 460), "intact", fill=GREEN, font=F["small"])

        # After f > 200, show the number
        if f > 200:
            d.text((left_x + 30, col_y + 620), "0.462 precision@k", fill=RED, font=F["body"])
            d.text((right_x + 30, col_y + 620), "0.538 precision@k", fill=GREEN, font=F["body"])

        yield img

    # Pillar 2: citation-required prompts (15s = 360 frames)
    for f in range(360):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)
        d.text((100, 80), "2. Citation-required prompts", fill=VIOLET, font=F["h2"])
        d.text((100, 150), "Every claim must carry a [file:page] marker.", fill=DIM, font=F["body"])

        # Two chat cards: without (left, red) vs with (right, green)
        # Without: "Yes, liability is uncapped."
        # With: "Liability is uncapped. [msa.pdf:p.4]"
        if f < 180:
            # First show "without", then fade to "with"
            d.rounded_rectangle((200, 280, W - 200, 560), radius=20, fill=PANEL, outline=RED, width=3)
            d.text((240, 320), "Without citation-required:", fill=RED, font=F["h3"])
            d.text((240, 400), '"Yes, liability is uncapped."', fill=TEXT, font=F["h2"])
            d.text((240, 490), "→ which page? which contract?", fill=DIM, font=F["body"])
            if f > 100:
                d.text((W // 2 - 80, 620), "✗", fill=RED, font=F["huge"])
        else:
            t = min(1.0, (f - 180) / 60)
            d.rounded_rectangle((200, 280, W - 200, 560), radius=20, fill=PANEL, outline=GREEN, width=3)
            d.text((240, 320), "With citation-required:", fill=GREEN, font=F["h3"])
            d.text((240, 400), '"Liability is uncapped.', fill=TEXT, font=F["h2"])
            chars_to_show = int(len(" [msa.pdf:p.4]") * t)
            d.text((240, 460), " [msa.pdf:p.4]"[:chars_to_show], fill=VIOLET, font=F["mono_lg"])
            d.text((240, 600), "✓  every claim is auditable", fill=GREEN, font=F["h3"])

        yield img

    # Pillar 3: LLM-as-judge guard (12s = 288 frames)
    for f in range(288):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)
        d.text((100, 80), "3. LLM-as-judge guard", fill=VIOLET, font=F["h2"])
        d.text((100, 150), "A second 7B model audits every answer.", fill=DIM, font=F["body"])

        # An audit appears
        d.rounded_rectangle((200, 280, W - 200, 700), radius=20, fill=PANEL, outline=BORDER, width=2)
        d.text((240, 320), "Audit log:", fill=DIM, font=F["h3"])

        # Three audit lines appear progressively
        audits = [
            (0, GREEN, "✓ 'cap on liability' → cited [acme_msa.pdf:p.1]"),
            (120, GREEN, "✓ 'gross negligence exclusion' → cited [acme_msa.pdf:p.2]"),
            (240, AMBER, "⚠ 'indemnification scope' → judge flagged (ungrounded)"),
        ]
        for start_frame, color, text in audits:
            if f > start_frame:
                t = min(1.0, (f - start_frame) / 30)
                # Type effect
                chars = int(len(text) * t)
                d.text((240, 380 + audits.index((start_frame, color, text)) * 80), text[:chars], fill=color, font=F["body"])

        # Final tally
        if f > 240:
            d.text((W // 2 - 280, 800), "2 cited · 1 flagged", fill=TEXT, font=F["h3"])
            d.text((W // 2 - 280, 870), "→ judge over-flags at 7B; calmer at 14B", fill=DIM, font=F["small"])
        yield img

    # End card
    yield from end_card("129 tests · 0.538 vs 0.462 · MIT", "that's the magic sauce")


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="firm-bot-explainers-"))
    jobs = [
        ("why-firm-bot.mp4", video_why, 1080),
        ("what-is-it.mp4", video_what, 960),
        ("magic-sauce.mp4", video_magic, 1200),
    ]
    for name, builder, n_frames in jobs:
        path = tmp / name
        print(f"  rendering {name} ({n_frames} frames)…", flush=True)
        encode(builder(), path, fps=24)
        final = OUT / name
        shutil.move(str(path), str(final))
        print(f"    → {final.name} ({final.stat().st_size:,} bytes)")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()