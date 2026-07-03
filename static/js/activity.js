/* Activity detail: stacked stream charts (one measure per chart, one axis
 * each) with a shared crosshair, plus the route map. */
(function () {
  const container = document.getElementById("stream-charts");
  const mapEl = document.getElementById("map");
  if (!container && !mapEl) return;

  const activityId = container
    ? container.dataset.activity
    : location.pathname.split("/").pop();

  fetch(`/api/activity/${activityId}/streams`)
    .then((r) => (r.ok ? r.json() : null))
    .then((streams) => {
      if (!streams || !streams.t) return;
      if (container) buildCharts(streams);
      if (mapEl) buildMap(streams);
    });

  function smooth(values, window) {
    if (!values) return null;
    const out = new Array(values.length);
    let acc = 0, n = 0;
    const q = [];
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      q.push(v);
      if (v != null) { acc += v; n++; }
      if (q.length > window) {
        const old = q.shift();
        if (old != null) { acc -= old; n--; }
      }
      out[i] = n ? acc / n : null;
    }
    return out;
  }

  function buildCharts(streams) {
    const t = AB.theme();
    const sport = container.dataset.sport;
    const time = streams.t;
    const charts = [];
    const shared = { x: null };

    const crosshair = {
      id: "crosshair",
      afterDraw(chart) {
        if (shared.x == null) return;
        const x = chart.scales.x.getPixelForValue(shared.x);
        if (x < chart.chartArea.left || x > chart.chartArea.right) return;
        const ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = t.baseline;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, chart.chartArea.top);
        ctx.lineTo(x, chart.chartArea.bottom);
        ctx.stroke();
        ctx.restore();
      },
    };

    function addChart(label, values, color, opts = {}) {
      if (!values || !values.some((v) => v != null && v !== 0)) return;
      const div = document.createElement("div");
      div.className = "stream-chart";
      const canvas = document.createElement("canvas");
      div.appendChild(canvas);
      container.appendChild(div);
      const chart = new Chart(canvas, {
        type: "line",
        data: {
          labels: time,
          datasets: [{
            label,
            data: values,
            borderColor: color,
            backgroundColor: color + (opts.fill ? "33" : "00"),
            fill: !!opts.fill,
            borderWidth: 1.5,
            pointRadius: 0,
            spanGaps: true,
            tension: 0.2,
          }],
        },
        options: {
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          scales: {
            x: {
              type: "linear",
              min: time[0], max: time[time.length - 1],
              grid: { display: false },
              ticks: {
                maxTicksLimit: 12,
                callback: (v) => AB.fmtDuration(v),
                display: opts.lastRow,
              },
            },
            y: {
              title: { display: true, text: label },
              grid: { color: t.grid },
              ticks: { maxTicksLimit: 4, callback: opts.tickFmt },
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: (items) => AB.fmtDuration(items[0].parsed.x),
                label: (item) => `${label}: ${opts.valueFmt ? opts.valueFmt(item.parsed.y) : Math.round(item.parsed.y)}`,
              },
            },
          },
        },
        plugins: [crosshair],
      });
      canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        const xVal = chart.scales.x.getValueForPixel(e.clientX - rect.left);
        shared.x = xVal;
        charts.forEach((c) => c.draw());
      });
      canvas.addEventListener("mouseleave", () => {
        shared.x = null;
        charts.forEach((c) => c.draw());
      });
      charts.push(chart);
    }

    const paceFmt = (v) => AB.fmtSpeedOrPace(v, sport);
    const isPaceSport = sport === "run" || sport === "swim";

    if (streams.speed)
      addChart(isPaceSport ? "Pace" : "Speed", smooth(streams.speed, 10),
               t.sports[sport] || t.sports.other,
               { tickFmt: (v) => paceFmt(v), valueFmt: paceFmt });
    if (streams.power)
      addChart("Power (W)", smooth(streams.power, 5), t.pmc.ctl);
    if (streams.hr)
      addChart("Heart rate (bpm)", streams.hr, t.pmc.atl);
    if (streams.cad)
      addChart(sport === "run" ? "Cadence (spm)" : "Cadence (rpm)",
               smooth(streams.cad, 10), t.sports.other);
    if (streams.alt)
      addChart("Elevation", streams.alt, t.muted,
               { fill: true, lastRow: true,
                 tickFmt: (v) => AB.fmtElev(v), valueFmt: (v) => AB.fmtElev(v) });

    // make sure the bottom chart shows the time axis even if altitude missing
    if (charts.length) {
      const last = charts[charts.length - 1];
      last.options.scales.x.ticks.display = true;
      last.canvas.parentElement.style.height = "140px";
      last.update();
    }
  }

  function buildMap(streams) {
    if (!streams.lat || !streams.lng || typeof L === "undefined") {
      mapEl.style.display = "none";
      return;
    }
    const points = [];
    for (let i = 0; i < streams.lat.length; i++) {
      if (streams.lat[i] != null && streams.lng[i] != null)
        points.push([streams.lat[i], streams.lng[i]]);
    }
    if (points.length < 2) { mapEl.style.display = "none"; return; }
    const map = L.map("map", { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    const line = L.polyline(points, { color: "#2a78d6", weight: 3 }).addTo(map);
    L.circleMarker(points[0], { radius: 5, color: "#0ca30c", fillOpacity: 1 }).addTo(map);
    L.circleMarker(points[points.length - 1], { radius: 5, color: "#d03b3b", fillOpacity: 1 }).addTo(map);
    map.fitBounds(line.getBounds(), { padding: [16, 16] });
  }
})();
