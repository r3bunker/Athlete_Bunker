"""TrainingPeaks-style training metrics.

Implements the standard endurance-training math:

* Normalized Power (NP): 30 s rolling average of power, raised to the 4th
  power, averaged, then the 4th root (Coggan).
* NGP (Normalized Graded Pace): run speed adjusted for gradient using a
  Strava-style GAP polynomial, then normalized the same way as NP.
* IF (Intensity Factor) = NP / FTP (or NGP / threshold speed, etc).
* TSS = duration_h * IF^2 * 100, with sport-specific variants:
  power-based TSS (bike), rTSS (run, from NGP), sTSS (swim, IF cubed per
  TrainingPeaks convention), and hrTSS as the heart-rate fallback.
* CTL / ATL / TSB: exponentially-weighted fitness (42 d), fatigue (7 d) and
  form (CTL - ATL of the previous day) — the Performance Management Chart.
* EF, VI, Pw:Hr / Pa:Hr aerobic decoupling, time in zones, peak curves.
"""
import math
from datetime import date, timedelta

CTL_TC = 42.0   # fitness time constant, days
ATL_TC = 7.0    # fatigue time constant, days

PEAK_DURATIONS = [5, 10, 30, 60, 120, 300, 600, 1200, 3600]

# Zone boundaries as a fraction of the sport threshold. Upper bound of each
# zone; the last zone is open-ended.
POWER_ZONES = [0.55, 0.75, 0.90, 1.05, 1.20]           # Coggan Z1-Z6 (of FTP)
HR_ZONES = [0.81, 0.89, 0.93, 0.99, 1.02]              # Friel/Coggan (of LTHR)
PACE_ZONES = [0.78, 0.88, 0.95, 1.05, 1.15]            # of threshold speed
ZONE_LABELS = ["Z1 Recovery", "Z2 Endurance", "Z3 Tempo", "Z4 Threshold",
               "Z5 VO2max", "Z6 Anaerobic"]


# ---------------------------------------------------------------- helpers

def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def rolling_average(values, window):
    """Rolling mean over `window` samples; None values count as 0."""
    out = []
    acc = 0.0
    buf = []
    for v in values:
        v = v or 0.0
        buf.append(v)
        acc += v
        if len(buf) > window:
            acc -= buf.pop(0)
        out.append(acc / len(buf))
    return out


def resample_1hz(t, values):
    """Resample an irregularly-sampled stream onto a 1 Hz grid (hold last)."""
    if not t:
        return []
    out = []
    j = 0
    last = None
    for sec in range(int(t[-1]) + 1):
        while j < len(t) and t[j] <= sec:
            if values[j] is not None:
                last = values[j]
            j += 1
        out.append(last)
    return out


# ------------------------------------------------------------ power / pace

def normalized_power(t, power):
    """Coggan Normalized Power from a (t seconds, watts) stream."""
    p = resample_1hz(t, power)
    p = [v for v in (p or [])]
    if not p or len(p) < 60:
        return None
    rolled = rolling_average(p, 30)
    fourth = [v ** 4 for v in rolled[29:]]  # full windows only
    if not fourth:
        return None
    return _mean(fourth) ** 0.25


def grade_adjusted_speed(speed, grade):
    """Approximate GAP factor: cost of running at `grade` vs flat.

    Polynomial fit in the style of Strava's GAP model; clamped to sane
    gradients. Positive grade -> adjusted speed is faster than actual.
    """
    g = max(-0.30, min(0.30, grade or 0.0))
    factor = 1.0 + 2.74 * g + 5.4 * g * g
    return speed * max(0.4, factor)


def ngp_speed(t, speed, altitude, distance):
    """Normalized Graded Pace as a speed (m/s) for runs."""
    if not t or not speed:
        return None
    v = resample_1hz(t, speed)
    alt = resample_1hz(t, altitude) if altitude else None
    dist = resample_1hz(t, distance) if distance else None
    adjusted = []
    for i, s in enumerate(v):
        if s is None:
            adjusted.append(0.0)
            continue
        grade = 0.0
        if alt and dist and i >= 10:
            da = (alt[i] or 0) - (alt[i - 10] or 0) if alt[i] is not None and alt[i - 10] is not None else 0
            dd = (dist[i] or 0) - (dist[i - 10] or 0) if dist[i] is not None and dist[i - 10] is not None else 0
            if dd > 1:
                grade = da / dd
        adjusted.append(grade_adjusted_speed(s, grade))
    if len(adjusted) < 60:
        return _mean([a for a in adjusted if a]) if adjusted else None
    rolled = rolling_average(adjusted, 30)
    fourth = [x ** 4 for x in rolled[29:]]
    return _mean(fourth) ** 0.25 if fourth else None


# ------------------------------------------------------------------- TSS

def tss_from_power(duration_s, np, ftp):
    if not (np and ftp and duration_s):
        return None, None
    intensity = np / ftp
    return (duration_s * np * intensity) / (ftp * 3600.0) * 100.0, intensity


def tss_from_run_pace(duration_s, ngp, threshold_pace_s_per_km):
    """rTSS from Normalized Graded Pace (m/s) vs threshold pace."""
    if not (ngp and threshold_pace_s_per_km and duration_s):
        return None, None
    threshold_speed = 1000.0 / threshold_pace_s_per_km
    intensity = ngp / threshold_speed
    return duration_s / 3600.0 * intensity ** 2 * 100.0, intensity


def tss_from_swim(duration_s, avg_speed, css_s_per_100m):
    """sTSS: swim TSS uses IF cubed (TrainingPeaks convention)."""
    if not (avg_speed and css_s_per_100m and duration_s):
        return None, None
    css_speed = 100.0 / css_s_per_100m
    intensity = avg_speed / css_speed
    return duration_s / 3600.0 * intensity ** 3 * 100.0, intensity


def tss_from_hr(t, hr, lthr, duration_s):
    """hrTSS: per-sample (HR/LTHR)^2 accumulated over time."""
    if not (hr and lthr):
        return None, None
    samples = resample_1hz(t, hr)
    samples = [s for s in samples if s]
    if not samples:
        return None, None
    ratios2 = [(s / lthr) ** 2 for s in samples]
    mean_r2 = _mean(ratios2)
    hours = (duration_s or len(samples)) / 3600.0
    return hours * mean_r2 * 100.0, math.sqrt(mean_r2)


def compute_tss(sport, duration_s, settings, *, t=None, power=None, hr=None,
                ngp=None, avg_speed=None, np=None):
    """Sport-specific TSS with fallback chain. Returns (tss, if, method)."""
    if sport == "bike" and np:
        tss, i = tss_from_power(duration_s, np, settings.get("ftp"))
        if tss is not None:
            return tss, i, "power"
    if sport == "run" and ngp:
        tss, i = tss_from_run_pace(duration_s, ngp, settings.get("threshold_pace"))
        if tss is not None:
            return tss, i, "pace"
    if sport == "swim" and avg_speed:
        tss, i = tss_from_swim(duration_s, avg_speed, settings.get("swim_css"))
        if tss is not None:
            return tss, i, "swim"
    lthr = settings.get("lthr_run") if sport == "run" else settings.get("lthr_bike")
    if hr and lthr:
        tss, i = tss_from_hr(t, hr, lthr, duration_s)
        if tss is not None:
            return tss, i, "hr"
    # Last resort: assume an easy aerobic effort (IF 0.65)
    if duration_s:
        return duration_s / 3600.0 * 0.65 ** 2 * 100.0, 0.65, "estimated"
    return None, None, None


# ------------------------------------------------- efficiency & decoupling

def efficiency_factor(np_or_ngp, avg_hr):
    if not (np_or_ngp and avg_hr):
        return None
    return np_or_ngp / avg_hr


def variability_index(np, avg_power):
    if not (np and avg_power):
        return None
    return np / avg_power


def decoupling(t, output, hr):
    """Pw:Hr or Pa:Hr — drift of output/HR between first and second halves (%)."""
    if not (t and output and hr):
        return None
    o = resample_1hz(t, output)
    h = resample_1hz(t, hr)
    n = min(len(o), len(h))
    if n < 600:  # need at least 10 minutes to be meaningful
        return None
    half = n // 2
    def ratio(o_part, h_part):
        pairs = [(a, b) for a, b in zip(o_part, h_part) if a and b]
        if len(pairs) < 60:
            return None
        return _mean([a for a, _ in pairs]) / _mean([b for _, b in pairs])
    r1 = ratio(o[:half], h[:half])
    r2 = ratio(o[half:], h[half:])
    if not (r1 and r2):
        return None
    return (r1 - r2) / r1 * 100.0


# ------------------------------------------------------------------ zones

def zone_bounds(sport, kind, settings):
    """Absolute zone upper bounds for a sport/metric, from athlete settings."""
    if kind == "power" and settings.get("ftp"):
        return [f * settings["ftp"] for f in POWER_ZONES]
    if kind == "hr":
        lthr = settings.get("lthr_run") if sport == "run" else settings.get("lthr_bike")
        if lthr:
            return [f * lthr for f in HR_ZONES]
    if kind == "pace":
        if sport == "run" and settings.get("threshold_pace"):
            thr = 1000.0 / settings["threshold_pace"]
        elif sport == "swim" and settings.get("swim_css"):
            thr = 100.0 / settings["swim_css"]
        else:
            return None
        return [f * thr for f in PACE_ZONES]
    return None


def time_in_zones(t, values, bounds):
    """Seconds spent in each zone (len(bounds)+1 buckets)."""
    if not (values and bounds):
        return None
    samples = resample_1hz(t, values)
    zones = [0] * (len(bounds) + 1)
    for v in samples:
        if not v:
            continue
        for zi, ub in enumerate(bounds):
            if v <= ub:
                zones[zi] += 1
                break
        else:
            zones[-1] += 1
    return zones if any(zones) else None


# ------------------------------------------------------------------ peaks

def peak_values(t, values, durations=PEAK_DURATIONS):
    """Best rolling average for each duration. Returns [(duration, value)]."""
    samples = resample_1hz(t, values)
    samples = [v or 0.0 for v in samples]
    n = len(samples)
    if n < 5:
        return []
    prefix = [0.0]
    for v in samples:
        prefix.append(prefix[-1] + v)
    out = []
    for d in durations:
        if d > n:
            break
        best = max(prefix[i + d] - prefix[i] for i in range(n - d + 1)) / d
        if best > 0:
            out.append((d, round(best, 2)))
    return out


# ------------------------------------------------------------------- PMC

def pmc_series(daily_tss, start, end, seed_days=0):
    """CTL/ATL/TSB series over [start, end].

    daily_tss: dict of date -> total TSS. The recursion runs from the earliest
    data (or `start`) so values at `start` are already warmed up.
    """
    if daily_tss:
        first = min(min(daily_tss), start)
    else:
        first = start
    ctl = atl = 0.0
    out = []
    day = first
    prev_ctl = prev_atl = 0.0
    while day <= end:
        tss = daily_tss.get(day, 0.0)
        prev_ctl, prev_atl = ctl, atl
        ctl += (tss - ctl) / CTL_TC
        atl += (tss - atl) / ATL_TC
        if day >= start:
            out.append({
                "date": day.isoformat(),
                "tss": round(tss, 1),
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(prev_ctl - prev_atl, 1),
            })
        day += timedelta(days=1)
    return out
