"""«Помощник диспетчера»: rule-based answers to structured questions, built only from the service's own data.

No LLM and no external calls: the question is parsed with regular expressions (route, date, hour, intent) and the
answer is assembled from the same query functions the API uses (fleet, series, kpi, anomalies, model).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import queries as Q
from .adjust import Adj
from .errors import ApiError

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]
WD_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WD_PAT = [r"понедельник", r"вторник", r"сред[уа]", r"четверг", r"пятниц[уа]", r"суббот[уа]", r"воскресень[ея]"]

EXAMPLES = [
    "Где завтра переполнение?",
    "Сколько вагонов нужно на 17 маршруте в 8 утра?",
    "Сколько пассажиров на маршруте 7 10 декабря в 18:00?",
    "Когда час пик на 11 маршруте в пятницу?",
    "Какие аномалии были на маршруте 1 в мае?",
    "Как устроена модель?",
]

INTENTS = [
    ("help", r"помощ|что ты умеешь|что умеешь|примеры|^\s*$"),
    ("anomalies", r"аномал|сбо[йия]|выброс|провал|всплеск"),
    ("model", r"модел|точност|метрик|как (устроен|считает|считается|работает)|lightgbm|гибрид"),
    ("vehicles", r"вагон|трамва[ея]в|подвижн|выпуск|сколько (нужно|надо) (машин|единиц)"),
    ("overflow", r"переполн|давк|перегру|риск|не хват|битком"),
    ("peak", r"\bпик"),
    ("load", r"пассажир|загрузк|пото[кч]|сколько (людей|человек)|прогноз|спрос"),
]


def _fmt(x) -> str:
    return "—" if x is None else f"{x:,.0f}".replace(",", " ")


def _human(d: date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1]} ({WD_SHORT[d.weekday()]})"


def parse(text: str, ref: date) -> dict:
    t = " " + text.lower().replace("ё", "е") + " "
    out: dict = {"route": None, "route_raw": None, "date": None, "date_word": None, "hour": None, "month": None}

    # ---- dates (removed from the text so their numbers are not taken for routes/hours) ----
    def take(m, d, word=None):
        nonlocal t
        out["date"], out["date_word"] = d, word
        t = t[:m.start()] + " " + t[m.end():]

    rel = {"послезавтра": 2, "завтра": 1, "сегодня": 0, "вчера": -1}
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        try:
            take(m, date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            pass
    if out["date"] is None and (m := re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", t)):
        y = int(m[3]) if m[3] else ref.year
        y = y + 2000 if y < 100 else y
        try:
            take(m, date(y, int(m[2]), int(m[1])))
        except ValueError:
            pass
    if out["date"] is None and (m := re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS_GEN) + r")(?:\s+(\d{4}))?", t)):
        try:
            take(m, date(int(m[3]) if m[3] else ref.year, MONTHS_GEN.index(m[2]) + 1, int(m[1])))
        except ValueError:
            pass
    if out["date"] is None:
        for w, k in rel.items():
            if m := re.search(rf"\b{w}\b", t):
                take(m, ref + timedelta(days=k), w)
                break
    if out["date"] is None:
        for i, pat in enumerate(WD_PAT):
            if m := re.search(rf"\b(?:в|во)?\s*{pat}", t):
                delta = (i - ref.weekday()) % 7
                take(m, ref + timedelta(days=delta), WD_FULL[i])
                break
    if out["date"] is None:
        months_prep = ["январ", "феврал", "март", "апрел", "ма[йея]", "июн", "июл", "август", "сентябр", "октябр",
                       "ноябр", "декабр"]
        for i, pat in enumerate(months_prep):
            if m := re.search(rf"\b(?:в|за)\s+{pat}\w*", t):
                out["month"] = i + 1
                t = t[:m.start()] + " " + t[m.end():]
                break

    # ---- route ----
    m = (re.search(r"(?:маршрут\w*|№|#|трамва\w*)\s*(?:№\s*)?(\d{1,3})\b", t)
         or re.search(r"\b(\d{1,3})\s*(?:-?(?:м|й|го|ом|ый|ой))?\s*(?:маршрут|трамва)", t))
    if m:
        out["route_raw"] = m[1]
        t = t[:m.start()] + " " + t[m.end():]

    # ---- hour ----
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", t) or \
        re.search(r"\b(?:в|к|на|около)\s*(\d{1,2})\s*(?:ч\w*)?\s*(утра|вечера|дня|ночи)?", t) or \
        re.search(r"\b(\d{1,2})\s*(утра|вечера|дня|ночи|час\w*)\b", t)
    if m:
        h = int(m[1])
        suf = m[2] if m.lastindex and m.lastindex >= 2 and m[2] and not m[2].isdigit() else ""
        if suf in ("вечера", "дня") and h < 12:
            h += 12
        if suf == "ночи" and h == 12:
            h = 0
        if 0 <= h <= 23:
            out["hour"] = h
    elif re.search(r"\bутр\w*", t):
        out["hour_word"] = "утро"
    elif re.search(r"\bвечер\w*", t):
        out["hour_word"] = "вечер"

    out["intent"] = next((name for name, pat in INTENTS if re.search(pat, t)), None)
    if out["intent"] is None:
        out["intent"] = "load" if (out["route_raw"] or out["date"]) else "help"
    return out


def _route(st, raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw not in st.route_idx:
        raise ApiError(404, "route_not_found",
                       f"Маршрут «{raw}» не найден. Доступные маршруты: {', '.join(st.routes)}")
    return raw


def _in_range(st, d: date) -> None:
    lo, hi = st.coverage["combined"]
    if not lo <= d <= hi:
        raise ApiError(400, "out_of_range", f"Данные есть с {lo:%d.%m.%Y} по {hi:%d.%m.%Y}; спросите про дату из этого периода")


def _fleet(st, route, d, adj, plan_by):
    return Q.fleet_query(st, route, str(d), adj, None, 0.8, 0.6, 1.5, None, 10.0, 20.0, None, 30.0, plan_by)


def answer(st, q: str, ref: date, adj: Adj, plan_by: str = "p50") -> dict:
    p = parse(q, ref)
    intent = p["intent"]
    items: list[str] = []
    action: dict = {}
    try:
        route = _route(st, p["route_raw"])
        if intent == "help":
            text = ("Я отвечаю на вопросы по данным сервиса: переполнение, потребность в вагонах, пассажиропоток по "
                    "часам, час пик, аномалии в истории, устройство модели. Укажите маршрут, дату и час, например:")
            items = EXAMPLES
        elif intent == "model":
            m = Q.model_query(st)
            text = m["description"][0] + (" " + m["description"][1] if m["hybrid_available"] else "")
            if m.get("hybrid_compare"):
                hc = m["hybrid_compare"]
                items.append(f"Гибрид ML к v08 за ноябрь–декабрь: {hc['pct']:+.2f} %".replace(".", ","))
            if m["fold_table"] is not None:
                tb = m["tables"][m["fold_table"]]
                items += [" · ".join(f"{h}: {v}" for h, v in zip(tb["header"], r)) for r in tb["rows"][:6]]
            action = {"scroll": "modelCard"}
        elif intent == "anomalies":
            if p["date"]:
                a = b = p["date"]
            elif p["month"]:
                y = st.coverage["history"][0].year
                a = date(y, p["month"], 1)
                b = (date(y + (p["month"] == 12), p["month"] % 12 + 1, 1) - timedelta(days=1))
            else:
                a, b = st.coverage["history"]
            r = Q.anomalies_query(st, route or "all", str(a), str(b))
            if not r["available"]:
                text = r["message"]
            elif not r["events"]:
                text = f"Аномалий {'на маршруте ' + route if route else 'в сети'} за {a:%d.%m}–{b:%d.%m.%Y} не найдено."
            else:
                ev = sorted(r["events"], key=lambda e: -abs(e["score"]))
                kinds = ", ".join(f"{r['kinds'].get(k, k)} — {n}" for k, n in r["by_kind"].items())
                text = (f"ИИ-детектор нашёл {r['count']} аномальных дней {'на маршруте ' + route if route else 'в сети'} "
                        f"за {a:%d.%m}–{b:%d.%m.%Y} ({kinds}). Самые сильные:")
                items = [f"{date.fromisoformat(e['date']):%d.%m} · маршрут {e['route']} · {e['kind_ru']}: {e['label']}"
                         + (f" ({e['deviation_pct']:+.0f} % к типичному дню)".replace(".", ",") if e["deviation_pct"] is not None else "")
                         for e in ev[:6]]
            action = {"scroll": "anomCard", "route": route}
        else:
            d = p["date"] or ref
            _in_range(st, d)
            action = {"route": route or "all", "date": str(d), "hour": p["hour"]}
            if intent == "overflow":
                r = _fleet(st, route or "all", d, adj, plan_by)
                risks = [x for x in r["recommendations"] if x["type"] == "risk"]
                ov = r["overflow"]
                where = f"на маршруте {route}" if route else "в сети"
                if risks:
                    rs = sorted({x["route"] for x in risks}, key=lambda s: (len(s), s))
                    text = f"{_human(d)}: риск переполнения {where} — маршруты {', '.join(rs)}."
                else:
                    text = f"{_human(d)}: переполнения {where} при текущем выпуске не ожидается."
                if ov["available"] and ov["max"] is not None:
                    text += (f" Максимальная вероятность переполнения — {round(ov['max'] * 100)} % "
                             f"(маршрут {ov['route']}, {ov['hour']:02d}:00).")
                items = [x["text"] for x in risks[:6]]
                action["scroll"] = "fleetCard"
            elif intent == "vehicles":
                r = _fleet(st, route or "all", d, adj, plan_by)
                if route:
                    fr = r["routes"][0]
                    rows = fr["hours"]
                else:
                    fr, rows = None, r["total_hours"]
                h = p["hour"] if p["hour"] is not None else (8 if p.get("hour_word") == "утро" else 18 if p.get("hour_word") == "вечер" else None)
                who = f"Маршрут {route}" if route else "Все маршруты"
                if h is None:
                    x = max(rows, key=lambda x: x["required"])
                    h = x["hour"]
                    text = f"{who}, {_human(d)}: в пик ({h:02d}:00–{h + 1:02d}:00) нужно {x['required']} ваг. на линии"
                else:
                    x = rows[h]
                    text = f"{who}, {_human(d)}, {h:02d}:00–{(h + 1) % 24:02d}:00: нужно {x['required']} ваг. на линии"
                text += f" (сейчас ≈ {x['plan']})" if x.get("plan") else ""
                text += f", прогноз {_fmt(x['boardings'])} пасс./ч"
                if x.get("boardings_p10") is not None:
                    text += f" (80 %: {_fmt(x['boardings_p10'])}–{_fmt(x['boardings_p90'])})"
                if x.get("headway_min"):
                    text += f", интервал ≈ {x['headway_min']:.0f} мин".replace(".", ",")
                if x.get("p_overflow") is not None:
                    text += f", вероятность переполнения {round(x['p_overflow'] * 100)} %"
                text += "."
                if plan_by == "p90" and r["plan_by"] == "p90":
                    text += " Расчёт по P90 (с запасом на верхнюю границу прогноза)."
                if fr:
                    items = [f"{fr['vehicle_model']}, вместимость {fr['capacity']} пасс., оборот {fr['round_trip_min']:.0f} мин"]
                items += [rec["text"] for rec in r["recommendations"] if rec["type"] == "risk"][:3]
                action.update({"hour": h, "scroll": "fleetCard"})
            elif intent == "peak":
                src = "history" if d <= st.coverage["history"][1] else "forecast"
                k = Q.kpi_query(st, route or "all", str(d), str(d), 0, 23, src, adj)
                who = f"маршрута {route}" if route else "сети"
                text = (f"Час пик {who} {_human(d)}: {k['peak_hour']:02d}:00–{k['peak_hour'] + 1:02d}:00, "
                        f"{_fmt(k['max_hourly'])} пасс./ч ({'факт' if src == 'history' else 'прогноз'}); за сутки {_fmt(k['total'])}.")
                action["hour"] = k["peak_hour"]
            else:  # load
                src = "history" if d <= st.coverage["history"][1] else "forecast"
                who = f"Маршрут {route}" if route else "Все маршруты"
                s = Q.series_query(st, src, route or "all", str(d), str(d), 0, 23, "hour", adj)
                pts = s["points"]
                kind = "факт" if src == "history" else "прогноз"
                if p["hour"] is not None:
                    x = pts[p["hour"]]
                    text = f"{who}, {_human(d)}, {p['hour']:02d}:00–{(p['hour'] + 1) % 24:02d}:00: {kind} {_fmt(x['value'])} пасс. за час"
                    if x.get("p10") is not None:
                        text += f" (80 % интервал {_fmt(x['p10'])}–{_fmt(x['p90'])})"
                    text += "."
                else:
                    sm = s["summary"]
                    text = (f"{who}, {_human(d)}: {kind} {_fmt(sm['total'])} пасс. за сутки, пик "
                            f"{sm['peak_hour']:02d}:00 — {_fmt(sm['max_hourly'])} пасс./ч.")
                    lo = sum(x["p10"] for x in pts if x.get("p10") is not None)
                    hi = sum(x["p90"] for x in pts if x.get("p90") is not None)
                    if hi:
                        text += f" 80 % интервал на сутки: {_fmt(lo)}–{_fmt(hi)}."
                if src == "history":
                    an = Q.anomalies_query(st, route or "all", str(d), str(d))
                    items = [f"Аномалия ({e['kind_ru']}, маршрут {e['route']}): {e['label']}" for e in an["events"]]
    except ApiError as e:
        text, items = e.message, []
    return {"question": q, "intent": intent,
            "parsed": {"route": p["route_raw"], "date": str(p["date"]) if p["date"] else None, "hour": p["hour"],
                       "month": p["month"]},
            "ref_date": str(ref), "answer": text, "items": items, "action": action,
            "engine": "правила и шаблоны по данным сервиса (без внешних LLM)"}
