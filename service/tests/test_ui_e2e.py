"""Browser regression tests (headless Chrome via Playwright). Skipped when Playwright or Chrome is not installed.

Round 4 bug: charts drawn while the page/card was hidden or still being laid out stayed at ECharts' 100 px fallback
canvas (blank-looking chart under the map) because they were resized only on window «resize». Fixed with a
ResizeObserver per chart container.
"""
import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")

CHART_JS = """[...document.querySelectorAll('.chart')].filter(el => el.offsetParent).map(el => {
  const cv = el.querySelector('canvas');
  return {id: el.id, box: el.clientWidth, canvas: cv ? parseInt(cv.style.width) : 0}; })"""


@pytest.fixture(scope="module")
def base_url():
    import uvicorn

    from app.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            try:
                b = p.chromium.launch(headless=True)
            except Exception as e:  # no browser binaries on this machine
                pytest.skip(f"no Chromium available: {e}")
        yield b
        b.close()


def _ready(page):
    page.wait_for_function("document.querySelectorAll('#routeTable tbody tr').length > 0", timeout=30000)
    page.wait_for_timeout(1000)


@pytest.mark.parametrize("width", [1440, 390])
def test_charts_render_after_hidden_start(browser, base_url, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("document.addEventListener('DOMContentLoaded', () => "
                         "{ document.querySelector('main').style.display = 'none'; })")
    page.goto(base_url + "/")
    _ready(page)
    page.evaluate("document.querySelector('main').style.display = ''")
    page.wait_for_timeout(800)
    charts = page.evaluate(CHART_JS)
    assert charts and all(abs(c["canvas"] - c["box"]) <= 2 for c in charts), charts
    assert not errors, errors
    page.close()


def test_horizons_routes_themes_no_errors(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
    page.goto(base_url + "/")
    _ready(page)
    for route in ("all", "7", "17"):
        page.select_option("#route", route)
        for h in ("day", "month", "year"):
            page.click(f"#horizon button[data-h={h}]")
            _ready(page)
            opt = page.evaluate("echarts.getInstanceByDom(document.getElementById('lineChart')).getOption().series.length")
            assert opt > 0, (route, h)
        page.click("#horizon button[data-h=day]")
    page.click("#themeBtn")
    _ready(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors, errors  # includes the reported «dayLineTooltip» ReferenceError class of bugs
    page.close()
