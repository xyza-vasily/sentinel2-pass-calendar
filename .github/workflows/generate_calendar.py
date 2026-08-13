"""
Regenerates index.html: a Sentinel-2A/2B overpass calendar for a fixed
location, computed by propagating fresh orbital elements one year forward.
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import requests
from skyfield.api import load, EarthSatellite, wgs84

# ---- configuration -------------------------------------------------------

TARGET_LAT = 48.2359
TARGET_LON = 16.5900
LOCATION_LABEL = "Lower Austria"
LOCAL_TZ = "Europe/Vienna"

SATELLITES = [
    (40697, "Sentinel-2A"),
    (42063, "Sentinel-2B"),
]

HALF_SWATH_KM = 145.0
FORECAST_DAYS = 370
STEP_SECONDS = 30
CHUNK_DAYS = 5

# ---- fetch fresh TLEs from CelesTrak --------------------------------------

def fetch_tle(catnr):
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    lines = [l for l in resp.text.strip().splitlines() if l.strip()]
    if len(lines) >= 3:
        return lines[-2], lines[-1]
    return lines[0], lines[1]


def find_close_approaches(sat, ts, t0_tt, total_days, step_seconds, chunk_days, label):
    results = []
    step_days = step_seconds / 86400.0
    pts_per_chunk = int(chunk_days * 86400 / step_seconds)
    n_chunks = int(np.ceil(total_days / chunk_days))

    for i in range(n_chunks):
        chunk_start_tt = t0_tt + i * chunk_days
        offsets = np.arange(pts_per_chunk) * step_days
        times = ts.tt_jd(chunk_start_tt + offsets)

        geocentric = sat.at(times)
        subpoint = wgs84.subpoint(geocentric)
        lats = subpoint.latitude.degrees
        lons = subpoint.longitude.degrees

        lat1 = np.radians(lats)
        lon1 = np.radians(lons)
        lat2 = np.radians(TARGET_LAT)
        lon2 = np.radians(TARGET_LON)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
        dist_km = 2 * 6371 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

        below = dist_km < HALF_SWATH_KM
        idx = np.where(below)[0]
        if len(idx) == 0:
            continue
        splits = np.where(np.diff(idx) > 1)[0]
        clusters = np.split(idx, splits + 1)
        n = pts_per_chunk
        for c in clusters:
            if c[0] == 0 or c[-1] == n - 1:
                continue
            sub_d = dist_km[c]
            min_i = c[np.argmin(sub_d)]
            results.append((times[min_i].utc_iso(), label))
    return results


def main():
    ts = load.timescale()
    start = datetime.now(timezone.utc)
    t0 = ts.utc(start.year, start.month, start.day)

    all_results = []
    for catnr, label in SATELLITES:
        line1, line2 = fetch_tle(catnr)
        sat = EarthSatellite(line1, line2, label, ts)
        res = find_close_approaches(
            sat, ts, t0.tt, FORECAST_DAYS, STEP_SECONDS, CHUNK_DAYS, label
        )
        all_results.extend(res)

    local_tz = ZoneInfo(LOCAL_TZ)
    rows = []
    for t_iso, label in all_results:
        dt_utc = datetime.strptime(t_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(local_tz)
        kind = "day" if 7 <= dt_local.hour <= 16 else "night"
        rows.append({
            "date": dt_local.strftime("%Y-%m-%d"),
            "time": dt_local.strftime("%H:%M"),
            "sat": label.replace("Sentinel-", ""),
            "type": kind,
        })
    rows.sort(key=lambda r: (r["date"], r["time"]))

    passes_json = json.dumps(rows)
    generated_at = start.strftime("%Y-%m-%d %H:%M UTC")

    template = open("template.html", encoding="utf-8").read()
    html = template.replace("__PASSES_JSON__", passes_json)
    html = html.replace("__GENERATED_AT__", generated_at)
    html = html.replace("__LOCATION_LABEL__", LOCATION_LABEL)
    html = html.replace("__LOCAL_TZ__", LOCAL_TZ)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote index.html with {len(rows)} passes, generated at {generated_at}")


if __name__ == "__main__":
    main()
