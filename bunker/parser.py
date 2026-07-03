"""Parse Garmin activity files (.fit / .fit.gz / .tcx / .gpx) into a
normalized structure the ingest pipeline can process.

Each parsed session becomes:
{
  "sport": "run" | "bike" | "swim" | "other",
  "sub_sport": str | None,
  "name": str | None,
  "start_time": datetime (UTC),
  "duration_s", "moving_s", "distance_m", "calories",
  "avg_hr", "max_hr", "avg_power", "max_power", "avg_speed", "max_speed",
  "avg_cadence", "max_cadence", "elev_gain_m", "elev_loss_m", "avg_temp",
  "records": {"t": [...seconds from start], "hr": [], "power": [], "speed": [],
               "cad": [], "alt": [], "dist": [], "lat": [], "lng": [], "temp": []},
  "laps": [ {duration_s, distance_m, avg_hr, max_hr, avg_power, max_power,
             avg_speed, avg_cadence, elev_gain_m} ]
}

A multisport FIT file (e.g. a triathlon race) yields one session per leg.
"""
import gzip
import io
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import fitdecode

SEMI_TO_DEG = 180.0 / 2 ** 31

SPORT_MAP = {
    "running": "run", "trail_running": "run", "treadmill_running": "run",
    "cycling": "bike", "road_biking": "bike", "mountain_biking": "bike",
    "indoor_cycling": "bike", "virtual_ride": "bike", "gravel_cycling": "bike",
    "swimming": "swim", "lap_swimming": "swim", "open_water": "swim",
}

STREAM_KEYS = ["t", "hr", "power", "speed", "cad", "alt", "dist", "lat", "lng", "temp"]


class ParseError(Exception):
    pass


def normalize_sport(sport, sub_sport=None):
    for candidate in (sub_sport, sport):
        if candidate and str(candidate).lower() in SPORT_MAP:
            return SPORT_MAP[str(candidate).lower()]
    s = str(sport or "").lower()
    if "run" in s:
        return "run"
    if "cycl" in s or "bik" in s or "ride" in s:
        return "bike"
    if "swim" in s:
        return "swim"
    return "other"


def parse_file(filename, data):
    """Dispatch on extension; returns a list of session dicts."""
    lower = filename.lower()
    if lower.endswith(".gz"):
        data = gzip.decompress(data)
        lower = lower[:-3]
    if lower.endswith(".fit"):
        return parse_fit(data)
    if lower.endswith(".tcx"):
        return parse_tcx(data)
    if lower.endswith(".gpx"):
        return parse_gpx(data)
    raise ParseError(f"Unsupported file type: {filename}")


# ----------------------------------------------------------------- FIT

def _field(frame, *names):
    for n in names:
        if frame.has_field(n):
            v = frame.get_value(n)
            if v is not None:
                return v
    return None


def parse_fit(data):
    records, laps, sessions = [], [], []
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "record":
                    ts = _field(frame, "timestamp")
                    if ts is None:
                        continue
                    lat = _field(frame, "position_lat")
                    lng = _field(frame, "position_long")
                    records.append({
                        "ts": ts,
                        "hr": _field(frame, "heart_rate"),
                        "power": _field(frame, "power"),
                        "speed": _field(frame, "enhanced_speed", "speed"),
                        "cad": _field(frame, "cadence"),
                        "alt": _field(frame, "enhanced_altitude", "altitude"),
                        "dist": _field(frame, "distance"),
                        "lat": lat * SEMI_TO_DEG if lat is not None else None,
                        "lng": lng * SEMI_TO_DEG if lng is not None else None,
                        "temp": _field(frame, "temperature"),
                    })
                elif frame.name == "lap":
                    laps.append({
                        "start_time": _field(frame, "start_time"),
                        "duration_s": _field(frame, "total_timer_time", "total_elapsed_time"),
                        "distance_m": _field(frame, "total_distance"),
                        "avg_hr": _field(frame, "avg_heart_rate"),
                        "max_hr": _field(frame, "max_heart_rate"),
                        "avg_power": _field(frame, "avg_power"),
                        "max_power": _field(frame, "max_power"),
                        "avg_speed": _field(frame, "enhanced_avg_speed", "avg_speed"),
                        "avg_cadence": _field(frame, "avg_cadence"),
                        "elev_gain_m": _field(frame, "total_ascent"),
                    })
                elif frame.name == "session":
                    sessions.append({
                        "sport": _field(frame, "sport"),
                        "sub_sport": _field(frame, "sub_sport"),
                        "start_time": _field(frame, "start_time") or _field(frame, "timestamp"),
                        "duration_s": _field(frame, "total_elapsed_time"),
                        "moving_s": _field(frame, "total_timer_time"),
                        "distance_m": _field(frame, "total_distance"),
                        "calories": _field(frame, "total_calories"),
                        "avg_hr": _field(frame, "avg_heart_rate"),
                        "max_hr": _field(frame, "max_heart_rate"),
                        "avg_power": _field(frame, "avg_power"),
                        "max_power": _field(frame, "max_power"),
                        "avg_speed": _field(frame, "enhanced_avg_speed", "avg_speed"),
                        "max_speed": _field(frame, "enhanced_max_speed", "max_speed"),
                        "avg_cadence": _field(frame, "avg_cadence"),
                        "max_cadence": _field(frame, "max_cadence"),
                        "elev_gain_m": _field(frame, "total_ascent"),
                        "elev_loss_m": _field(frame, "total_descent"),
                        "avg_temp": _field(frame, "avg_temperature"),
                        "np_device": _field(frame, "normalized_power"),
                        "tss_device": _field(frame, "training_stress_score"),
                    })
    except Exception as exc:  # fitdecode raises several error types
        raise ParseError(f"Could not decode FIT file: {exc}") from exc

    if not sessions:
        if not records:
            raise ParseError("FIT file contains no session or record data")
        sessions = [_session_from_records(records)]

    out = []
    for sess in sessions:
        start = _to_utc(sess["start_time"])
        end_s = sess.get("duration_s") or 0
        sess_records = [r for r in records
                        if start is not None and _to_utc(r["ts"]) is not None
                        and 0 <= (_to_utc(r["ts"]) - start).total_seconds() <= end_s + 1]
        sess_laps = [l for l in laps
                     if l.get("start_time") is not None and start is not None
                     and 0 <= (_to_utc(l["start_time"]) - start).total_seconds() <= end_s + 1]
        session = dict(sess)
        session["sport"] = normalize_sport(sess.get("sport"), sess.get("sub_sport"))
        session["sub_sport"] = str(sess.get("sub_sport")) if sess.get("sub_sport") else None
        session["start_time"] = start
        session["name"] = None
        session["records"] = _records_to_streams(sess_records, start)
        session["laps"] = [{k: v for k, v in l.items() if k != "start_time"}
                           for l in sess_laps]
        out.append(session)
    return out


def _session_from_records(records):
    """Synthesize a session when a FIT file has records but no session frame."""
    start = records[0]["ts"]
    end = records[-1]["ts"]
    dist = next((r["dist"] for r in reversed(records) if r["dist"] is not None), None)
    return {
        "sport": None, "sub_sport": None, "start_time": start,
        "duration_s": (_to_utc(end) - _to_utc(start)).total_seconds(),
        "moving_s": None, "distance_m": dist, "calories": None,
        "avg_hr": None, "max_hr": None, "avg_power": None, "max_power": None,
        "avg_speed": None, "max_speed": None, "avg_cadence": None,
        "max_cadence": None, "elev_gain_m": None, "elev_loss_m": None,
        "avg_temp": None, "np_device": None, "tss_device": None,
    }


def _to_utc(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def _records_to_streams(records, start):
    streams = {k: [] for k in STREAM_KEYS}
    for r in records:
        ts = _to_utc(r["ts"])
        if ts is None or start is None:
            continue
        streams["t"].append(round((ts - start).total_seconds(), 1))
        streams["hr"].append(r.get("hr"))
        streams["power"].append(r.get("power"))
        streams["speed"].append(r.get("speed"))
        streams["cad"].append(r.get("cad"))
        streams["alt"].append(r.get("alt"))
        streams["dist"].append(r.get("dist"))
        streams["lat"].append(r.get("lat"))
        streams["lng"].append(r.get("lng"))
        streams["temp"].append(r.get("temp"))
    return streams


# ----------------------------------------------------------------- TCX

def _strip_ns(tag):
    return tag.split("}")[-1]


def parse_tcx(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"Invalid TCX: {exc}") from exc

    out = []
    for activity in root.iter():
        if _strip_ns(activity.tag) != "Activity":
            continue
        sport = normalize_sport(activity.get("Sport"))
        streams = {k: [] for k in STREAM_KEYS}
        laps_out = []
        start = None
        calories = 0.0
        for lap in activity:
            if _strip_ns(lap.tag) != "Lap":
                continue
            lap_info = {"duration_s": None, "distance_m": None, "avg_hr": None,
                        "max_hr": None, "avg_power": None, "max_power": None,
                        "avg_speed": None, "avg_cadence": None, "elev_gain_m": None}
            # lap totals live in direct children; iter() would also match
            # DistanceMeters inside trackpoints
            for child in lap:
                tag = _strip_ns(child.tag)
                if tag == "TotalTimeSeconds" and child.text:
                    lap_info["duration_s"] = float(child.text)
                elif tag == "DistanceMeters" and child.text:
                    lap_info["distance_m"] = float(child.text)
                elif tag == "Calories" and child.text:
                    calories += float(child.text)
                elif tag == "Track":
                    for tp in child:
                        if _strip_ns(tp.tag) != "Trackpoint":
                            continue
                        point = _parse_trackpoint(tp)
                        if point["time"] is None:
                            continue
                        if start is None:
                            start = point["time"]
                        streams["t"].append((point["time"] - start).total_seconds())
                        streams["hr"].append(point["hr"])
                        streams["power"].append(point["power"])
                        streams["speed"].append(point["speed"])
                        streams["cad"].append(point["cad"])
                        streams["alt"].append(point["alt"])
                        streams["dist"].append(point["dist"])
                        streams["lat"].append(point["lat"])
                        streams["lng"].append(point["lng"])
                        streams["temp"].append(None)
            laps_out.append(lap_info)
        if start is None:
            continue
        duration = sum(l["duration_s"] or 0 for l in laps_out) or (streams["t"][-1] if streams["t"] else 0)
        distance = next((d for d in reversed(streams["dist"]) if d is not None), None)
        if distance is None:
            distance = sum(l["distance_m"] or 0 for l in laps_out) or None
        out.append({
            "sport": sport, "sub_sport": None, "name": None, "start_time": start,
            "duration_s": duration, "moving_s": duration, "distance_m": distance,
            "calories": calories or None, "avg_hr": None, "max_hr": None,
            "avg_power": None, "max_power": None, "avg_speed": None,
            "max_speed": None, "avg_cadence": None, "max_cadence": None,
            "elev_gain_m": None, "elev_loss_m": None, "avg_temp": None,
            "np_device": None, "tss_device": None,
            "records": streams, "laps": laps_out,
        })
    if not out:
        raise ParseError("TCX file contains no activities")
    return out


def _parse_trackpoint(tp):
    point = {"time": None, "hr": None, "power": None, "speed": None, "cad": None,
             "alt": None, "dist": None, "lat": None, "lng": None}
    for el in tp.iter():
        tag = _strip_ns(el.tag)
        text = (el.text or "").strip()
        if tag == "Time" and text:
            point["time"] = _parse_iso(text)
        elif tag == "AltitudeMeters" and text:
            point["alt"] = float(text)
        elif tag == "DistanceMeters" and text:
            point["dist"] = float(text)
        elif tag == "LatitudeDegrees" and text:
            point["lat"] = float(text)
        elif tag == "LongitudeDegrees" and text:
            point["lng"] = float(text)
        elif tag == "Cadence" and text:
            point["cad"] = float(text)
        elif tag == "Value" and text and point["hr"] is None:
            parent_ok = True  # HeartRateBpm/Value is the only Value element in a Trackpoint
            if parent_ok:
                try:
                    point["hr"] = float(text)
                except ValueError:
                    pass
        elif tag in ("Speed",) and text:
            point["speed"] = float(text)
        elif tag in ("Watts",) and text:
            point["power"] = float(text)
        elif tag == "RunCadence" and text:
            point["cad"] = float(text)
    return point


def _parse_iso(text):
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------- GPX

def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_gpx(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"Invalid GPX: {exc}") from exc

    streams = {k: [] for k in STREAM_KEYS}
    start = None
    total_dist = 0.0
    prev = None
    sport_hint = None
    for el in root.iter():
        tag = _strip_ns(el.tag)
        if tag == "type" and el.text:
            sport_hint = el.text
        if tag != "trkpt":
            continue
        lat = float(el.get("lat"))
        lng = float(el.get("lon"))
        time = alt = hr = cad = None
        for child in el.iter():
            ctag = _strip_ns(child.tag)
            text = (child.text or "").strip()
            if ctag == "time" and text:
                time = _parse_iso(text)
            elif ctag == "ele" and text:
                alt = float(text)
            elif ctag == "hr" and text:
                hr = float(text)
            elif ctag == "cad" and text:
                cad = float(text)
        if time is None:
            continue
        if start is None:
            start = time
        speed = None
        if prev is not None:
            d = haversine_m(prev["lat"], prev["lng"], lat, lng)
            dt = (time - prev["time"]).total_seconds()
            total_dist += d
            if dt > 0:
                speed = d / dt
        streams["t"].append((time - start).total_seconds())
        streams["hr"].append(hr)
        streams["power"].append(None)
        streams["speed"].append(speed)
        streams["cad"].append(cad)
        streams["alt"].append(alt)
        streams["dist"].append(total_dist)
        streams["lat"].append(lat)
        streams["lng"].append(lng)
        streams["temp"].append(None)
        prev = {"lat": lat, "lng": lng, "time": time}

    if start is None:
        raise ParseError("GPX file contains no timed trackpoints")

    duration = streams["t"][-1]
    avg_speed = total_dist / duration if duration else None
    sport = normalize_sport(sport_hint)
    if sport == "other" and avg_speed:
        sport = "bike" if avg_speed > 5.5 else "run"
    return [{
        "sport": sport, "sub_sport": None, "name": None, "start_time": start,
        "duration_s": duration, "moving_s": duration, "distance_m": total_dist or None,
        "calories": None, "avg_hr": None, "max_hr": None, "avg_power": None,
        "max_power": None, "avg_speed": None, "max_speed": None,
        "avg_cadence": None, "max_cadence": None, "elev_gain_m": None,
        "elev_loss_m": None, "avg_temp": None, "np_device": None,
        "tss_device": None, "records": streams, "laps": [],
    }]
