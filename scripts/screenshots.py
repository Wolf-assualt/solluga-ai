"""
scripts/screenshots.py — Capture README screenshots of the web dashboard.

Starts a private uvicorn instance on 127.0.0.1 against the SAMPLE database
(data/demo.db, created by data/seed_demo.py if missing) with a throwaway
password and .env loading disabled, then drives it with Playwright.

* GET navigation only — never submits reset / delete / status forms.
* Fails (exit 1) if any page logs a console error or throws.
* Uses the system Chrome/Chromium; no `playwright install` download needed.

Usage:
    python -m pip install -r requirements-dev.txt
    python scripts/screenshots.py [--port 2628] [--chrome /usr/bin/google-chrome]
Output: docs/assets/*.png
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DB = os.path.join("data", "demo.db")
OUT_DIR = os.path.join(ROOT, "docs", "assets")

PAGES = [
    ("/", "home.png"),
    ("/dashboard", "dashboard.png"),
    ("/orders", "orders.png"),
    ("/items", "items.png"),
    ("/sales", "sales.png"),
]


def _find_chrome(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None  # fall back to Playwright's bundled browser if installed


def _wait_healthy(base: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.4)
    raise RuntimeError("server did not become healthy in time")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--port", type=int, default=2628)
    ap.add_argument("--chrome", default=None, help="path to Chrome/Chromium executable")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(ROOT, DEMO_DB)):
        subprocess.run([sys.executable, os.path.join(ROOT, "data", "seed_demo.py")], check=True, cwd=ROOT)

    password = secrets.token_urlsafe(12)
    env = {
        **os.environ,
        "PYTHON_DOTENV_DISABLED": "1",   # never load real secrets from .env
        "DB_PATH": DEMO_DB,
        "DASHBOARD_PASSWORD": password,
        "SECRET_KEY": secrets.token_urlsafe(24),
    }
    for k in ("TELEGRAM_BOT_TOKEN", "WHATSAPP_ACCESS_TOKEN", "LLM_API_KEY"):
        env.pop(k, None)

    base = f"http://127.0.0.1:{args.port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    errors: list[str] = []
    try:
        _wait_healthy(base)
        os.makedirs(OUT_DIR, exist_ok=True)
        chrome = _find_chrome(args.chrome)

        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            if chrome:
                launch_kwargs["executable_path"] = chrome
            browser = p.chromium.launch(**launch_kwargs)

            def new_page(scheme: str, **ctx_kwargs):
                ctx = browser.new_context(color_scheme=scheme, reduced_motion="reduce", **ctx_kwargs)
                page = ctx.new_page()
                page.on("console", lambda m: m.type == "error" and errors.append(f"[{page.url}] console: {m.text}"))
                page.on("pageerror", lambda e: errors.append(f"[{page.url}] pageerror: {e}"))
                return ctx, page

            def shoot(page, path: str, filename: str, full_page: bool = True) -> None:
                page.goto(base + path, wait_until="networkidle")
                if path.startswith("/dashboard"):
                    page.wait_for_function("window.__dashboardReady === true", timeout=15000)
                if full_page:
                    # Grow the viewport to the content height so the fixed-height
                    # sidebar spans the whole capture (full_page would clip it).
                    vp = page.viewport_size
                    height = page.evaluate("document.documentElement.scrollHeight")
                    page.set_viewport_size({"width": vp["width"], "height": max(height, vp["height"])})
                    page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(OUT_DIR, filename))
                if full_page:
                    page.set_viewport_size(vp)
                print(f"  📸 {filename:24s} ← {path}")

            def login(page) -> None:
                page.goto(base + "/login", wait_until="networkidle")
                page.fill("input[name=password]", password)
                page.click("button[type=submit]")
                page.wait_for_url(base + "/")

            desktop = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}

            # Light theme, desktop
            ctx, page = new_page("light", **desktop)
            shoot(page, "/login", "login.png", full_page=False)
            login(page)
            for path, name in PAGES:
                shoot(page, path, name)
            ctx.close()

            # Dark theme dashboard
            ctx, page = new_page("dark", **desktop)
            login(page)
            shoot(page, "/dashboard", "dashboard-dark.png")
            ctx.close()

            # Mobile dashboard
            ctx, page = new_page(
                "light", viewport={"width": 390, "height": 844}, device_scale_factor=2,
                is_mobile=True, has_touch=True,
            )
            login(page)
            shoot(page, "/dashboard", "dashboard-mobile.png")
            ctx.close()

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    if errors:
        print("\n❌ Browser errors:")
        for e in errors:
            print("  ", e)
        return 1
    print(f"\n✅ Screenshots saved to {os.path.relpath(OUT_DIR, ROOT)}/ — no console errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
