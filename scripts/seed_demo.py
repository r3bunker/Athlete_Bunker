#!/usr/bin/env python3
"""Seed the database with ~16 weeks of synthetic triathlon training so every
dashboard has data to show. Safe to re-run (duplicates are skipped).

Usage: python scripts/seed_demo.py [--days 112]
To start fresh afterwards, delete data/athlete_bunker.db.
"""
import argparse
import hashlib
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bunker import create_app
from bunker.db import get_db, get_settings
from bunker.ingest import process_session
from bunker.db import insert_activity

random.seed(42)

# Weekly pattern: (weekday, sport, minutes, intensity 0-1)
WEEK_PLAN = [
    (0, "swim", 55, 0.72),
    (1, "bike", 70, 0.80),   # intervals
    (2, "run", 50, 0.70),
    (3, "swim", 50, 0.75),
    (3, "run", 40, 0.85),    # tempo brick day
    (4, "bike", 60, 0.65),
    (5, "bike", 150, 0.68),  # long ride
    (6, "run", 80, 0.66),    # long run
]


def make_records(sport, minutes, effort, settings):
    """Synthesize 1 Hz-ish streams with warmup, steady work and variation."""
    n = minutes * 60
    t, hr, power, speed, cad, alt, dist = [], [], [], [], [], [], []
    lthr = settings["lthr_run"] if sport == "run" else settings["lthr_bike"]
    ftp = settings["ftp"]
    thr_speed = {"run": 1000.0 / settings["threshold_pace"],
                 "swim": 100.0 / settings["swim_css"],
                 "bike": 9.5}[sport]
    d = 0.0
    elevation = 100.0
    for i in range(0, n, 2):  # 0.5 Hz keeps files small
        ramp = min(1.0, i / 600.0)  # 10 min warmup
        wobble = 0.06 * math.sin(i / 180.0) + random.uniform(-0.04, 0.04)
        surge = 0.15 if sport == "bike" and effort > 0.75 and (i // 300) % 2 == 1 else 0.0
        level = effort * ramp * (1 + wobble) + surge * ramp
        t.append(float(i))
        hr.append(round(lthr * (0.62 + 0.42 * level)))
        if sport == "bike":
            power.append(max(0, round(ftp * level * 1.05)))
            v = thr_speed * (0.5 + 0.6 * level)
        else:
            power.append(None)
            v = thr_speed * (0.55 + 0.5 * level)
        speed.append(round(v, 2))
        cad.append(round({"run": 172, "bike": 88, "swim": 32}[sport] * (0.9 + 0.15 * level)))
        elevation += random.uniform(-0.4, 0.45) if sport == "bike" else random.uniform(-0.2, 0.22)
        alt.append(round(elevation, 1))
        d += v * 2
        dist.append(round(d, 1))
    return {"t": t, "hr": hr, "power": power, "speed": speed, "cad": cad,
            "alt": alt, "dist": dist, "lat": [None] * len(t),
            "lng": [None] * len(t), "temp": [None] * len(t)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=112)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db()
        settings = get_settings(db)
        today = datetime.now(timezone.utc).date()
        start_day = today - timedelta(days=args.days)
        created = 0
        day = start_day
        while day <= today:
            for weekday, sport, minutes, effort in WEEK_PLAN:
                if day.weekday() != weekday:
                    continue
                # progressive build with a recovery week every 4th
                week_no = (day - start_day).days // 7
                cycle = week_no % 4
                scale = [0.85, 0.95, 1.05, 0.7][cycle]
                mins = max(25, int(minutes * scale * random.uniform(0.92, 1.08)))
                records = make_records(sport, mins, effort, settings)
                start = datetime(day.year, day.month, day.day, 6 + weekday % 3, 30,
                                 tzinfo=timezone.utc) - timedelta(
                                     hours=settings["timezone_offset_hours"])
                session = {
                    "sport": sport, "sub_sport": None, "name": None,
                    "start_time": start,
                    "duration_s": float(mins * 60), "moving_s": float(mins * 60),
                    "distance_m": records["dist"][-1],
                    "calories": mins * {"swim": 9, "bike": 11, "run": 12}[sport],
                    "avg_hr": None, "max_hr": None, "avg_power": None,
                    "max_power": None, "avg_speed": None, "max_speed": None,
                    "avg_cadence": None, "max_cadence": None,
                    "elev_gain_m": None, "elev_loss_m": None, "avg_temp": None,
                    "np_device": None, "tss_device": None,
                    "records": records, "laps": [],
                }
                fake_hash = hashlib.sha256(
                    f"demo-{day}-{sport}-{mins}".encode()).hexdigest()
                activity, laps, streams, peaks = process_session(
                    session, settings, source_file="demo-data", file_hash=fake_hash)
                if insert_activity(db, activity, laps, streams, peaks):
                    created += 1
            day += timedelta(days=1)
        print(f"Seeded {created} demo activities into {app.config['DATABASE']}")


if __name__ == "__main__":
    main()
