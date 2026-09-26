"""Capture dashboard screenshots with headless Chrome (playwright).

Usage: python scripts/screenshots.py [base_url]   -> docs/screenshots/*.png
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def wait_ready(page):
    page.wait_for_function("document.querySelectorAll('#routeTable tbody tr').length > 0", timeout=20000)
    page.wait_for_timeout(2500)  # tiles + chart animations


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for theme in ("light", "dark"):
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme, device_scale_factor=1)
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and print("console:", m.text))
        page.goto(BASE + "/", wait_until="domcontentloaded")
        wait_ready(page)
        page.screenshot(path=str(OUT / f"day_all_{theme}.png"), full_page=True)
        if theme == "dark":
            continue
        page.select_option("#route", "7")
        wait_ready(page)
        page.screenshot(path=str(OUT / "day_route7.png"), full_page=True)
        page.click("#horizon button[data-h=month]")
        wait_ready(page)
        page.screenshot(path=str(OUT / "month_route7.png"), full_page=True)
        page.click("#horizon button[data-h=year]")
        wait_ready(page)
        page.screenshot(path=str(OUT / "year_route7.png"), full_page=True)
        page.click("#horizon button[data-h=day]")
        page.select_option("#route", "5")
        page.fill("#date", "2025-12-22")
        page.dispatch_event("#date", "change")
        wait_ready(page)
        page.screenshot(path=str(OUT / "day_route5_new.png"), full_page=True)
        # round 2 panels: corrections + rolling stock (route 17, festival x1.3 on 10.12 + rain scenario)
        page.select_option("#route", "17")
        page.fill("#date", "2025-12-10")
        page.dispatch_event("#date", "change")
        wait_ready(page)
        page.locator("#fleetCard").screenshot(path=str(OUT / "panel_fleet.png"))
        page.eval_on_selector("#kLevel", "el => { el.value = 1.03; el.dispatchEvent(new Event('input')); }")
        page.select_option("#eRoute", "17")
        page.fill("#eFrom", "2025-12-10"); page.fill("#eTo", "2025-12-10")
        page.select_option("#eH0", "16"); page.select_option("#eH1", "21")
        page.click(".ghost-btn[data-k='1.2']")
        page.click("#eAdd")
        page.fill("#wDate", "2025-12-10"); page.fill("#wMm", "10"); page.fill("#wT", "-15")
        page.click("#wAdd")
        wait_ready(page)
        page.locator("#adjCard").screenshot(path=str(OUT / "panel_corrections.png"))
        page.locator("#fleetCard").screenshot(path=str(OUT / "panel_fleet_corrected.png"))
        page.screenshot(path=str(OUT / "corrections_route17.png"), full_page=True)
        page.click("#adjReset")
        page.click("#horizon button[data-h=year]")
        wait_ready(page)
        page.locator("#lineChart").screenshot(path=str(OUT / "panel_year.png"))
        page.click("#horizon button[data-h=month]")
        wait_ready(page)
        page.locator("#lineChart").screenshot(path=str(OUT / "panel_month.png"))
        page.click("#horizon button[data-h=day]")
        wait_ready(page)
        page.screenshot(path=str(OUT / "day_route17_nogeo.png"), full_page=False)
        mob = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mp = mob.new_page()
        mp.goto(BASE + "/", wait_until="domcontentloaded")
        wait_ready(mp)
        mp.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        print("mobile overflow:", mp.evaluate("document.documentElement.scrollWidth > innerWidth"))
    b.close()
print("saved to", OUT)
