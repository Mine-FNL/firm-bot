"""Render the three explainer videos with audio narration + smoother visuals.

Improvements over v1:
  - Audio narration via macOS `say` (Alex voice, US English, default rate)
  - 30fps rendering for smoother motion (was 24fps)
  - H.264 preset slow, crf 18 (was medium, crf 23) — visibly cleaner
  - Smoother animation curves (ease-in-out cubic instead of linear)
  - Slightly larger headline fonts for better small-size legibility
  - Subtle stroke on body text for legibility against busy backgrounds
"""
from __future__ import annotations

import math
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
FPS = 30  # smoother than 24fps
VOICE = "Alex"  # US English male, clear and neutral

# Palette — locked by docs/marketing/DESIGN.md
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


def find_font(*c: str, size: int) -> ImageFont.FreeTypeFont:
    for path in c:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F = {
    "huge":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=200),
    "h1":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=104),
    "h2":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=60),
    "h3":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=48),
    "body":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=38),
    "small":  find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=30),
    "tiny":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=24),
    "mono_lg": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=48),
    "mono_md": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=34),
    "mono_sm": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=26),
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


def ease_in_out_cubic(t: float) -> float:
    """Smoother animation curve than linear."""
    if t < 0.5:
        return 4 * t * t * t
    p = 2 * t - 2
    return 0.5 * p * p * p + 1


def encode_video(frames: Iterator[Image.Image], out_path: Path) -> None:
    """Pipe frames through ffmpeg with high-quality H.264 settings."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "mjpeg",
        "-framerate", str(FPS), "-i", "-",
        "-vcodec", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "slow", "-crf", "18",         # higher quality
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for img in frames:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=92)
        proc.stdin.write(buf.getvalue())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.returncode}")


def mux_audio(video_path: Path, audio_text: str, out_path: Path, voice: str = VOICE) -> None:
    """Generate audio with macOS `say` and mux into the video."""
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as af:
        audio_aiff = Path(af.name)
    try:
        # Generate narration
        r = subprocess.run(
            ["say", "-v", voice, "-o", str(audio_aiff), audio_text],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"say failed: {r.stderr}")
        # Get durations
        def dur(p: Path) -> float:
            out = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p),
            ], text=True).strip()
            return float(out)
        v_dur = dur(video_path)
        a_dur = dur(audio_aiff)
        # Stretch audio to video length (apad + atempo, or just trim/pad with -shortest)
        # Simplest: pad with silence to video length
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-i", str(audio_aiff),
            "-filter_complex", f"[1:a]apad=whole_dur={v_dur}[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
    finally:
        audio_aiff.unlink(missing_ok=True)


def text_with_stroke(d, xy, text, font, fill, stroke=BG_TOP, stroke_w=2):
    """Render text with a thin dark stroke for legibility."""
    d.text(xy, text, fill=stroke, font=font, stroke_width=stroke_w)
    d.text(xy, text, fill=fill, font=font)


def end_card(title: str, subtitle: str, n_frames: int = 90) -> Iterator[Image.Image]:
    """Reusable end card with cross-fade in."""
    for f in range(n_frames):
        # Title fades in over first 30 frames
        title_alpha = min(1.0, f / 30)
        sub_alpha = min(1.0, max(0, (f - 15) / 30))
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 520, GREEN, 0.20 * title_alpha)
        d = ImageDraw.Draw(img)

        if title_alpha > 0.1:
            d.text((W // 2 - 360, 380), title, fill=GREEN, font=F["h1"])
        if sub_alpha > 0.1:
            d.text((W // 2 - 360, 520), subtitle, fill=DIM, font=F["body"])
            d.text((W // 2 - 360, 640), "github.com/Mine-FNL/firm-bot", fill=VIOLET, font=F["h3"])
        yield img


# ============================================================================
# Video 1: why-firm-bot (50s = 1500 frames @ 30fps)
# ============================================================================

WHY_SCRIPT = """Friday night. Eleven forty-seven PM. Your client just sent a contract question. You need an answer fast. But the only tool you trust is cloud-based. Every question leaves your network. Vendor large language model. Then subprocessors. Then audit logs. By the time you ask one question, four third parties have seen privileged work product. Compliance review fails. You can't deploy it. The market for legal AI is ninety percent cloud. The remaining ten percent is what we built. Firm-bot. Local first. Citations required. Your data, your box."""


def video_why() -> Iterator[Image.Image]:
    # Act 1: lawyer at 11pm (15s = 450 frames)
    for f in range(450):
        img = Image.new("RGB", (W, H), (10, 14, 26))
        d = ImageDraw.Draw(img)

        t = min(1.0, f / 90)
        ease_t = ease_in_out_cubic(t)
        clock_x, clock_y = W // 2, 360
        d.ellipse((clock_x - 220, clock_y - 220, clock_x + 220, clock_y + 220), outline=DIM, width=5)
        # Hour hand
        d.line((clock_x, clock_y, clock_x, clock_y - 110), fill=TEXT, width=10)
        # Minute hand — animates
        minute_angle = -90 + ease_t * 30
        mx = clock_x + 175 * math.cos(math.radians(minute_angle))
        my = clock_y + 175 * math.sin(math.radians(minute_angle))
        d.line((clock_x, clock_y, mx, my), fill=BLUE, width=8)
        # Second hand
        sec_angle = -90 + (f / 30) * 360 % 360
        sx = clock_x + 195 * math.cos(math.radians(sec_angle))
        sy = clock_y + 195 * math.sin(math.radians(sec_angle))
        d.line((clock_x, clock_y, sx, sy), fill=RED, width=3)

        d.text((clock_x - 220, clock_y + 280), "Friday, 11:47 PM", fill=DIM, font=F["body"])
        text_with_stroke(d, (W // 2 - 460, clock_y + 380), '"What is the cap on liability in this contract?"', F["h3"], TEXT)
        if f > 200:
            d.text((W // 2 - 320, clock_y + 500), "— your client, just now", fill=DIM, font=F["small"])
        yield img

    # Act 2: cloud RAG path (20s = 600 frames)
    for f in range(600):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, 480, 540, 400, RED, 0.20)
        d = ImageDraw.Draw(img)

        d.text((100, 80), "The cloud RAG path", fill=RED, font=F["h2"])
        d.text((100, 160), "Every query leaves your perimeter.", fill=DIM, font=F["body"])

        stages = [
            (200, "Question", DIM),
            (520, "Vendor LLM", RED),
            (840, "Subprocessors", RED),
            (1160, "Audit logs", RED),
            (1480, "Your data", AMBER),
            (1800, "Compliance?", AMBER),
        ]
        y = 560
        for x, label, color in stages:
            d.rounded_rectangle((x - 130, y - 60, x + 130, y + 60), radius=16, fill=PANEL, outline=color, width=4)
            text_with_stroke(d, (x - 110, y - 22), label, F["small"], color)

        # Animate the question flowing across (eased)
        flow_t = ease_in_out_cubic(min(1.0, f / 220))
        flow_x = int(200 + flow_t * (1800 - 200))
        d.ellipse((flow_x - 30, y - 30, flow_x + 30, y + 30), fill=BLUE)
        d.ellipse((flow_x - 50, y - 50, flow_x + 50, y + 50), outline=BLUE, width=2)

        # Compliance checklist
        cy = 840
        checks = [
            ("DPA review", False),
            ("Subprocessor list", False),
            ("Audit trail ownership", False),
            ("Vendor risk assessment", False),
        ]
        for i, (label, ok) in enumerate(checks):
            yyy = cy + i * 56
            d.text((140, yyy), "✗", fill=RED, font=F["h3"])
            d.text((220, yyy), label, fill=TEXT, font=F["body"])

        yield img

    # Act 3: the alternative (12s = 360 frames)
    for f in range(360):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 540, GREEN, 0.22)
        d = ImageDraw.Draw(img)

        d.text((W // 2 - 480, 280), "What if it never", fill=TEXT, font=F["h1"])
        d.text((W // 2 - 480, 420), "left the box?", fill=GREEN, font=F["h1"])

        d.text((W // 2 - 380, 600), "Same question. Same answer.", fill=DIM, font=F["h2"])
        d.text((W // 2 - 380, 690), "No compliance review.", fill=DIM, font=F["h2"])
        d.text((W // 2 - 380, 780), "No vendor.", fill=DIM, font=F["h2"])

        if f > 120:
            arrow_alpha = min(1.0, (f - 120) / 40)
            d.text((W // 2 - 380, 900), "→ firm-bot", fill=BLUE, font=F["h1"])
            d.text((W // 2 - 380, 1020), "github.com/Mine-FNL/firm-bot", fill=VIOLET, font=F["body"])
        yield img

    # End card
    yield from end_card("firm-bot", "your data, your box", n_frames=120)


# ============================================================================
# Video 2: what-is-it (45s = 1350 frames @ 30fps)
# ============================================================================

WHAT_SCRIPT = """What is firm-bot? A local-first chat-bot builder for professional services. Six stages. Zero cloud calls. Stage one: ingest. PDFs, email, DOCX. Stage two: chunk. Structure aware. Recognises article, section, title case. Stage three: embed. Local sentence transformers. Stage four: retrieve. BM-25 plus dense, fused with reciprocal rank fusion. Stage five: answer. Citation required. Every claim must carry a file and page marker. Stage six: guard. A second model audits the answer and flags ungrounded claims. The chat card. Every claim carries a source. That's it."""


def video_what() -> Iterator[Image.Image]:
    # Title (3s)
    for _ in range(90):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 540, BLUE, 0.22)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 400, 380), "What is firm-bot?", fill=BLUE, font=F["h1"])
        d.text((W // 2 - 320, 520), "Local-first RAG. Six stages. Zero cloud.", fill=DIM, font=F["h3"])
        yield img

    # Pipeline animation (28s = 840 frames)
    stages = [
        ("Ingest", "PDF · EML · DOCX", BLUE),
        ("Chunk", "structure-aware", VIOLET),
        ("Embed", "all-MiniLM-L6-v2", GREEN),
        ("Retrieve", "BM25 + dense RRF", AMBER),
        ("Answer", "qwen2.5-coder:14b", BLUE),
        ("Guard", "7B LLM-as-judge", VIOLET),
    ]
    panel_w = 290
    gap = 40
    total_w = len(stages) * panel_w + (len(stages) - 1) * gap
    start_x = (W - total_w) // 2
    panel_y = 400
    panel_h = 300

    for f in range(840):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 540, BLUE, 0.14)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 340, 140), "The pipeline", fill=BLUE, font=F["h2"])
        d.text((W // 2 - 300, 230), "Six stages. One box. No cloud calls.", fill=DIM, font=F["body"])

        for i, (title, sub, color) in enumerate(stages):
            x = start_x + i * (panel_w + gap)
            stage_start = i * 140
            lit_t = max(0, min(1, (f - stage_start) / 50))
            lit = lit_t > 0.5
            current = lit and (i == len(stages) - 1 or f < (i + 1) * 140)
            border_w = 5 if current else 3

            # Smoother fade-in: ease-in-out
            alpha = ease_in_out_cubic(lit_t) if not lit else 1.0
            panel_color = tuple(int(c * alpha + PANEL[i] * (1 - alpha)) for i, c in enumerate(PANEL)) if alpha < 1 else PANEL

            d.rounded_rectangle((x, panel_y, x + panel_w, panel_y + panel_h), radius=20, fill=panel_color, outline=color, width=border_w)

            if lit:
                d.text((x + 24, panel_y + 28), f"{i+1}.", fill=color, font=F["h2"])
                d.text((x + 90, panel_y + 36), title, fill=TEXT, font=F["h3"])
                d.text((x + 24, panel_y + 124), sub, fill=DIM, font=F["small"])
                if current:
                    # Smoother pulse
                    pulse = abs(((f % 70) - 35)) / 35
                    pulse_r = int(8 + pulse * 14)
                    cx_p = x + panel_w // 2
                    cy_p = panel_y + 220
                    d.ellipse((cx_p - 18, cy_p, cx_p + 18, cy_p + 36), fill=color)
                    d.ellipse((cx_p - pulse_r, cy_p + 18 - pulse_r, cx_p + pulse_r, cy_p + 18 + pulse_r), outline=color, width=2)
            else:
                dim_color = tuple(int(c * 0.4) for c in DIM)
                d.text((x + 24, panel_y + 36), f"{i+1}. {title}", fill=dim_color, font=F["h3"])

            if i < len(stages) - 1 and lit and f > (i + 1) * 140 - 20:
                arrow_t = ease_in_out_cubic(min(1.0, (f - ((i + 1) * 140 - 20)) / 30))
                ax = x + panel_w + 8
                d.line((ax, panel_y + panel_h // 2, ax + (gap - 16) * arrow_t, panel_y + panel_h // 2), fill=color, width=4)
                d.polygon([(ax + (gap - 16) * arrow_t, panel_y + panel_h // 2 - 10), (ax + (gap - 16) * arrow_t, panel_y + panel_h // 2 + 10), (ax + (gap - 4) * arrow_t + 4, panel_y + panel_h // 2)], fill=color)

        # Chat card fades in at end
        if f > 780:
            chat_alpha = min(1.0, (f - 780) / 40)
            d.rounded_rectangle((320, 800, W - 320, 1000), radius=20, fill=PANEL, outline=GREEN, width=3)
            d.text((360, 830), "What's the cap on liability?", fill=BLUE, font=F["body"])
            d.text((360, 890), "The cap on liability is the fees paid in the twelve (12) months", fill=TEXT, font=F["body"])
            d.text((360, 940), "preceding the claim. [acme_msa.pdf:p.1]", fill=VIOLET, font=F["mono_md"])
        yield img

    # Chat card zoom (10s = 300 frames)
    for f in range(300):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 540, GREEN, 0.22)
        d = ImageDraw.Draw(img)

        d.text((100, 80), "The chat card", fill=BLUE, font=F["h2"])
        d.text((100, 160), "Every claim carries a [file:page] marker.", fill=DIM, font=F["body"])

        d.rounded_rectangle((180, 260, W - 180, 720), radius=24, fill=PANEL, outline=BORDER, width=2)
        d.text((220, 300), "Q: What's the cap on liability?", fill=BLUE, font=F["h3"])
        d.line((220, 390, W - 220, 390), fill=BORDER, width=1)
        d.text((220, 430), "A: The cap on liability is the fees paid by Client in", fill=TEXT, font=F["body"])
        d.text((220, 490), "the twelve (12) months preceding the claim, except", fill=TEXT, font=F["body"])
        d.text((220, 550), "for claims of gross negligence.", fill=TEXT, font=F["body"])
        d.text((220, 630), "[acme_msa.pdf:p.1]", fill=VIOLET, font=F["mono_lg"])

        d.rounded_rectangle((W // 2 - 160, 840, W // 2 + 160, 900), radius=30, fill=GREEN)
        d.text((W // 2 - 110, 856), "✓ cited", fill=BG_TOP, font=F["h3"])
        yield img

    # End card
    yield from end_card("That's it.", "local-first RAG, six stages, citations enforced", n_frames=90)


# ============================================================================
# Video 3: magic-sauce (55s = 1650 frames @ 30fps)
# ============================================================================

MAGIC_SCRIPT = """The magic sauce. Three things cloud RAG can't do. Number one: structure aware chunking. A naive chunker splits mid-clause. We keep Section 4.2 Limitation of Liability intact. Result: point five three eight precision at K, versus point four six two for naive. Number two: citation required prompts. Without: 'Yes, liability is uncapped.' Which page? Which contract? With: 'Liability is uncapped. msa dot pdf, page four.' Every claim auditable. Number three: LLM as judge. A second seven billion parameter model audits every answer. Cites that hold up. Flags that don't. Twelve-nine tests passing. Zero point five three eight versus zero point four six two. MIT licensed."""


def video_magic() -> Iterator[Image.Image]:
    # Title (3s)
    for _ in range(90):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        glow(img, W // 2, H // 2, 540, VIOLET, 0.22)
        d = ImageDraw.Draw(img)
        d.text((W // 2 - 400, 380), "The magic sauce", fill=VIOLET, font=F["h1"])
        d.text((W // 2 - 360, 520), "three things cloud RAG can't do", fill=DIM, font=F["h3"])
        yield img

    # Pillar 1: structure-aware chunker (18s = 540 frames)
    for f in range(540):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)
        d.text((100, 80), "1. Structure-aware chunker", fill=VIOLET, font=F["h2"])
        d.text((100, 160), "Recognises Article §, Section, Title Case, WHEREAS.", fill=DIM, font=F["body"])

        col_w = 760
        left_x = 100
        right_x = W - col_w - 100
        col_y = 300
        col_h = 620

        d.rounded_rectangle((left_x, col_y, left_x + col_w, col_y + col_h), radius=20, fill=PANEL, outline=RED, width=3)
        d.text((left_x + 30, col_y + 30), "Naive chunker", fill=RED, font=F["h3"])
        d.text((left_x + 30, col_y + 95), "splits mid-clause", fill=DIM, font=F["body"])

        d.rounded_rectangle((right_x, col_y, right_x + col_w, col_y + col_h), radius=20, fill=PANEL, outline=GREEN, width=3)
        d.text((right_x + 30, col_y + 30), "firm_bot", fill=GREEN, font=F["h3"])
        d.text((right_x + 30, col_y + 95), "respects section boundaries", fill=DIM, font=F["body"])

        clause = "Section 4.2 — Limitation of Liability. In no event shall either party's total liability exceed the fees paid in the twelve (12) months preceding the event giving rise to the claim, except for claims of gross negligence or willful misconduct. Section 4.3 — Indemnification. Vendor shall indemnify Client against any third-party claims arising from Vendor's gross negligence."

        d.text((left_x + 30, col_y + 180), clause, fill=TEXT, font=F["small"])
        # Red split indicator (with smooth animation)
        split_t = ease_in_out_cubic(min(1.0, f / 100))
        naive_split_x = left_x + 30 + int((col_w - 60) * 0.55)
        d.line((naive_split_x, col_y + 170, naive_split_x, col_y + 600), fill=RED, width=5)
        d.text((naive_split_x + 10, col_y + 380), "✗ split", fill=RED, font=F["small"])
        d.text((naive_split_x + 10, col_y + 425), "mid-clause", fill=RED, font=F["small"])

        d.text((right_x + 30, col_y + 180), clause, fill=TEXT, font=F["small"])
        # Green check
        d.text((right_x + col_w - 100, col_y + 380), "✓", fill=GREEN, font=F["h1"])
        d.text((right_x + col_w - 100, col_y + 490), "intact", fill=GREEN, font=F["small"])

        if f > 240:
            d.text((left_x + 30, col_y + 640), "0.462 precision@k", fill=RED, font=F["body"])
            d.text((right_x + 30, col_y + 640), "0.538 precision@k", fill=GREEN, font=F["body"])

        yield img

    # Pillar 2: citation-required prompts (16s = 480 frames)
    for f in range(480):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)
        d.text((100, 80), "2. Citation-required prompts", fill=VIOLET, font=F["h2"])
        d.text((100, 160), "Every claim must carry a [file:page] marker.", fill=DIM, font=F["body"])

        if f < 240:
            d.rounded_rectangle((200, 300, W - 200, 600), radius=22, fill=PANEL, outline=RED, width=3)
            d.text((240, 340), "Without citation-required:", fill=RED, font=F["h3"])
            d.text((240, 430), '"Yes, liability is uncapped."', fill=TEXT, font=F["h2"])
            d.text((240, 530), "→ which page? which contract?", fill=DIM, font=F["body"])
            if f > 140:
                pulse = abs(((f - 140) % 50) - 25) / 25
                d.text((W // 2 - 60, 700), "✗", fill=RED, font=F["huge"])
        else:
            t = ease_in_out_cubic(min(1.0, (f - 240) / 60))
            d.rounded_rectangle((200, 300, W - 200, 600), radius=22, fill=PANEL, outline=GREEN, width=3)
            d.text((240, 340), "With citation-required:", fill=GREEN, font=F["h3"])
            d.text((240, 430), '"Liability is uncapped.', fill=TEXT, font=F["h2"])
            cite = " [msa.pdf:p.4]"
            chars_to_show = int(len(cite) * t)
            d.text((240, 500), cite[:chars_to_show], fill=VIOLET, font=F["mono_lg"])
            if t > 0.7:
                pulse = abs(((f - 280) % 60) - 30) / 30
                d.text((240, 620), "✓  every claim is auditable", fill=GREEN, font=F["h3"])
        yield img

    # Pillar 3: LLM-as-judge guard (14s = 420 frames)
    for f in range(420):
        img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)
        d.text((100, 80), "3. LLM-as-judge guard", fill=VIOLET, font=F["h2"])
        d.text((100, 160), "A second 7B model audits every answer.", fill=DIM, font=F["body"])

        d.rounded_rectangle((200, 300, W - 200, 720), radius=22, fill=PANEL, outline=BORDER, width=2)
        d.text((240, 340), "Audit log:", fill=DIM, font=F["h3"])

        audits = [
            (0, GREEN, "✓ 'cap on liability' → cited [acme_msa.pdf:p.1]"),
            (90, GREEN, "✓ 'gross negligence exclusion' → cited [acme_msa.pdf:p.2]"),
            (200, AMBER, "⚠ 'indemnification scope' → judge flagged (ungrounded)"),
        ]
        for start_frame, color, text in audits:
            if f > start_frame:
                t = ease_in_out_cubic(min(1.0, (f - start_frame) / 30))
                chars = int(len(text) * t)
                d.text((240, 400 + audits.index((start_frame, color, text)) * 90), text[:chars], fill=color, font=F["body"])

        if f > 280:
            d.text((W // 2 - 280, 830), "2 cited · 1 flagged", fill=TEXT, font=F["h3"])
            d.text((W // 2 - 280, 900), "→ judge over-flags at 7B; calmer at 14B", fill=DIM, font=F["small"])
        yield img

    # End card
    yield from end_card("129 tests · 0.538 vs 0.462 · MIT", "that's the magic sauce", n_frames=120)


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="firm-bot-explainers-v2-"))
    jobs = [
        ("why-firm-bot.mp4", video_why, WHY_SCRIPT),
        ("what-is-it.mp4", video_what, WHAT_SCRIPT),
        ("magic-sauce.mp4", video_magic, MAGIC_SCRIPT),
    ]
    # Allow re-rendering only specific videos via cmdline args
    import sys
    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    for name, builder, script in jobs:
        if only and name not in only:
            print(f"  skipping {name} (not in cmdline args)")
            continue
        print(f"  rendering {name} (silent)…", flush=True)
        silent = tmp / f"silent-{name}"
        encode_video(builder(), silent)
        print(f"    → silent ({silent.stat().st_size:,} bytes)")
        final = OUT / name
        print(f"  muxing audio for {name}…", flush=True)
        mux_audio(silent, script, final)
        print(f"    → {final.name} ({final.stat().st_size:,} bytes)")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()