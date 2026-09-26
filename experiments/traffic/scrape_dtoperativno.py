"""Scrape public Telegram channel preview t.me/s/DtOperativno (Дептранс. Оперативно,
official channel of Moscow Transport Dept) for 2025 posts containing the ЦОДД road-load
score ("загруженность дорог составляет N баллов") and average speed ("N км/ч").

Output: experiments/traffic/dtop_messages.jsonl (raw posts) — parsed by build_traffic.py.
Usage: python experiments/traffic/scrape_dtoperativno.py
"""
import json, re, html, time, os, urllib.request

CH = "DtOperativno"
OUT = os.path.join(os.path.dirname(__file__), "dtop_messages.jsonl")
START_BEFORE = 26500     # somewhere in early 2026
STOP_DATE = "2024-12-25"  # stop when older than this


def fetch(before):
    url = f"https://t.me/s/{CH}?before={before}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for k in range(4):
        try:
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        except Exception as e:  # noqa
            time.sleep(2 + 3 * k)
    return ""


def parse(s):
    out = []
    for b in re.split(r"tgme_widget_message_wrap", s)[1:]:
        pid = re.search(r'data-post="[^/]+/(\d+)"', b)
        d = re.search(r'datetime="([^"]+)"', b)
        m = re.search(r"(?s)tgme_widget_message_text[^>]*>(.*?)</div>", b)
        if not (pid and d):
            continue
        t = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""
        out.append({"id": int(pid.group(1)), "dt": d.group(1), "text": re.sub(r"\s+", " ", t).strip()})
    return out


def main():
    seen = {}
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            r = json.loads(line); seen[r["id"]] = r
    before = min(seen) if seen else START_BEFORE
    with open(OUT, "a", encoding="utf-8") as f:
        while True:
            msgs = parse(fetch(before))
            if not msgs:
                before -= 20
                continue
            for r in msgs:
                if r["id"] not in seen:
                    seen[r["id"]] = r
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            mn = min(r["id"] for r in msgs)
            oldest = min(msgs, key=lambda r: r["id"])["dt"]
            print(before, mn, oldest, flush=True)
            if oldest[:10] < STOP_DATE:
                break
            before = mn
            time.sleep(0.3)


if __name__ == "__main__":
    main()
