"""
Regenerates index.html: a Sentinel-2A/2B overpass calendar for a fixed
location, computed by propagating fresh orbital elements one year forward.
"""
import json
from datetime import datetime, timezone, timedelta
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

# ---- Special event dates ------------------------------------------------

def get_special_events():
    """Return a list of special events with dates and types"""
    events = []
    
    # ---- UAV Flight dates (UPDATED) ----
    uav_dates = [
        "2026-08-11",
        "2026-09-10",
        "2026-09-30",
    ]
    for date_str in uav_dates:
        events.append({"date": date_str, "type": "uav_flight"})
    
    # ---- GRS Measurement: September 30 ----
    events.append({"date": "2026-09-30", "type": "grs_measurement"})
    
    # ---- Date ranges (display as dashed lines) ----------------------------
    
    # Harvest SB: Oct 1-16
    for day in range(1, 17):
        events.append({"date": f"2026-10-{day:02d}", "type": "harvest"})
    
    # Tillage: Oct 19-23
    for day in range(19, 24):
        events.append({"date": f"2026-10-{day:02d}", "type": "tillage"})
    
    # Sowing: Oct 26-30
    for day in range(26, 31):
        events.append({"date": f"2026-10-{day:02d}", "type": "sowing"})
    
    return events

# ---- Drill & Drop Reading schedule (every 2 weeks on Friday) ------------

def get_drill_drop_dates(start_date):
    """Generate Drill & Drop Reading dates every 2 weeks on Friday"""
    dates = []
    current = start_date
    
    # Find the first Friday on or after the start date
    while current.weekday() != 4:  # 4 = Friday
        current += timedelta(days=1)
    
    # Generate dates for the next year
    end_date = start_date + timedelta(days=365)
    while current <= end_date:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=14)  # Every 2 weeks
    
    return dates

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

    # ---- Get Sentinel-2 passes --------------------------------------------
    all_results = []
    for catnr, label in SATELLITES:
        line1, line2 = fetch_tle(catnr)
        sat = EarthSatellite(line1, line2, label, ts)
        res = find_close_approaches(
            sat, ts, t0.tt, FORECAST_DAYS, STEP_SECONDS, CHUNK_DAYS, label
        )
        all_results.extend(res)

    local_tz = ZoneInfo(LOCAL_TZ)
    
    # ---- Create sentinel pass data ----------------------------------------
    sentinel_rows = []
    for t_iso, label in all_results:
        dt_utc = datetime.strptime(t_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(local_tz)
        kind = "day" if 7 <= dt_local.hour <= 16 else "night"
        sentinel_rows.append({
            "date": dt_local.strftime("%Y-%m-%d"),
            "time": dt_local.strftime("%H:%M"),
            "sat": label.replace("Sentinel-", ""),
            "type": kind,
        })
    
    # ---- Create Drill & Drop Reading schedule -----------------------------
    # Start from August 21, 2026 (or current date if later)
    start_date = datetime(2026, 8, 21, tzinfo=timezone.utc)
    if start_date < start:
        start_date = start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    drill_drop_dates = get_drill_drop_dates(start_date)
    drill_drop_rows = [
        {"date": d, "type": "drill_drop"}
        for d in drill_drop_dates
    ]
    
    # ---- Get special events -----------------------------------------------
    special_rows = get_special_events()
    
    # ---- Combine all events -----------------------------------------------
    all_events = sentinel_rows + drill_drop_rows + special_rows
    
    # ---- Sort by date -----------------------------------------------------
    all_events.sort(key=lambda r: (r["date"], r.get("time", "00:00")))
    
    # ---- Debug: Print all special events to verify ------------------------
    print("\n===== SPECIAL EVENTS =====")
    for event in special_rows:
        print(f"  {event['date']}: {event['type']}")
    print("==========================\n")
    
    from collections import defaultdict
    by_date = defaultdict(list)
    for event in all_events:
        by_date[event["date"]].append(event)

    # ---- Generate HTML ----------------------------------------------------
    passes_json = json.dumps(all_events)
    generated_at = start.strftime("%Y-%m-%d %H:%M UTC")

    template = open("template.html", encoding="utf-8").read()
    html = template.replace("__PASSES_JSON__", passes_json)
    html = html.replace("__GENERATED_AT__", generated_at)
    html = html.replace("__LOCATION_LABEL__", LOCATION_LABEL)
    html = html.replace("__LOCAL_TZ__", LOCAL_TZ)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote index.html with {len(all_events)} events, generated at {generated_at}")
    print(f"Sentinel-2 passes: {len(sentinel_rows)}")
    print(f"Drill & Drop readings: {len(drill_drop_rows)}")
    print(f"Special events: {len(special_rows)}")
    print(f"Total events: {len(all_events)}")


if __name__ == "__main__":
    main()
