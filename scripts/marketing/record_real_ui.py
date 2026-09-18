"""Real screen recording of firm-bot's UI driven by Playwright.

Drives the actual web UI through the demo flow:
  1. Open localhost:8000 — drag-drop zone empty
  2. Type a question into the chat input
  3. Submit and let the answer stream in (real Ollama)
  4. Show the citation marker + cited source

Outputs raw .webm in tmp; convert to mp4 with ffmpeg.

Requires:
  - firm-bot serve running on http://127.0.0.1:8000 with FIRM_BOT_LLM_MODEL=qwen2.5-coder:1.5b-instruct
  - Demo firm ingested with acme_msa.pdf + nda.pdf
  - Playwright + Chromium browser installed

The 1.5B model is used so the recording completes in <60 seconds.
For production marketing, swap in a larger model + lengthen the
recording to include a real LLM streaming experience.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

# Tell Playwright where to find browsers
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/Users/gg/Library/Caches/ms-playwright")

from playwright.sync_api import sync_playwright

OUT = Path("docs/assets/marketing")
OUT.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://127.0.0.1:8000"
QUESTION = "What's the cap on liability in the MSA?"


def main() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="firmbot-record-"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1280,720",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(tmp),
                record_video_size={"width": 1280, "height": 720},
                device_scale_factor=2,  # crisper
            )
            page = ctx.new_page()

            # Step 1: load the UI
            print("  → loading UI…")
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_selector("#firm-list li", timeout=15000)
            time.sleep(1.0)

            # Step 2: select the demo firm from the sidebar
            print("  → selecting demo firm…")
            demo_li = page.locator('#firm-list li[data-slug="demo"]').first
            demo_li.click()
            time.sleep(2.0)  # let firm-load + UI react
            # Wait for the upload zone + chat input to be ready
            page.wait_for_selector("#upload-zone", timeout=10000)
            page.wait_for_selector("#q-input", timeout=10000)
            time.sleep(0.5)

            # Step 3: type the question
            print("  → typing question…")
            chat_input = page.locator("#q-input")
            chat_input.click()
            time.sleep(0.3)
            chat_input.fill(QUESTION)  # faster than per-char typing
            time.sleep(0.5)

            # Step 4: submit
            # NOTE: the chat input is a <textarea> inside a <form
            # id="chat-form">. The form's onsubmit handler does
            # ev.preventDefault() and calls streamQuery, so submitting
            # the form (return-key OR button click) is what triggers
            # the request. We previously did chat_input.press("Enter")
            # which only inserts a newline (the global keydown handler
            # only reacts to Escape, not Enter) — so the request never
            # fired and the recording stalled at "Ask away".
            # Clicking the Send button submits the form and triggers
            # streamQuery correctly.
            print("  → submitting…")
            page.locator("#send-btn").click()
            # Wait for the streaming answer. The UI re-renders the
            # message after SSE done — so wait for the final render
            # (any non-empty .body inside #messages) plus a buffer for
            # the citation-highlight pass.
            try:
                page.wait_for_function(
                    """() => {
                        const bodies = document.querySelectorAll('#messages .body');
                        for (const b of bodies) {
                            const t = (b.textContent || '').trim();
                            if (t.length > 100 && !t.endsWith('▍')) return true;
                        }
                        return false;
                    }""",
                    timeout=60000,
                )
                print("  → answer rendered")
            except Exception as e:
                print(f"  → render wait failed: {e}; waiting 30s anyway")
                time.sleep(30)

            time.sleep(4.0)  # let citation pane + final highlight render

            # Step 5: scroll to /metrics page
            print("  → visiting /metrics…")
            page.goto(f"{BASE_URL}/metrics", wait_until="networkidle", timeout=15000)
            time.sleep(2.0)

            # Close and finalize
            print("  → closing browser…")
            ctx.close()
            browser.close()

            # Playwright writes a .webm to tmp
            webm_files = list(tmp.glob("*.webm"))
            if not webm_files:
                raise RuntimeError("no .webm file produced")
            raw = webm_files[0]
            final = OUT / "real-demo-recording.mp4"
            print(f"  → converting {raw.name} → {final.name}")
            # Convert webm to mp4 with proper codec
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(raw),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "medium", "-crf", "20",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-movflags", "+faststart",
                str(final),
            ], check=True)

        print(f"\nwrote {final} ({final.stat().st_size:,} bytes, {final.stat().st_size / 1024 / 1024:.2f} MB)")
        return final
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()