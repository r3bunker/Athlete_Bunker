"""Display formatting with metric/imperial support, sport-aware."""

M_PER_MILE = 1609.344
M_PER_YD = 0.9144


def fmt_duration(seconds):
    if not seconds:
        return "–"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_hours(seconds):
    if not seconds:
        return "0.0"
    return f"{seconds / 3600.0:.1f}"


def fmt_distance(meters, sport, units):
    """Run/bike in mi or km; swim in yd or m."""
    if meters is None:
        return "–"
    if sport == "swim":
        if units == "imperial":
            return f"{meters / M_PER_YD:,.0f} yd"
        return f"{meters:,.0f} m"
    if units == "imperial":
        return f"{meters / M_PER_MILE:.2f} mi"
    return f"{meters / 1000.0:.2f} km"


def fmt_speed(mps, units):
    if not mps:
        return "–"
    if units == "imperial":
        return f"{mps * 3600 / M_PER_MILE:.1f} mph"
    return f"{mps * 3.6:.1f} km/h"


def _pace_str(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_pace(mps, sport, units):
    """Run pace per mi/km; swim pace per 100 yd / 100 m."""
    if not mps:
        return "–"
    if sport == "swim":
        per = (100 * M_PER_YD if units == "imperial" else 100.0) / mps
        unit = "/100yd" if units == "imperial" else "/100m"
        return f"{_pace_str(per)} {unit}"
    per = (M_PER_MILE if units == "imperial" else 1000.0) / mps
    unit = "/mi" if units == "imperial" else "/km"
    return f"{_pace_str(per)} {unit}"


def fmt_speed_or_pace(mps, sport, units):
    """The natural display for each sport: pace for run/swim, speed for bike."""
    if sport in ("run", "swim"):
        return fmt_pace(mps, sport, units)
    return fmt_speed(mps, units)


def fmt_elev(meters, units):
    if meters is None:
        return "–"
    if units == "imperial":
        return f"{meters * 3.28084:,.0f} ft"
    return f"{meters:,.0f} m"


def register_filters(app):
    app.jinja_env.filters["duration"] = fmt_duration
    app.jinja_env.filters["hours"] = fmt_hours
    app.jinja_env.filters["distance"] = fmt_distance
    app.jinja_env.filters["speed"] = fmt_speed
    app.jinja_env.filters["pace"] = fmt_pace
    app.jinja_env.filters["speed_or_pace"] = fmt_speed_or_pace
    app.jinja_env.filters["elev"] = fmt_elev
