"""Pages and JSON APIs."""
import calendar as cal
import json
from collections import defaultdict
from datetime import date, timedelta

from flask import (Blueprint, Response, jsonify, redirect, render_template,
                   request, url_for)

from . import metrics
from .db import delete_activity, get_db, get_settings, save_settings
from .ingest import ingest_upload

bp = Blueprint("main", __name__)

SPORTS = ["swim", "bike", "run", "other"]


def _rows_to_dicts(rows):
    return [dict(r) for r in rows]


def _daily_tss(db):
    daily = defaultdict(float)
    for row in db.execute(
            "SELECT date_local, SUM(COALESCE(tss,0)) AS tss FROM activities GROUP BY date_local"):
        daily[date.fromisoformat(row["date_local"])] = row["tss"]
    return daily


# ------------------------------------------------------------------ pages

@bp.route("/")
def dashboard():
    db = get_db()
    settings = get_settings(db)
    today = date.today()

    daily = _daily_tss(db)
    pmc = metrics.pmc_series(daily, today - timedelta(days=1), today)
    current = pmc[-1] if pmc else {"ctl": 0, "atl": 0, "tsb": 0}

    def totals_since(days):
        row = db.execute(
            "SELECT COUNT(*) AS n, SUM(COALESCE(moving_s, duration_s)) AS secs,"
            " SUM(COALESCE(tss,0)) AS tss, SUM(COALESCE(distance_m,0)) AS dist"
            " FROM activities WHERE date_local >= ?",
            ((today - timedelta(days=days - 1)).isoformat(),)).fetchone()
        return dict(row)

    recent = _rows_to_dicts(db.execute(
        "SELECT * FROM activities ORDER BY start_time DESC LIMIT 8"))
    return render_template("dashboard.html", settings=settings, current=current,
                           week=totals_since(7), month=totals_since(28),
                           recent=recent, today=today)


@bp.route("/calendar")
@bp.route("/calendar/<int:year>/<int:month>")
def calendar_view(year=None, month=None):
    db = get_db()
    settings = get_settings(db)
    today = date.today()
    year = year or today.year
    month = month or today.month

    first = date(year, month, 1)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)

    c = cal.Calendar(firstweekday=0)  # Monday
    weeks = c.monthdatescalendar(year, month)
    lo, hi = weeks[0][0], weeks[-1][-1]

    acts = defaultdict(list)
    for row in db.execute(
            "SELECT id, sport, name, tss, distance_m, duration_s, moving_s, date_local"
            " FROM activities WHERE date_local BETWEEN ? AND ? ORDER BY start_time",
            (lo.isoformat(), hi.isoformat())):
        acts[row["date_local"]].append(dict(row))

    week_rows = []
    for week in weeks:
        days = []
        w_tss = w_secs = w_dist = 0.0
        for day in week:
            day_acts = acts.get(day.isoformat(), [])
            for a in day_acts:
                w_tss += a["tss"] or 0
                w_secs += a["moving_s"] or a["duration_s"] or 0
                w_dist += a["distance_m"] or 0
            days.append({"date": day, "in_month": day.month == month,
                         "is_today": day == today, "activities": day_acts})
        week_rows.append({"days": days, "tss": w_tss, "secs": w_secs})

    return render_template("calendar.html", settings=settings, weeks=week_rows,
                           year=year, month=month,
                           month_name=cal.month_name[month],
                           prev=prev_month, next=next_month, today=today)


@bp.route("/activities")
def activities():
    db = get_db()
    settings = get_settings(db)
    sport = request.args.get("sport")
    q = "SELECT * FROM activities"
    args = []
    if sport in SPORTS:
        q += " WHERE sport = ?"
        args.append(sport)
    q += " ORDER BY start_time DESC LIMIT 500"
    rows = _rows_to_dicts(db.execute(q, args))
    return render_template("activities.html", settings=settings,
                           activities=rows, sport=sport)


@bp.route("/activity/<int:activity_id>")
def activity_detail(activity_id):
    db = get_db()
    settings = get_settings(db)
    row = db.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if row is None:
        return render_template("404.html", settings=settings), 404
    activity = dict(row)
    for key in ("hr_zones", "power_zones", "pace_zones"):
        activity[key] = json.loads(activity[key]) if activity[key] else None
    laps = _rows_to_dicts(db.execute(
        "SELECT * FROM laps WHERE activity_id = ? ORDER BY lap_index", (activity_id,)))
    peaks = _rows_to_dicts(db.execute(
        "SELECT metric, duration_s, value FROM peaks WHERE activity_id = ?"
        " ORDER BY metric, duration_s", (activity_id,)))
    has_streams = db.execute(
        "SELECT 1 FROM streams WHERE activity_id = ?", (activity_id,)).fetchone() is not None

    zone_defs = {
        "hr": metrics.zone_bounds(activity["sport"], "hr", settings),
        "power": metrics.zone_bounds(activity["sport"], "power", settings),
        "pace": metrics.zone_bounds(activity["sport"], "pace", settings),
    }
    return render_template("activity.html", settings=settings, a=activity,
                           laps=laps, peaks=peaks, has_streams=has_streams,
                           zone_labels=metrics.ZONE_LABELS, zone_defs=zone_defs)


@bp.route("/activity/<int:activity_id>/delete", methods=["POST"])
def activity_delete(activity_id):
    db = get_db()
    delete_activity(db, activity_id)
    return redirect(url_for("main.activities"))


@bp.route("/upload")
def upload_page():
    db = get_db()
    return render_template("upload.html", settings=get_settings(db))


@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    db = get_db()
    if request.method == "POST":
        updates = {}
        for key, cast in [("athlete_name", str), ("units", str), ("ftp", float),
                          ("lthr_bike", float), ("lthr_run", float),
                          ("max_hr", float), ("resting_hr", float),
                          ("weight_kg", float),
                          ("timezone_offset_hours", float)]:
            raw = request.form.get(key)
            if raw not in (None, ""):
                try:
                    updates[key] = cast(raw)
                except ValueError:
                    pass
        # threshold run pace entered as mm:ss per mi/km; CSS as mm:ss per 100yd/100m
        units = request.form.get("units") or get_settings(db)["units"]
        pace_raw = request.form.get("threshold_pace_display")
        if pace_raw:
            sec = _parse_mmss(pace_raw)
            if sec:
                updates["threshold_pace"] = sec / 1.609344 if units == "imperial" else sec
        css_raw = request.form.get("swim_css_display")
        if css_raw:
            sec = _parse_mmss(css_raw)
            if sec:
                updates["swim_css"] = sec / 0.9144 if units == "imperial" else sec
        save_settings(db, updates)
        return redirect(url_for("main.settings_page"))

    settings = get_settings(db)
    zones = {
        "power": metrics.zone_bounds("bike", "power", settings),
        "hr_bike": metrics.zone_bounds("bike", "hr", settings),
        "hr_run": metrics.zone_bounds("run", "hr", settings),
        "pace_run": metrics.zone_bounds("run", "pace", settings),
        "pace_swim": metrics.zone_bounds("swim", "pace", settings),
    }
    imperial = settings["units"] == "imperial"
    pace_display = _fmt_mmss(settings["threshold_pace"] * (1.609344 if imperial else 1))
    css_display = _fmt_mmss(settings["swim_css"] * (0.9144 if imperial else 1))
    return render_template("settings.html", settings=settings, zones=zones,
                           zone_labels=metrics.ZONE_LABELS,
                           pace_display=pace_display, css_display=css_display)


def _fmt_mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _parse_mmss(text):
    try:
        if ":" in text:
            m, s = text.strip().split(":")
            return int(m) * 60 + int(s)
        return float(text)
    except ValueError:
        return None


# ------------------------------------------------------------------- APIs

@bp.route("/api/upload", methods=["POST"])
def api_upload():
    db = get_db()
    settings = get_settings(db)
    results = []
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        results.extend(ingest_upload(db, f.filename, f.read(), settings))
    return jsonify(results)


@bp.route("/api/pmc")
def api_pmc():
    db = get_db()
    days = min(int(request.args.get("days", 90)), 730)
    today = date.today()
    series = metrics.pmc_series(_daily_tss(db), today - timedelta(days=days - 1), today)
    return jsonify(series)


@bp.route("/api/weekly")
def api_weekly():
    """Hours and TSS per ISO week, split by sport, for the last N weeks."""
    db = get_db()
    weeks = min(int(request.args.get("weeks", 12)), 52)
    today = date.today()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    buckets = {}
    for row in db.execute(
            "SELECT date_local, sport, SUM(COALESCE(moving_s, duration_s, 0)) AS secs,"
            " SUM(COALESCE(tss,0)) AS tss, SUM(COALESCE(distance_m,0)) AS dist"
            " FROM activities WHERE date_local >= ? GROUP BY date_local, sport",
            (start.isoformat(),)):
        d = date.fromisoformat(row["date_local"])
        wk = (d - timedelta(days=d.weekday())).isoformat()
        b = buckets.setdefault(wk, {s: {"secs": 0, "tss": 0, "dist": 0} for s in SPORTS})
        sport = row["sport"] if row["sport"] in SPORTS else "other"
        b[sport]["secs"] += row["secs"]
        b[sport]["tss"] += row["tss"]
        b[sport]["dist"] += row["dist"]
    out = []
    wk = start
    while wk <= today:
        key = wk.isoformat()
        out.append({"week": key,
                    "sports": buckets.get(key, {s: {"secs": 0, "tss": 0, "dist": 0}
                                                for s in SPORTS})})
        wk += timedelta(weeks=1)
    return jsonify(out)


@bp.route("/api/zones")
def api_zones():
    """Time-in-HR-zone totals over the last N days, per sport."""
    db = get_db()
    days = min(int(request.args.get("days", 28)), 365)
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    totals = defaultdict(lambda: [0] * 6)
    for row in db.execute(
            "SELECT sport, hr_zones FROM activities"
            " WHERE date_local >= ? AND hr_zones IS NOT NULL", (since,)):
        zones = json.loads(row["hr_zones"])
        sport = row["sport"] if row["sport"] in SPORTS else "other"
        for i, v in enumerate(zones[:6]):
            totals[sport][i] += v
            totals["all"][i] += v
    return jsonify(totals)


@bp.route("/api/activity/<int:activity_id>/streams")
def api_streams(activity_id):
    db = get_db()
    row = db.execute("SELECT data FROM streams WHERE activity_id = ?",
                     (activity_id,)).fetchone()
    if row is None:
        return jsonify({}), 404
    return Response(row["data"], mimetype="application/json")


@bp.route("/api/peaks")
def api_peaks():
    """Best peak values across all activities in a window (personal records)."""
    db = get_db()
    days = min(int(request.args.get("days", 90)), 3650)
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = db.execute(
        "SELECT p.metric, p.duration_s, MAX(p.value) AS value"
        " FROM peaks p JOIN activities a ON a.id = p.activity_id"
        " WHERE a.date_local >= ? GROUP BY p.metric, p.duration_s"
        " ORDER BY p.metric, p.duration_s", (since,))
    out = defaultdict(list)
    for r in rows:
        out[r["metric"]].append({"duration_s": r["duration_s"], "value": r["value"]})
    return jsonify(out)
