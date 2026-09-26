# Build log: product service

2026-09-26
- Looked at the data. labels train+test = 57,551 route-hour cells (Jan–Oct 2025, 9 routes, no route 5). In the directory xlsx, sheet «Порядок_с_координатами» has stops with lat/lon for routes 1–12 (1, 5, 7, 11, 12 are relevant here).
- `scripts/prepare_data.py` builds `data/` (history, forecast, explain, stops.json, routes.json, pipeline_report.json, meta.json). The container is self-contained, and the paths can be overridden with env vars.
- Backend: FastAPI. Dense float32 cubes [route, day, hour] for history, forecast and combined. JSON bytes are cached with an LRU. Errors are unified as JSON with Russian messages (custom handlers for ApiError, RequestValidationError, 404/405 and 500). Metrics middleware is pure ASGI.
- Endpoints: routes, stops, forecast, history, series, forecast/stop, map, kpi, scenario/year, explain, export (csv/xlsx), pipeline/report, health, metrics.
- Frontend: vanilla JS + Leaflet + ECharts. Map with hour slider and play, top stops, KPIs, line chart (day/month/year), heatmap, route table, export, light/dark theme, mobile layout. Checked in headless Chrome (playwright) → docs/screenshots.
- Fixed: Nov 3 2025 was a moved day off, so the default date is now Nov 11. Leaflet size is invalidated after layout. Wheel zoom is enabled only after a click on the map. The day KPI now compares with the same weekday of the previous month.
- Coordinator update: switched to `final_candidate.csv` + `_explain.csv`. Explain factors are named in Russian (special/weather/rules), and the `note` column is shown. Route 5 now has forecast from 2025-12-16 (no history → clear 404 on /history and 400 on the year scenario; map overlay before launch). Stop binding now comes from `experiments/route_stops.csv`. Added `/pipeline/report` and the «Качество данных» block.
- Tests: 21 pytest tests pass.
- Docker: Docker Desktop 4.60 crashes at startup (stale `%LOCALAPPDATA%\Docker\run\dockerInference` socket, "file cannot be accessed by the system"). I did not touch host folders, so `docker compose up --build` could not be run here. Dockerfile and compose were reviewed. `scripts/bench_docker.ps1` is ready for a one-command container benchmark with docker stats.
- Performance, 2-CPU affinity emulation on the host (2 workers): 3.3k RPS, p95 12.6 ms at 16 connections; 3.6k RPS, p95 45 ms at 64; 3.4k RPS, p95 189 ms at 256; RAM ≤ 460 MB. 4 workers were worse (p95 58 ms at 64 connections, 633 MB), so the default is WORKERS=2.

Round 2 (judging criteria)
- Data refreshed: final_candidate.csv v08 (LB 0.90167) + explain (weather_mult is now non-trivial) + daily weather (06–21 h aggregation, as in src/adjust.py) + fleet.json (vehicle class from «Наряд», speed from «Расписание», lengths from geometry).
- Correction coefficients (`app/adjust.py`): k_level, k_special, w_precip, w_cold, w_floor, w_scenario, k_event. They work as API query params on forecast/series/stop/map/kpi/fleet/year/weather/export. Responses include `delta` (было → стало) and `baseline`. The defaults reproduce the model: recomputed weather matches the file within 5e-4.
- Rolling stock `/fleet`: trams needed per hour, current supply estimated from the previous 4 weeks of actuals, risk/surplus statuses, Russian recommendations. The UI panel has editable assumptions.
- Year = explicit «сценарный прогноз» for Jan–Dec 2026 with a ±band (default 10 % ≈ 1 − LB). Route 5 uses network seasonality. Month = daily totals.
- UI: corrections panel, fleet panel, new month and year charts, export with corrections and a scenario export. Only the 10 target routes are shown.
- Tests: 31 pass. Perf, 2 CPUs pinned, heavier mix: 2.7k RPS, p95 9.8 ms at 16 connections; 2.5k RPS, p95 37 ms at 64; 2.0k RPS, p95 274 ms at 256; RAM ≤ 484 MB. Docker Desktop is still broken on the dev machine.
