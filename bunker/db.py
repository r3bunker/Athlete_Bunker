"""SQLite storage for activities, streams, laps, peaks and athlete settings."""
import json
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash       TEXT,
    source_file     TEXT,
    sport           TEXT NOT NULL,            -- swim | bike | run | other
    sub_sport       TEXT,
    name            TEXT,
    start_time      TEXT NOT NULL,            -- ISO8601 UTC
    date_local      TEXT NOT NULL,            -- YYYY-MM-DD in athlete-local time
    duration_s      REAL,                     -- elapsed
    moving_s        REAL,
    distance_m      REAL,
    avg_hr          REAL,
    max_hr          REAL,
    avg_power       REAL,
    max_power       REAL,
    np              REAL,                     -- normalized power (bike) / NGP speed stored separately
    ngp_speed       REAL,                     -- normalized graded pace as m/s (run)
    intensity       REAL,                     -- IF
    tss             REAL,
    tss_method      TEXT,                     -- power | pace | swim | hr | estimated
    avg_speed       REAL,                     -- m/s (moving)
    max_speed       REAL,
    avg_cadence     REAL,
    max_cadence     REAL,
    elev_gain_m     REAL,
    elev_loss_m     REAL,
    calories        REAL,
    avg_temp        REAL,
    work_kj         REAL,
    ef              REAL,                     -- efficiency factor
    vi              REAL,                     -- variability index
    decoupling      REAL,                     -- Pw:Hr / Pa:Hr percent
    hr_zones        TEXT,                     -- JSON seconds per zone
    power_zones     TEXT,
    pace_zones      TEXT,
    has_gps         INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date_local);
CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_hash
    ON activities(file_hash, start_time);

CREATE TABLE IF NOT EXISTS laps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    lap_index   INTEGER,
    duration_s  REAL,
    distance_m  REAL,
    avg_hr      REAL,
    max_hr      REAL,
    avg_power   REAL,
    max_power   REAL,
    avg_speed   REAL,
    avg_cadence REAL,
    elev_gain_m REAL
);
CREATE INDEX IF NOT EXISTS idx_laps_activity ON laps(activity_id);

CREATE TABLE IF NOT EXISTS streams (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    data        TEXT NOT NULL                 -- JSON: {t:[],hr:[],power:[],speed:[],cad:[],alt:[],dist:[],lat:[],lng:[],temp:[]}
);

CREATE TABLE IF NOT EXISTS peaks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    metric      TEXT NOT NULL,                -- power | hr | speed
    duration_s  INTEGER NOT NULL,
    value       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_peaks_activity ON peaks(activity_id);
CREATE INDEX IF NOT EXISTS idx_peaks_metric ON peaks(metric, duration_s);
"""

DEFAULT_SETTINGS = {
    "athlete_name": "Athlete",
    "units": "imperial",            # imperial | metric
    "ftp": 250,                     # watts
    "lthr_bike": 160,               # bpm
    "lthr_run": 168,                # bpm
    "max_hr": 190,                  # bpm
    "resting_hr": 50,               # bpm
    "threshold_pace": 270,          # run threshold, seconds per km
    "swim_css": 105,                # critical swim speed, seconds per 100 m
    "weight_kg": 75,
    "timezone_offset_hours": -7,    # used to bucket activities into local days
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def get_settings(db):
    settings = dict(DEFAULT_SETTINGS)
    for row in db.execute("SELECT key, value FROM settings"):
        try:
            settings[row["key"]] = json.loads(row["value"])
        except (ValueError, TypeError):
            settings[row["key"]] = row["value"]
    return settings


def save_settings(db, updates):
    for key, value in updates.items():
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
    db.commit()


def insert_activity(db, activity, laps, streams, peaks):
    """Insert a fully-computed activity bundle. Returns new id or None if duplicate."""
    cols = [
        "file_hash", "source_file", "sport", "sub_sport", "name", "start_time",
        "date_local", "duration_s", "moving_s", "distance_m", "avg_hr", "max_hr",
        "avg_power", "max_power", "np", "ngp_speed", "intensity", "tss",
        "tss_method", "avg_speed", "max_speed", "avg_cadence", "max_cadence",
        "elev_gain_m", "elev_loss_m", "calories", "avg_temp", "work_kj", "ef",
        "vi", "decoupling", "hr_zones", "power_zones", "pace_zones", "has_gps",
    ]
    try:
        cur = db.execute(
            f"INSERT INTO activities({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            [activity.get(c) for c in cols],
        )
    except sqlite3.IntegrityError:
        return None
    activity_id = cur.lastrowid
    for i, lap in enumerate(laps):
        db.execute(
            "INSERT INTO laps(activity_id, lap_index, duration_s, distance_m, avg_hr,"
            " max_hr, avg_power, max_power, avg_speed, avg_cadence, elev_gain_m)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (activity_id, i + 1, lap.get("duration_s"), lap.get("distance_m"),
             lap.get("avg_hr"), lap.get("max_hr"), lap.get("avg_power"),
             lap.get("max_power"), lap.get("avg_speed"), lap.get("avg_cadence"),
             lap.get("elev_gain_m")),
        )
    if streams:
        db.execute(
            "INSERT INTO streams(activity_id, data) VALUES(?, ?)",
            (activity_id, json.dumps(streams)),
        )
    for metric, duration_s, value in peaks:
        db.execute(
            "INSERT INTO peaks(activity_id, metric, duration_s, value) VALUES(?,?,?,?)",
            (activity_id, metric, duration_s, value),
        )
    db.commit()
    return activity_id


def delete_activity(db, activity_id):
    db.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
    db.commit()
