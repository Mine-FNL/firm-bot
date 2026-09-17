"""Render the firm-bot demo video — 60s, 1920x1080, animated.

Segments:
  1. Title card (5s)
  2. Terminal: firm-bot serve (8s)
  3. Browser opens at localhost:8000 (5s)
  4. Drop PDF + ingest (10s)
  5. Question + answer streaming in (17s)
  6. Citation pane slides in (8s)
  7. /metrics Prometheus output (5s)
  8. End card with install instructions (4s)

Total: ~62s.

Output: docs/assets/marketing/demo-video.mp4 (1920x1080, H.264).
Each segment is rendered to its own PNG sequence + piped through
ffmpeg to avoid loading all frames in memory at once.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont

OUT = Path("docs/assets/marketing")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080

# Palette — matches docs/marketing/DESIGN.md
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
TERMINAL_PROMPT = (74, 222, 128)


def find_font(*c: str, size: int) -> ImageFont.FreeTypeFont:
    for path in c:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F = {
    "huge":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=200),
    "h1":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=96),
    "h2":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=56),
    "h3":     find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=44),
    "body":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=36),
    "small":  find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=28),
    "tiny":   find_font("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=22),
    "mono_lg": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=44),
    "mono_md": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=32),
    "mono_sm": find_font("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=24),
}


def vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
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


def soft_glow(img: Image.Image, cx: int, cy: int, r: int, color, alpha: float = 0.20) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for k in range(6, 0, -1):
        rr = int(r * (k / 6))
        a = int(alpha * 255 * (k / 6))
        od.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=color + (a,))
    img.alpha_composite(overlay)


def encode_frames(frames: Iterator[Image.Image], out_path: Path, fps: int = 24) -> None:
    """Pipe an iterator of PIL images through ffmpeg to MP4."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-framerate", str(fps),
        "-i", "-",
        "-vcodec", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "23",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for img in frames:
        # JPEG-encode in memory for image2pipe speed
        from io import BytesIO
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=88)
        proc.stdin.write(buf.getvalue())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.returncode}")


# ============================================================================
# Segment 1: Title card (5s = 120 frames @ 24fps)
# ============================================================================

def seg_title() -> Iterator[Image.Image]:
    for _ in range(120):
        img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        soft_glow(img, 600, 380, 480, BLUE, 0.22)
        soft_glow(img, 1400, 800, 500, VIOLET, 0.20)
        d = ImageDraw.Draw(img)

        d.text((160, 360), "firm-bot", fill=BLUE, font=F["huge"])

        d.text((160, 580), "Local-first RAG for professional services.", fill=TEXT, font=F["h2"])
        d.text((160, 660), "Citations required. Your data never leaves the box.", fill=DIM, font=F["body"])

        # Feature pills
        pills = ["Citations required", "Ollama-powered", "Multi-tenant", "MIT licensed"]
        x = 160
        y = 820
        for label in pills:
            bbox = d.textbbox((0, 0), label, font=F["small"])
            w = bbox[2] - bbox[0] + 48
            d.rounded_rectangle((x, y, x + w, y + 56), radius=28, outline=BLUE, width=3)
            d.text((x + 24, y + 14), label, fill=TEXT, font=F["small"])
            x += w + 20

        d.text((160, 990), "github.com/Mine-FNL/firm-bot", fill=VIOLET, font=F["body"])
        yield img


# ============================================================================
# Segment 2: Terminal launch (8s = 192 frames)
# Animation: type "$ firm-bot serve" then output appears
# ============================================================================

TYPING_FRAMES_PER_CHAR = 4   # ~6 chars/sec @ 24fps
TERMINAL_FRAMES = 192


def seg_terminal() -> Iterator[Image.Image]:
    cmd_text = "$ firm-bot serve"
    output_lines = [
        "INFO:     Started server process [12345]",
        "INFO:     Waiting for application startup.",
        "INFO:     Application startup complete.",
        "INFO:     Uvicorn running on http://127.0.0.1:8000",
        "INFO:     Press CTRL+C to quit",
    ]

    for f in range(TERMINAL_FRAMES):
        img = Image.new("RGB", (W, H), TERMINAL_BG)
        d = ImageDraw.Draw(img)

        # Title bar
        d.rectangle((0, 0, W, 60), fill=(40, 40, 45))
        for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse((40 + i * 40, 18, 72 + i * 40, 50), fill=color)
        d.text((220, 18), "gg@macbook-pro — firm-bot serve — 96×24", fill=(180, 180, 180), font=F["mono_sm"])

        # Type the command
        chars_typed = min(len(cmd_text), f // TYPING_FRAMES_PER_CHAR)
        cursor_visible = (f % 8) < 5
        typed = cmd_text[:chars_typed]
        if cursor_visible and chars_typed < len(cmd_text):
            typed += "▌"
        d.text((80, 130), typed, fill=TERMINAL_PROMPT, font=F["mono_lg"])

        # Show output lines progressively after command completes
        if chars_typed >= len(cmd_text):
            output_start_frame = len(cmd_text) * TYPING_FRAMES_PER_CHAR + 6
            elapsed = f - output_start_frame
            line_every = 18  # ~0.75s per line
            for i in range(min(len(output_lines), max(0, elapsed // line_every + 1))):
                y = 230 + i * 64
                line = output_lines[i]
                color = (220, 220, 220) if i < 3 else BLUE
                d.text((80, y), line, fill=color, font=F["mono_md"])

            # Final cursor prompt
            cursor_y = 230 + len(output_lines) * 64 + 30
            if chars_typed >= len(cmd_text):
                d.text((80, cursor_y), "$ ", fill=TERMINAL_PROMPT, font=F["mono_lg"])
                if cursor_visible:
                    d.text((140, cursor_y), "▌", fill=TEXT, font=F["mono_lg"])

        # Caption overlay
        d.text((W // 2 - 200, H - 80), "self-hosted, no cloud calls", fill=DIM, font=F["small"])
        yield img


# ============================================================================
# Segment 3: Browser opens (5s = 120 frames)
# Animation: browser chrome fades in, URL bar fills, page loads
# ============================================================================

def seg_browser_open() -> Iterator[Image.Image]:
    for f in range(120):
        t = f / 119.0
        img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        soft_glow(img, W // 2, H // 2, 600, BLUE, 0.10 * t)
        d = ImageDraw.Draw(img)

        # Browser window grows in
        margin = int(80 - 30 * t)
        win_x0 = margin
        win_y0 = margin
        win_x1 = W - margin
        win_y1 = H - margin
        d.rounded_rectangle((win_x0, win_y0, win_x1, win_y1), radius=18, fill=(40, 40, 45), outline=BORDER, width=2)

        # Title bar
        d.rectangle((win_x0, win_y0, win_x1, win_y0 + 60), fill=(50, 50, 55))
        for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse((win_x0 + 24 + i * 36, win_y0 + 18, win_x0 + 52 + i * 36, win_y0 + 46), fill=color)

        # URL bar (typing animation)
        url_text = "http://localhost:8000"
        url_chars = min(len(url_text), int(t * len(url_text) * 1.3))
        d.rounded_rectangle((win_x0 + 180, win_y0 + 14, win_x1 - 30, win_y0 + 46), radius=16, fill=(70, 70, 75))
        d.text((win_x0 + 210, win_y0 + 18), url_text[:url_chars], fill=(220, 220, 220), font=F["small"])

        # App shell — fades in toward end of segment
        if t > 0.4:
            alpha_t = min(1.0, (t - 0.4) / 0.4)
            # Sidebar
            sb_x = win_x0 + 12
            sb_y = win_y0 + 80
            sb_w = 260
            d.rectangle((sb_x, sb_y, sb_x + sb_w, win_y1 - 12), fill=(22, 28, 45))
            d.text((sb_x + 30, sb_y + 30), "firm-bot", fill=BLUE, font=F["h3"])
            d.text((sb_x + 30, sb_y + 90), "Firm: acme LLP", fill=TEXT, font=F["small"])

            # Main panel
            main_x = sb_x + sb_w + 14
            d.rectangle((main_x, sb_y, win_x1 - 24, win_y1 - 24), fill=PANEL, outline=BORDER, width=2)
            d.text((main_x + 40, sb_y + 60), "Drag PDFs, EML, or DOCX here", fill=TEXT, font=F["h3"])
            d.text((main_x + 40, sb_y + 130), "or click to browse", fill=DIM, font=F["body"])

            # Drop zone
            dz_x0, dz_y0 = main_x + 40, sb_y + 220
            dz_x1, dz_y1 = win_x1 - 60, sb_y + 540
            d.rounded_rectangle((dz_x0, dz_y0, dz_x1, dz_y1), radius=20, outline=BLUE, width=4)
            d.text((dz_x0 + 50, dz_y0 + 40), "Drop files to ingest", fill=TEXT, font=F["h3"])
            d.text((dz_x0 + 50, dz_y0 + 110), "PDF · EML · DOCX", fill=DIM, font=F["small"])

        yield img


# ============================================================================
# Segment 4: Drop PDF + ingest (10s = 240 frames)
# ============================================================================

def seg_ingest() -> Iterator[Image.Image]:
    for f in range(240):
        img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)

        # Sidebar + main panel chrome (static)
        d.rectangle((0, 0, 240, H), fill=(22, 28, 45))
        d.text((40, 100), "firm-bot", fill=BLUE, font=F["h3"])
        d.text((40, 160), "Firm: acme LLP", fill=TEXT, font=F["small"])

        d.rectangle((252, 12, W - 12, H - 12), fill=PANEL, outline=BORDER, width=2)
        d.text((300, 80), "Drop PDFs, EML, or DOCX here", fill=TEXT, font=F["h3"])

        # Drop zone
        dz_x0, dz_y0 = 300, 200
        dz_x1, dz_y1 = W - 60, 600
        d.rounded_rectangle((dz_x0, dz_y0, dz_x1, dz_y1), radius=20, outline=BLUE, width=4)
        d.text((dz_x0 + 60, dz_y0 + 60), "Drop files to ingest", fill=TEXT, font=F["h3"])

        # PDF hover / drop animation
        if 30 < f < 120:
            # PDF hovers above the zone, dropping in
            t = (f - 30) / 90.0
            # x stays at right portion of zone
            pdf_x = dz_x0 + int((dz_x1 - dz_x0) * 0.3)
            # y starts above zone, ends inside
            start_y = dz_y0 - 120
            end_y = dz_y0 + 150
            pdf_y = int(start_y + (end_y - start_y) * t)
            # PDF card
            d.rounded_rectangle((pdf_x, pdf_y, pdf_x + 360, pdf_y + 80), radius=12, fill=VIOLET, outline=TEXT, width=2)
            d.text((pdf_x + 20, pdf_y + 20), "📄  acme_msa.pdf  (218 KB)", fill=TEXT, font=F["small"])
        elif f == 120:
            # Drop! Highlight the zone
            d.rounded_rectangle((dz_x0, dz_y0, dz_x1, dz_y1), radius=20, outline=GREEN, width=6)
            d.rounded_rectangle((dz_x0 + 80, dz_y0 + 200, dz_x0 + 440, dz_y0 + 280), radius=12, fill=VIOLET, outline=TEXT, width=2)
            d.text((dz_x0 + 100, dz_y0 + 220), "📄  acme_msa.pdf  (218 KB)", fill=TEXT, font=F["small"])
        elif 121 <= f < 180:
            # Ingesting... progress
            t = (f - 121) / 59.0
            d.rounded_rectangle((dz_x0 + 80, dz_y0 + 200, dz_x0 + 440, dz_y0 + 280), radius=12, fill=VIOLET, outline=TEXT, width=2)
            d.text((dz_x0 + 100, dz_y0 + 220), "📄  acme_msa.pdf", fill=TEXT, font=F["small"])
            # progress bar
            pb_x0 = dz_x0 + 80
            pb_x1 = dz_x0 + 440
            pb_y = dz_y0 + 320
            d.rounded_rectangle((pb_x0, pb_y, pb_x1, pb_y + 30), radius=15, fill=(40, 50, 70))
            d.rounded_rectangle((pb_x0, pb_y, pb_x0 + int((pb_x1 - pb_x0) * t), pb_y + 30), radius=15, fill=BLUE)
            d.text((pb_x0, pb_y + 50), "Ingesting…  chunking · embedding · indexing", fill=DIM, font=F["small"])
        elif f >= 180:
            # Done
            d.text((dz_x0 + 60, dz_y0 + 60), "Ingested ✓", fill=GREEN, font=F["h3"])
            d.text((dz_x0 + 60, dz_y0 + 130), "9 chunks indexed from 2 documents", fill=TEXT, font=F["body"])

            # Stats
            yy = dz_y0 + 220
            for label, val in [("Files", "2"), ("Chunks", "9"), ("Sources", "2 PDFs")]:
                d.rounded_rectangle((dz_x0, yy, dz_x0 + 260, yy + 90), radius=12, fill=PANEL, outline=BORDER)
                d.text((dz_x0 + 16, yy + 12), label, fill=DIM, font=F["small"])
                d.text((dz_x0 + 16, yy + 40), val, fill=TEXT, font=F["h2"])
                yy += 100

            d.text((dz_x0, yy + 20), "Ready to ask.", fill=BLUE, font=F["body"])

        yield img


# ============================================================================
# Segment 5: Question + answer streaming (17s = 408 frames)
# ============================================================================

ANSWER_FULL = (
    "The cap on liability in the MSA is the fees paid by Client in "
    "the twelve (12) months preceding the claim, except for claims "
    "of gross negligence or willful misconduct. "
)
CITATION = "[acme_msa.pdf:p.1]"


def seg_qa() -> Iterator[Image.Image]:
    question = "What's the cap on liability in the MSA?"
    answer = ANSWER_FULL

    typing_q_frames = len(question) * 2  # ~0.5s to type
    submit_pause = 18  # ~0.75s
    answer_typing = len(answer) * 2
    citation_pause = 24

    total = typing_q_frames + submit_pause + answer_typing + citation_pause + 60  # hold for 2.5s

    for f in range(total):
        img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)

        # Sidebar
        d.rectangle((0, 0, 240, H), fill=(22, 28, 45))
        d.text((40, 100), "firm-bot", fill=BLUE, font=F["h3"])
        d.text((40, 160), "Firm: acme LLP", fill=TEXT, font=F["small"])

        # Main panel
        d.rectangle((252, 12, W - 12, H - 12), fill=PANEL, outline=BORDER, width=2)
        d.text((300, 80), "Ask anything about your firm's documents.", fill=TEXT, font=F["h2"])

        # Question bubble
        q_chars = min(len(question), f // 2)
        if q_chars > 0:
            d.rounded_rectangle((320, 180, W - 80, 280), radius=20, fill=BLUE)
            d.text((360, 210), question[:q_chars], fill=BG_TOP, font=F["body"])

        # Submit indicator
        if q_chars >= len(question) and f < typing_q_frames + submit_pause:
            d.text((W - 260, 220), "↵ Enter", fill=DIM, font=F["small"])

        # Answer bubble
        if f >= typing_q_frames + submit_pause:
            ans_f = f - typing_q_frames - submit_pause
            if ans_f < answer_typing:
                chars = ans_f // 2
                text = answer[:chars]
            else:
                text = answer
                chars = len(text)

            d.rounded_rectangle((320, 320, W - 80, 600), radius=20, fill=PANEL, outline=BORDER, width=1)
            d.text((360, 350), "Answer", fill=DIM, font=F["small"])

            # Wrap text
            words = text.split()
            line = ""
            yy = 400
            for w in words:
                if len(line) + len(w) + 1 > 60:
                    d.text((360, yy), line, fill=TEXT, font=F["body"])
                    yy += 50
                    line = w
                else:
                    line = (line + " " + w).strip()
            if line:
                d.text((360, yy), line, fill=TEXT, font=F["body"])

            # Citation appears at end
            if ans_f >= answer_typing:
                d.text((360, yy + 60), CITATION, fill=VIOLET, font=F["mono_md"])
                # Guard verdict
                d.rounded_rectangle((W - 260, 560, W - 80, 610), radius=15, fill=GREEN)
                d.text((W - 220, 575), "✓ cited", fill=BG_TOP, font=F["body"])

        yield img


# ============================================================================
# Segment 6: Citation pane slides in (8s = 192 frames)
# ============================================================================

def seg_citation_pane() -> Iterator[Image.Image]:
    for f in range(192):
        img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        d = ImageDraw.Draw(img)

        # Sidebar
        d.rectangle((0, 0, 240, H), fill=(22, 28, 45))
        d.text((40, 100), "firm-bot", fill=BLUE, font=F["h3"])

        # Main panel
        d.rectangle((252, 12, W - 12, H - 12), fill=PANEL, outline=BORDER, width=2)

        # Question
        d.rounded_rectangle((320, 100, W - 80, 200), radius=20, fill=BLUE)
        d.text((360, 130), "What's the cap on liability in the MSA?", fill=BG_TOP, font=F["body"])

        # Answer
        d.rounded_rectangle((320, 240, W - 80, 480), radius=20, fill=PANEL, outline=BORDER, width=1)
        d.text((360, 270), "Answer", fill=DIM, font=F["small"])
        d.text((360, 320), "The cap on liability is the fees paid in the twelve", fill=TEXT, font=F["body"])
        d.text((360, 370), "(12) months preceding the claim.", fill=TEXT, font=F["body"])
        d.text((360, 440), "[acme_msa.pdf:p.1]", fill=VIOLET, font=F["mono_md"])

        # Source pane slides in from right
        t = min(1.0, f / 60.0)
        pane_w = 900
        pane_x = int(W - 60 - pane_w * t)
        d.rounded_rectangle((pane_x, 540, pane_x + pane_w, H - 60), radius=20, fill=(20, 30, 55), outline=VIOLET, width=3)
        if t > 0.4:
            d.text((pane_x + 30, 560), "Source: acme_msa.pdf  p.1  § 4.2 Limitation of Liability", fill=VIOLET, font=F["small"])
            excerpt = '"In no event shall either party\u2019s total liability exceed the fees paid in the twelve (12) months preceding the event giving rise to the claim, except for claims of gross negligence or willful misconduct."'
            # wrap
            words = excerpt.split()
            line = ""
            yy = 620
            for w in words:
                if len(line) + len(w) + 1 > 50:
                    d.text((pane_x + 30, yy), line, fill=TEXT, font=F["small"])
                    yy += 38
                    line = w
                else:
                    line = (line + " " + w).strip()
            if line:
                d.text((pane_x + 30, yy), line, fill=TEXT, font=F["small"])

        yield img


# ============================================================================
# Segment 7: /metrics (5s = 120 frames)
# ============================================================================

METRICS_TEXT = """# HELP firmbot_query_requests_total Total /query requests
# TYPE firmbot_query_requests_total counter
firmbot_query_requests_total{firm="acme",status="200"} 47.0
firmbot_query_requests_total{firm="acme",status="200"} 52.0
firmbot_query_requests_total{firm="acme",status="429"} 3.0

# HELP firmbot_query_latency_seconds End-to-end /query latency
# TYPE firmbot_query_latency_seconds histogram
firmbot_query_latency_seconds_bucket{firm="acme",le="0.5"} 12.0
firmbot_query_latency_seconds_bucket{firm="acme",le="1.0"} 41.0
firmbot_query_latency_seconds_bucket{firm="acme",le="2.0"} 88.0
firmbot_query_latency_seconds_bucket{firm="acme",le="5.0"} 99.0
firmbot_query_latency_seconds_sum{firm="acme"} 137.42
firmbot_query_latency_seconds_count{firm="acme"} 102.0

# HELP firmbot_active_firms Number of configured firms
# TYPE firmbot_active_firms gauge
firmbot_active_firms 1.0"""


def seg_metrics() -> Iterator[Image.Image]:
    lines = METRICS_TEXT.split("\n")
    for f in range(120):
        img = Image.new("RGB", (W, H), (12, 12, 16))
        d = ImageDraw.Draw(img)

        # Title bar
        d.rectangle((0, 0, W, 60), fill=(40, 40, 45))
        for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse((40 + i * 40, 18, 72 + i * 40, 50), fill=color)
        d.text((220, 18), "Prometheus metrics endpoint", fill=(180, 180, 180), font=F["mono_sm"])

        # URL bar
        d.rounded_rectangle((600, 14, 1500, 46), radius=16, fill=(70, 70, 75))
        d.text((640, 18), "GET http://localhost:8000/metrics", fill=(220, 220, 220), font=F["mono_sm"])

        # Body — show lines progressively
        lines_visible = min(len(lines), int(f * len(lines) / 80))
        for i in range(lines_visible):
            line = lines[i]
            color = (180, 180, 180)
            if line.startswith("# HELP"):
                color = BLUE
            elif line.startswith("# TYPE"):
                color = VIOLET
            elif "_bucket{" in line or "_sum{" in line:
                color = (220, 220, 220)
            d.text((80, 120 + i * 44), line, fill=color, font=F["mono_md"])

        # Caption
        d.text((80, H - 60), "pip install firm-bot[observability]", fill=DIM, font=F["small"])
        yield img


# ============================================================================
# Segment 8: End card (4s = 96 frames)
# ============================================================================

def seg_end() -> Iterator[Image.Image]:
    for _ in range(96):
        img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
        soft_glow(img, W // 2, H // 2, 500, GREEN, 0.18)
        d = ImageDraw.Draw(img)

        d.text((W // 2 - 320, 280), "Try it now", fill=GREEN, font=F["h1"])
        d.text((W // 2 - 320, 410), "git clone https://github.com/Mine-FNL/firm-bot", fill=TEXT, font=F["mono_lg"])
        d.text((W // 2 - 320, 480), "cd firm-bot && pip install -e \".[dev,observability]\"", fill=TEXT, font=F["mono_lg"])
        d.text((W // 2 - 320, 550), "firm-bot serve   # → http://localhost:8000", fill=TEXT, font=F["mono_lg"])

        d.text((W // 2 - 320, 740), "github.com/Mine-FNL/firm-bot", fill=VIOLET, font=F["h3"])
        d.text((W // 2 - 320, 820), "MIT licensed · Python 3.11+ · Ollama-powered", fill=DIM, font=F["body"])

        yield img


# ============================================================================
# Main
# ============================================================================

def main() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="firm-bot-video-"))
    segments = [
        ("01_title", seg_title, 120),
        ("02_terminal", seg_terminal, 192),
        ("03_browser", seg_browser_open, 120),
        ("04_ingest", seg_ingest, 240),
        ("05_qa", seg_qa, 408),
        ("06_citation", seg_citation_pane, 192),
        ("07_metrics", seg_metrics, 120),
        ("08_end", seg_end, 96),
    ]
    segment_files = []
    for name, builder, n_frames in segments:
        path = tmp / f"{name}.mp4"
        print(f"  rendering {name} ({n_frames} frames)…", flush=True)
        encode_frames(builder(), path, fps=24)
        segment_files.append(path)
        print(f"    → {path.name} ({path.stat().st_size:,} bytes)")

    # Concatenate
    list_file = tmp / "list.txt"
    list_file.write_text("\n".join(f"file '{f.absolute()}'" for f in segment_files))

    out = OUT / "demo-video.mp4"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nwrote {out} ({out.stat().st_size:,} bytes, {out.stat().st_size / 1024 / 1024:.2f} MB)")
    return out


if __name__ == "__main__":
    main()