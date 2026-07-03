# Athlete Bunker

A local, self-hosted triathlon training analytics site modeled on
TrainingPeaks. Upload your Garmin activity files and get the full metric
stack — TSS, IF, Normalized Power, CTL/ATL/TSB, zones, peaks — with nothing
leaving your machine.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000, go to **Settings** and enter your thresholds
(FTP, LTHR, run threshold pace, swim CSS), then drag your Garmin files onto
the **Upload** page.

Want to see the dashboards populated before uploading real data?

```bash
python scripts/seed_demo.py     # ~16 weeks of synthetic swim/bike/run training
```

To start over, delete `data/athlete_bunker.db`.

## Getting your Garmin files

- **Garmin Connect** (per activity): open the activity → gear icon →
  **Export Original** — that's the raw `.fit` file (sometimes zipped; `.fit.gz`
  works too). "Export to TCX/GPX" also works.
- **Bulk**: request your data archive at garmin.com/account/datamanagement, or
  plug the watch in via USB and copy `GARMIN/Activity/*.fit`.
- Multisport race files (triathlon mode) are split into one activity per leg
  automatically.

Supported formats: `.fit`, `.fit.gz`, `.tcx`, `.gpx`. Re-uploading the same
file is detected and skipped.

## What it computes

**Per activity**

| Metric | How |
|---|---|
| NP (Normalized Power) | Coggan 30 s rolling 4th-power average (bike) |
| NGP | Grade-adjusted run pace, normalized like NP |
| IF (Intensity Factor) | NP/FTP, NGP/threshold speed, or speed/CSS |
| TSS | power-based (bike), rTSS (run), sTSS (swim), hrTSS fallback, duration estimate as last resort |
| EF (Efficiency Factor) | NP or NGP (m/min) per heartbeat |
| VI (Variability Index) | NP ÷ average power |
| Pw:Hr / Pa:Hr decoupling | output-per-heartbeat drift, first half vs second half |
| Time in zones | HR, power and pace zones derived from your thresholds |
| Peaks | best 5 s … 60 min power, HR and speed |
| Elevation gain/loss | smoothed altitude with hysteresis (when the device didn't report it) |

**Across activities**

- **Performance Management Chart**: CTL (fitness, 42-day), ATL (fatigue,
  7-day), TSB (form) with daily TSS — 6 weeks to 1 year views.
- **Weekly training load** by sport (TSS, hours or distance).
- **Time-in-zone distribution** over the last 28 days.
- **Calendar** with per-week TSS and hours totals.

## Pages

- **Dashboard** — CTL/ATL/TSB tiles, PMC, weekly load, zone distribution, recent activities
- **Calendar** — month grid, color-coded by sport, weekly totals
- **Activities** — sortable list with per-sport filters
- **Activity detail** — summary tiles, synced pace/power/HR/cadence/elevation
  charts, route map, laps, zone histograms, peaks
- **Settings** — thresholds, units (imperial/metric), auto-computed zone tables
- **Upload** — drag-and-drop, multiple files at once

## Notes

- Everything is stored in a single SQLite file (`data/athlete_bunker.db`).
- Chart.js and Leaflet are vendored in `static/vendor/` so the site works
  offline; only the map's OpenStreetMap tiles need internet.
- Metrics are computed at upload time against your *current* thresholds. If
  you change a threshold, new uploads use the new value; history is kept as
  computed (same as TrainingPeaks' default behavior).
- Units: imperial shows miles/mph, /mi run pace and /100 yd swim pace; metric
  shows km, /km and /100 m.
- The UI is a dark Material You (Material 3) theme.

## Layout

```
app.py               # entry point
bunker/
  parser.py          # FIT / TCX / GPX → normalized sessions
  metrics.py         # NP, NGP, TSS family, zones, peaks, PMC math
  ingest.py          # parse → compute → store pipeline
  routes.py          # pages + JSON APIs
  db.py, fmt.py      # SQLite schema, display formatting
templates/, static/  # UI (vanilla JS + Chart.js + Leaflet)
scripts/seed_demo.py # synthetic training data for a demo
```
