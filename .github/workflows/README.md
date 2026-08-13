# Sentinel-2 pass calendar

A static, auto-updating calendar showing when Sentinel-2A / 2B pass over Lower Austria.

## One-time setup

1. In the repo, go to **Settings -> Pages** and set **Source** to **GitHub Actions**.
2. Go to the **Actions** tab and run the **Update Sentinel-2 pass calendar** workflow once manually.
3. Your calendar will be at `https://xyza-vasily.github.io/sentinel2-pass-calendar/`

## Changing the location

Edit the constants at the top of `generate_calendar.py`:
- `TARGET_LAT` and `TARGET_LON`
- `LOCATION_LABEL`
- `LOCAL_TZ`
