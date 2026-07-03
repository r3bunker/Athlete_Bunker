/* Dashboard charts: PMC, weekly load by sport, time in HR zones. */
(function () {
  const t = AB.theme();
  let pmcChart, weeklyChart, zonesChart;
  let weeklyData = null;

  // ---------------- PMC (all series share the TSS-point unit) ----------
  async function loadPMC(days) {
    const data = await (await fetch(`/api/pmc?days=${days}`)).json();
    const labels = data.map((d) => d.date);
    const ds = [
      {
        label: "Fitness (CTL)", data: data.map((d) => d.ctl),
        borderColor: t.pmc.ctl, backgroundColor: t.pmc.ctl + "22",
        fill: true, borderWidth: 2, pointRadius: 0, tension: 0.3, order: 2,
      },
      {
        label: "Fatigue (ATL)", data: data.map((d) => d.atl),
        borderColor: t.pmc.atl, borderWidth: 2, pointRadius: 0, tension: 0.3, order: 1,
      },
      {
        label: "Form (TSB)", data: data.map((d) => d.tsb),
        borderColor: t.pmc.tsb, borderWidth: 2, pointRadius: 0,
        borderDash: [5, 3], tension: 0.3, order: 0,
      },
      {
        label: "Daily TSS", data: data.map((d) => d.tss || null),
        type: "scatter", pointRadius: 2.5, pointHoverRadius: 5,
        pointBackgroundColor: t.muted, pointBorderColor: t.surface,
        pointBorderWidth: 1, showLine: false, order: 3,
      },
    ];
    if (pmcChart) pmcChart.destroy();
    pmcChart = new Chart(document.getElementById("pmc-chart"), {
      type: "line",
      data: { labels, datasets: ds },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 10, callback: function (v) {
              const d = new Date(this.getLabelForValue(v) + "T00:00:00");
              return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
            } },
          },
          y: { title: { display: true, text: "TSS points" }, grid: { color: t.grid } },
        },
        plugins: {
          legend: { position: "top", align: "end" },
          tooltip: { callbacks: { title: (items) => items[0].label } },
        },
      },
    });
  }

  document.querySelectorAll("#pmc-range button").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("#pmc-range button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      loadPMC(btn.dataset.days);
    }));

  // ---------------- weekly stacked bars ------------------------------
  const SPORTS = ["swim", "bike", "run", "other"];
  const SPORT_LABEL = { swim: "Swim", bike: "Bike", run: "Run", other: "Other" };

  function weeklyValue(entry, sport, mode) {
    const s = entry.sports[sport] || {};
    if (mode === "hours") return (s.secs || 0) / 3600;
    if (mode === "dist") return (s.dist || 0) / (AB.units === "imperial" ? 1609.344 : 1000);
    return s.tss || 0;
  }

  function renderWeekly(mode) {
    const axisTitle = mode === "hours" ? "Hours"
      : mode === "dist" ? (AB.units === "imperial" ? "Miles" : "Kilometers") : "TSS";
    const labels = weeklyData.map((w) => {
      const d = new Date(w.week + "T00:00:00");
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    });
    const datasets = SPORTS.map((sport) => ({
      label: SPORT_LABEL[sport],
      data: weeklyData.map((w) => weeklyValue(w, sport, mode)),
      backgroundColor: t.sports[sport],
      borderColor: t.surface, borderWidth: 1, // 2px visual gap between segments
      borderRadius: 3, borderSkipped: false,
      stack: "week",
    })).filter((ds) => ds.data.some((v) => v > 0));
    if (weeklyChart) weeklyChart.destroy();
    weeklyChart = new Chart(document.getElementById("weekly-chart"), {
      type: "bar",
      data: { labels, datasets },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: { stacked: true, title: { display: true, text: axisTitle }, grid: { color: t.grid } },
        },
        plugins: {
          legend: { position: "top", align: "end" },
          tooltip: { callbacks: {
            label: (item) => {
              const v = item.raw;
              if (mode === "hours") return `${item.dataset.label}: ${v.toFixed(1)} h`;
              if (mode === "dist") return `${item.dataset.label}: ${v.toFixed(1)} ${AB.units === "imperial" ? "mi" : "km"}`;
              return `${item.dataset.label}: ${Math.round(v)} TSS`;
            },
          } },
        },
      },
    });
  }

  document.querySelectorAll("#weekly-mode button").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("#weekly-mode button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderWeekly(btn.dataset.mode);
    }));

  // ---------------- HR zone distribution ------------------------------
  async function loadZones() {
    const data = await (await fetch("/api/zones?days=28")).json();
    const all = data.all || [0, 0, 0, 0, 0, 0];
    const labels = ["Z1 Recovery", "Z2 Endurance", "Z3 Tempo", "Z4 Threshold", "Z5 VO2max", "Z6 Anaerobic"];
    if (zonesChart) zonesChart.destroy();
    zonesChart = new Chart(document.getElementById("zones-chart"), {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: all.map((s) => s / 3600),
          backgroundColor: t.zones,
          borderRadius: 3, borderSkipped: false,
        }],
      },
      options: {
        indexAxis: "y",
        maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: "Hours" }, grid: { color: t.grid } },
          y: { grid: { display: false }, ticks: { color: t.text2 } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (i) => `${AB.fmtDuration(i.raw * 3600)} (h:mm:ss)` } },
        },
      },
    });
  }

  loadPMC(90);
  fetch("/api/weekly?weeks=12").then((r) => r.json()).then((d) => {
    weeklyData = d;
    renderWeekly("tss");
  });
  loadZones();
})();
