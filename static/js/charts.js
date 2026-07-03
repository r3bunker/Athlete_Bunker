/* Shared Chart.js setup: reads theme tokens from CSS so charts match the
 * active light/dark theme. */
const AB = (() => {
  const css = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const theme = () => ({
    text: css("--text"),
    text2: css("--text-2"),
    muted: css("--muted"),
    grid: css("--grid"),
    baseline: css("--baseline"),
    surface: css("--surface-container"),      // cards, where charts live
    tooltipBg: css("--surface-container-high"),
    sports: {
      swim: css("--c-swim"),
      bike: css("--c-bike"),
      run: css("--c-run"),
      other: css("--c-other"),
    },
    pmc: { ctl: css("--pmc-ctl"), atl: css("--pmc-atl"), tsb: css("--pmc-tsb") },
    zones: [css("--z1"), css("--z2"), css("--z3"), css("--z4"), css("--z5"), css("--z6")],
  });

  function applyDefaults() {
    const t = theme();
    Chart.defaults.font.family =
      'system-ui, -apple-system, "Segoe UI", sans-serif';
    Chart.defaults.font.size = 11;
    Chart.defaults.color = t.muted;
    Chart.defaults.borderColor = t.grid;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.boxHeight = 10;
    Chart.defaults.plugins.legend.labels.color = t.text2;
    Chart.defaults.plugins.tooltip.backgroundColor = t.tooltipBg;
    Chart.defaults.plugins.tooltip.titleColor = t.text;
    Chart.defaults.plugins.tooltip.bodyColor = t.text2;
    Chart.defaults.plugins.tooltip.borderColor = t.baseline;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.animation = false;
  }

  const units = document.body.dataset.units || "metric";
  const M_PER_MILE = 1609.344, M_PER_YD = 0.9144;

  function fmtDuration(secs) {
    secs = Math.round(secs || 0);
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
             : `${m}:${String(s).padStart(2, "0")}`;
  }
  function fmtHours(secs) { return ((secs || 0) / 3600).toFixed(1); }
  function paceStr(secPer) {
    secPer = Math.round(secPer);
    return `${Math.floor(secPer / 60)}:${String(secPer % 60).padStart(2, "0")}`;
  }
  function fmtSpeedOrPace(mps, sport) {
    if (!mps) return "–";
    if (sport === "swim") {
      const per = (units === "imperial" ? 100 * M_PER_YD : 100) / mps;
      return `${paceStr(per)} ${units === "imperial" ? "/100yd" : "/100m"}`;
    }
    if (sport === "run") {
      const per = (units === "imperial" ? M_PER_MILE : 1000) / mps;
      return `${paceStr(per)} ${units === "imperial" ? "/mi" : "/km"}`;
    }
    return units === "imperial"
      ? `${(mps * 3600 / M_PER_MILE).toFixed(1)} mph`
      : `${(mps * 3.6).toFixed(1)} km/h`;
  }
  function fmtElev(m) {
    if (m == null) return "–";
    return units === "imperial" ? `${Math.round(m * 3.28084)} ft` : `${Math.round(m)} m`;
  }
  function fmtDist(m, sport) {
    if (m == null) return "–";
    if (sport === "swim")
      return units === "imperial" ? `${Math.round(m / M_PER_YD)} yd` : `${Math.round(m)} m`;
    return units === "imperial"
      ? `${(m / M_PER_MILE).toFixed(2)} mi` : `${(m / 1000).toFixed(2)} km`;
  }

  return { theme, applyDefaults, units, fmtDuration, fmtHours, fmtSpeedOrPace, fmtElev, fmtDist, paceStr };
})();
AB.applyDefaults();
