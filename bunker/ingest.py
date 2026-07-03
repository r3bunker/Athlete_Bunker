"""Turn a parsed session into a fully-computed activity bundle and store it."""
import hashlib
from datetime import timedelta

from . import metrics
from .db import insert_activity

MAX_STREAM_POINTS = 2000

SPORT_TITLES = {"run": "Run", "bike": "Ride", "swim": "Swim", "other": "Workout"}


def _clean(values):
    return [v for v in values if v is not None]


def _elevation_gain(t, alt):
    """Gain/loss from a smoothed altitude stream (3 m hysteresis)."""
    samples = metrics.resample_1hz(t, alt)
    samples = [s for s in samples if s is not None]
    if len(samples) < 2:
        return None, None
    smoothed = metrics.rolling_average(samples, 10)
    gain = loss = 0.0
    ref = smoothed[0]
    for v in smoothed[1:]:
        delta = v - ref
        if delta >= 3.0:
            gain += delta
            ref = v
        elif delta <= -3.0:
            loss += -delta
            ref = v
    return round(gain, 1), round(loss, 1)


def _downsample(streams):
    n = len(streams.get("t") or [])
    if n == 0:
        return None
    stride = max(1, n // MAX_STREAM_POINTS)
    out = {}
    for key, values in streams.items():
        if values and any(v is not None for v in values):
            sampled = values[::stride]
            out[key] = [round(v, 6) if isinstance(v, float) else v for v in sampled]
    return out if out.get("t") else None


def _speed_from_distance(t, dist):
    """Derive a speed stream from cumulative distance (TCX/GPX often lack one)."""
    speed = [None] * len(t)
    prev_i = None
    for i in range(len(t)):
        if dist[i] is None:
            continue
        if prev_i is not None:
            dt = t[i] - t[prev_i]
            if dt > 0:
                speed[i] = max(0.0, (dist[i] - dist[prev_i]) / dt)
        prev_i = i
    return speed


def process_session(session, settings, source_file=None, file_hash=None):
    """Compute every derived metric for one parsed session.

    Returns (activity_dict, laps, downsampled_streams, peaks).
    """
    sport = session["sport"]
    rec = session.get("records") or {}
    t = rec.get("t") or []
    hr = rec.get("hr") or []
    power = rec.get("power") or []
    speed = rec.get("speed") or []
    alt = rec.get("alt") or []
    dist = rec.get("dist") or []
    if t and not _clean(speed) and _clean(dist):
        speed = _speed_from_distance(t, dist)
        rec["speed"] = speed

    duration_s = session.get("duration_s") or (t[-1] if t else None)
    moving_s = session.get("moving_s") or duration_s
    distance_m = session.get("distance_m")
    if distance_m is None:
        last_dist = next((d for d in reversed(dist) if d is not None), None)
        distance_m = last_dist

    avg_hr = session.get("avg_hr") or metrics._mean(hr)
    max_hr = session.get("max_hr") or (max(_clean(hr)) if _clean(hr) else None)
    avg_power = session.get("avg_power") or metrics._mean(power)
    max_power = session.get("max_power") or (max(_clean(power)) if _clean(power) else None)
    avg_cadence = session.get("avg_cadence") or metrics._mean(rec.get("cad") or [])
    max_cadence = session.get("max_cadence") or (max(_clean(rec.get("cad") or []), default=None))
    avg_temp = session.get("avg_temp") or metrics._mean(rec.get("temp") or [])
    avg_speed = session.get("avg_speed")
    if avg_speed is None and distance_m and moving_s:
        avg_speed = distance_m / moving_s
    max_speed = session.get("max_speed") or (max(_clean(speed)) if _clean(speed) else None)

    np = session.get("np_device") or metrics.normalized_power(t, power)
    ngp = metrics.ngp_speed(t, speed, alt, dist) if sport == "run" else None

    tss, intensity, method = metrics.compute_tss(
        sport, moving_s or duration_s, settings,
        t=t, power=power, hr=hr, ngp=ngp, avg_speed=avg_speed, np=np)

    # Efficiency factor: NP/HR on the bike, NGP (m/min)/HR on the run
    output_for_ef = np if sport == "bike" else (ngp * 60 if ngp else None)
    ef = metrics.efficiency_factor(output_for_ef, avg_hr)
    vi = metrics.variability_index(np, avg_power)
    dec_output = power if _clean(power) else speed
    dec = metrics.decoupling(t, dec_output, hr) if sport in ("bike", "run") else None

    elev_gain = session.get("elev_gain_m")
    elev_loss = session.get("elev_loss_m")
    if elev_gain is None and _clean(alt):
        elev_gain, elev_loss = _elevation_gain(t, alt)

    work_kj = None
    if avg_power and moving_s:
        work_kj = round(avg_power * moving_s / 1000.0, 0)

    import json
    hr_z = metrics.time_in_zones(t, hr, metrics.zone_bounds(sport, "hr", settings))
    pw_z = metrics.time_in_zones(t, power, metrics.zone_bounds(sport, "power", settings)) if sport == "bike" else None
    pace_z = metrics.time_in_zones(t, speed, metrics.zone_bounds(sport, "pace", settings)) if sport in ("run", "swim") else None

    start = session["start_time"]
    offset = timedelta(hours=settings.get("timezone_offset_hours") or 0)
    date_local = (start + offset).date().isoformat()

    name = session.get("name")
    if not name:
        hour = (start + offset).hour
        part = "Morning" if hour < 12 else ("Afternoon" if hour < 17 else "Evening")
        name = f"{part} {SPORT_TITLES.get(sport, 'Workout')}"

    activity = {
        "file_hash": file_hash,
        "source_file": source_file,
        "sport": sport,
        "sub_sport": session.get("sub_sport"),
        "name": name,
        "start_time": start.isoformat(),
        "date_local": date_local,
        "duration_s": duration_s,
        "moving_s": moving_s,
        "distance_m": distance_m,
        "avg_hr": round(avg_hr, 1) if avg_hr else None,
        "max_hr": max_hr,
        "avg_power": round(avg_power, 1) if avg_power else None,
        "max_power": max_power,
        "np": round(np, 1) if np else None,
        "ngp_speed": round(ngp, 3) if ngp else None,
        "intensity": round(intensity, 3) if intensity else None,
        "tss": round(tss, 1) if tss else None,
        "tss_method": method,
        "avg_speed": round(avg_speed, 3) if avg_speed else None,
        "max_speed": round(max_speed, 3) if max_speed else None,
        "avg_cadence": round(avg_cadence, 1) if avg_cadence else None,
        "max_cadence": max_cadence,
        "elev_gain_m": elev_gain,
        "elev_loss_m": elev_loss,
        "calories": session.get("calories"),
        "avg_temp": round(avg_temp, 1) if avg_temp else None,
        "work_kj": work_kj,
        "ef": round(ef, 2) if ef else None,
        "vi": round(vi, 2) if vi else None,
        "decoupling": round(dec, 1) if dec is not None else None,
        "hr_zones": json.dumps(hr_z) if hr_z else None,
        "power_zones": json.dumps(pw_z) if pw_z else None,
        "pace_zones": json.dumps(pace_z) if pace_z else None,
        "has_gps": 1 if _clean(rec.get("lat") or []) else 0,
    }

    peaks = []
    if _clean(power):
        peaks += [("power", d, v) for d, v in metrics.peak_values(t, power)]
    if _clean(hr):
        peaks += [("hr", d, v) for d, v in metrics.peak_values(t, hr)]
    if _clean(speed):
        peaks += [("speed", d, v) for d, v in metrics.peak_values(t, speed)]

    return activity, session.get("laps") or [], _downsample(rec), peaks


def ingest_upload(db, filename, data, settings):
    """Parse + process + store one uploaded file.

    Returns a list of result dicts, one per session in the file.
    """
    from .parser import parse_file, ParseError

    file_hash = hashlib.sha256(data).hexdigest()
    try:
        sessions = parse_file(filename, data)
    except ParseError as exc:
        return [{"file": filename, "status": "error", "message": str(exc)}]

    results = []
    for session in sessions:
        if session.get("start_time") is None:
            results.append({"file": filename, "status": "error",
                            "message": "Session missing start time"})
            continue
        activity, laps, streams, peaks = process_session(
            session, settings, source_file=filename, file_hash=file_hash)
        new_id = insert_activity(db, activity, laps, streams, peaks)
        if new_id is None:
            results.append({"file": filename, "status": "duplicate",
                            "message": "Already uploaded"})
        else:
            results.append({"file": filename, "status": "ok", "id": new_id,
                            "sport": activity["sport"], "name": activity["name"],
                            "tss": activity["tss"], "date": activity["date_local"]})
    return results
