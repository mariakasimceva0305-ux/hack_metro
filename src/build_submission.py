"""Final explainable model: prediction = L(route, daytype) × S(route, daytype, hour) × special_day_mult [× weather_mult].
Writes submission + explain file (per-cell decomposition for the dashboard)."""
import pandas as pd, numpy as np, argparse
from common import load_labels, full_grid, wape_score
from model_ls import forecast as ls_forecast, dtmap
from model_profile import daytype

# Special-day multipliers, estimated from 2025 history analogues (see INSIGHTS.md)
SPECIAL = {
    '2025-11-01': ('working Saturday (transferred workday)', 0.80),
    '2025-12-29': ('workday between weekend and New Year', 0.88),
    '2025-12-30': ('workday between weekend and New Year', 0.88),
    '2025-12-31': ('New Year Eve (day off)', 0.80),
}

def predict(hist, target, WL=2, WS=4, mode='wk4', lagg='median', special=True):
    t = target[['route','date','hour']].copy()
    t['base'] = ls_forecast(hist, t, WL, WS, mode, lagg, 'sum')
    t['special_mult'] = 1.0
    if special:
        # Dec 31: Saturday-like shape/level before scaling
        m31 = t.date == '2025-12-31'
        if m31.any():
            sat = t[m31].copy(); sat['date'] = pd.Timestamp('2025-12-27')
            t.loc[m31, 'base'] = ls_forecast(hist, sat, WL, WS, mode, lagg, 'sum')
        for day, (_, k) in SPECIAL.items():
            t.loc[t.date == day, 'special_mult'] = k
    t['prediction'] = t.base * t.special_mult
    return t

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--name', default='v02_ls_special'); a = ap.parse_args()
    d = load_labels()
    # backtest (special multipliers only matter for Nov–Dec dates; holiday→Sunday is inside daytype)
    for s, e in [('2025-10-01','2025-10-31'),('2025-09-15','2025-10-31'),('2025-02-01','2025-03-31'),('2025-04-01','2025-05-31')]:
        hist, fut = d[d.date < s], d[(d.date >= s) & (d.date <= e)]
        print(s, round(wape_score(fut.boardings.values, predict(hist, fut).prediction.values), 4))
    sub = predict(d, full_grid('2025-11-01', '2025-12-31'))
    sub.loc[sub.route == 5, ['base','prediction']] = 0
    sub['date'] = sub.date.dt.strftime('%Y-%m-%d'); sub['prediction'] = sub.prediction.round().astype(int)
    sub[['route','date','hour','prediction']].to_csv(f'submissions/{a.name}.csv', sep=';', index=False)
    sub.to_csv(f'submissions/{a.name}_explain.csv', sep=';', index=False)
    print(len(sub), 'total', sub.prediction.sum())
