(function () {
  const pages = document.querySelectorAll(".page");
  const navButtons = document.querySelectorAll(".nav button[data-page]");

  function show(id) {
    pages.forEach((page) => page.classList.toggle("active", page.id === id));
    navButtons.forEach((button) => {
      const on = button.getAttribute("data-page") === id;
      button.setAttribute("aria-current", on ? "page" : "false");
    });
  }

  navButtons.forEach((button) => {
    button.addEventListener("click", () => show(button.getAttribute("data-page")));
  });

  document.querySelectorAll("[data-toggle-table]").forEach((button) => {
    button.addEventListener("click", () => {
      const table = document.getElementById(button.getAttribute("data-toggle-table"));
      if (!table) return;
      table.classList.toggle("open");
      button.textContent = table.classList.contains("open") ? "Hide table" : "Show table";
    });
  });

  function load(name) {
    return fetch("data/" + name).then((response) => {
      if (!response.ok) throw new Error(name);
      return response.json();
    });
  }

  const plotConfig = { displaylogo: false, responsive: true };

  function drawCurves(payload) {
    const node = document.getElementById("equity-chart");
    if (!node || !window.Plotly || !payload || !payload.series) return;
    const traces = [];
    const tableRows = [];
    Object.keys(payload.series).forEach((key) => {
      const series = payload.series[key];
      traces.push({
        type: "scatter",
        mode: "lines",
        name: key,
        x: series.dates,
        y: series.wealth,
      });
      series.dates.forEach((date, i) => {
        tableRows.push([key, date, series.wealth[i]]);
      });
    });
    window.Plotly.newPlot(node, traces, {
      title: "Month-end wealth (rebased to 1)",
      paper_bgcolor: "#0b1528",
      plot_bgcolor: "#0b1528",
      font: { color: "#e7eef8" },
      xaxis: { title: "Date" },
      yaxis: { title: "Wealth (start = 1)" },
      legend: { orientation: "h" },
      margin: { t: 48 },
    }, plotConfig);
    const body = document.querySelector("#equity-table tbody");
    if (body) {
      body.replaceChildren();
      tableRows.forEach((row) => {
        const tr = document.createElement("tr");
        row.forEach((cell) => {
          const td = document.createElement("td");
          td.textContent = String(cell);
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }
  }

  function drawReliability(payload) {
    const node = document.getElementById("reliability-chart");
    if (!node || !window.Plotly || !payload || !payload.reliability) return;
    const bins = payload.reliability.bins.filter((row) => row.n);
    window.Plotly.newPlot(node, [
      {
        type: "scatter",
        mode: "markers",
        name: "Empirical rate",
        x: bins.map((row) => row.mean_predicted),
        y: bins.map((row) => row.empirical_rate),
        text: bins.map((row) => "n=" + row.n),
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Diagonal",
        x: [0, 1],
        y: [0, 1],
      },
    ], {
      title: "Reliability of the chosen-class probability",
      paper_bgcolor: "#0b1528",
      plot_bgcolor: "#0b1528",
      font: { color: "#e7eef8" },
      xaxis: { title: "Mean predicted probability", range: [0, 1] },
      yaxis: { title: "Share that were right", range: [0, 1] },
      margin: { t: 48 },
    }, plotConfig);
  }

  const filterButtons = document.querySelectorAll(".filters button");
  function applyFilter(cadence, lag) {
    document.querySelectorAll("#score-table tbody tr").forEach((row) => {
      const ok = row.getAttribute("data-cadence") === cadence && row.getAttribute("data-lag") === String(lag);
      row.hidden = !ok;
    });
    filterButtons.forEach((button) => {
      const on = button.getAttribute("data-cadence") === cadence && button.getAttribute("data-lag") === String(lag);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  filterButtons.forEach((button) => {
    button.addEventListener("click", () => applyFilter(button.getAttribute("data-cadence"), button.getAttribute("data-lag")));
  });
  applyFilter("daily", "1");

  const business = new Set();

  function etParts(date) {
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const bag = {};
    fmt.formatToParts(date).forEach((part) => { bag[part.type] = part.value; });
    return bag;
  }

  function isoFromParts(parts) {
    return parts.year + "-" + parts.month + "-" + parts.day;
  }

  function nextBusiness(iso) {
    const cursor = new Date(iso + "T12:00:00Z");
    for (let i = 0; i < 14; i += 1) {
      cursor.setUTCDate(cursor.getUTCDate() + 1);
      const day = cursor.toISOString().slice(0, 10);
      if (business.has(day)) return day;
    }
    return iso;
  }

  function postingOf(when) {
    const parts = etParts(when);
    const iso = isoFromParts(parts);
    const afterNoon = Number(parts.hour) > 12 || (Number(parts.hour) === 12 && (Number(parts.minute) > 0 || Number(parts.second) > 0));
    const atNoon = Number(parts.hour) === 12 && Number(parts.minute) === 0 && Number(parts.second) === 0;
    if (business.has(iso) && !afterNoon && !atNoon) return iso;
    return nextBusiness(iso);
  }

  function lastBusinessOfMonth(year, month) {
    const days = [];
    business.forEach((iso) => {
      if (iso.startsWith(year + "-" + month)) days.push(iso);
    });
    days.sort();
    return days.length ? days[days.length - 1] : null;
  }

  const IFT_KEY = "tsp-ift-log";

  function readLog() {
    try { return JSON.parse(localStorage.getItem(IFT_KEY) || "[]"); }
    catch (err) { return []; }
  }

  function writeLog(rows) {
    localStorage.setItem(IFT_KEY, JSON.stringify(rows));
  }

  function renderIft() {
    const count = document.getElementById("ift-count");
    if (!count) return;
    const now = new Date();
    const parts = etParts(now);
    const posted = postingOf(now);
    const month = posted.slice(0, 7);
    const account = (document.getElementById("ift-account") || {}).value || "civilian";
    const used = readLog().filter((row) => row.accepted && row.counted && row.account === account && row.month === month).length;
    const capped = Math.min(used, 2);
    count.textContent = capped + " of 2 unrestricted transfers used in " + month + " (" + account + ", by posting date).";
    const state = document.getElementById("ift-state");
    if (state) {
      state.textContent = used >= 2
        ? "Unrestricted transfers are used up. Further requests this month are accepted only when they do not decrease G and do not increase F, C, S, or I."
        : (2 - used) + " unrestricted transfer" + (used === 1 ? "" : "s") + " still available this month.";
    }
    document.querySelectorAll("#ift-meter .pip").forEach((pip) => {
      const which = pip.getAttribute("data-pip");
      if (which === "g") pip.classList.toggle("on", used >= 2);
      else pip.classList.toggle("used", Number(which) <= capped);
    });
    const cutoff = document.getElementById("cutoff");
    if (cutoff) {
      const noon = new Date(now);
      const hour = Number(parts.hour);
      cutoff.textContent = hour < 12
        ? "Before noon Eastern. A request on a TSP business day posts today (" + posted + ")."
        : "Noon Eastern has passed. A request now posts on " + posted + ".";
    }
    const trap = document.getElementById("trap");
    if (trap) {
      const last = lastBusinessOfMonth(parts.year, parts.month);
      const today = isoFromParts(parts);
      const after = Number(parts.hour) >= 12;
      if (last && today === last && after) {
        trap.textContent = "Month-end trap: a request now posts on " + posted + " and counts against that month, not " + month.slice(0, 7) + ".";
      } else {
        trap.textContent = last
          ? "Last TSP business day this month in the loaded calendar: " + last + "."
          : "Calendar not loaded yet.";
      }
    }
    const list = document.getElementById("ift-log");
    if (list) {
      list.replaceChildren();
      readLog().slice().reverse().forEach((row) => {
        const li = document.createElement("li");
        li.textContent = row.account + " " + row.requested + " posts " + row.posting + " " + row.target + " " + (row.accepted ? "accepted" : "rejected") + " (" + row.reason + ")";
        list.appendChild(li);
      });
    }
  }

  const iftForm = document.getElementById("ift-form");
  if (iftForm) {
    iftForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const whenValue = document.getElementById("ift-when").value;
      const when = whenValue ? new Date(whenValue) : new Date();
      const account = document.getElementById("ift-account").value;
      const target = document.getElementById("ift-fund").value;
      const posted = postingOf(when);
      const month = posted.slice(0, 7);
      const rows = readLog();
      const used = rows.filter((row) => row.accepted && row.counted && row.account === account && row.month === month).length;
      const current = rows.filter((row) => row.accepted && row.account === account).slice(-1)[0];
      const held = current ? current.target : "G";
      let accepted = true;
      let counted = used < 2;
      let reason = "posted";
      if (held === target) {
        accepted = false;
        counted = false;
        reason = "no allocation change";
      } else if (used >= 2 && target !== "G") {
        accepted = false;
        counted = false;
        reason = "after two unrestricted transfers, only a move into G is accepted by this log";
      } else if (!counted) {
        reason = "posted as a move into G after the monthly limit";
      }
      rows.push({
        account: account,
        requested: when.toISOString(),
        posting: posted,
        month: month,
        target: target,
        accepted: accepted,
        counted: accepted && counted,
        reason: reason,
      });
      writeLog(rows);
      renderIft();
    });
  }

  function renderReplay(history) {
    const slider = document.getElementById("replay");
    const readout = document.getElementById("replay-readout");
    const reveal = document.getElementById("reveal");
    const box = document.getElementById("reveal-box");
    if (!slider || !history || !history.replay) return;
    const replay = history.replay;
    slider.max = String(Math.max(replay.dates.length - 1, 0));
    slider.value = slider.max;
    function paint() {
      const i = Number(slider.value);
      const fund = replay.fund[i];
      const drivers = (replay.drivers[i] || []).map((item) => item.feature + " " + item.contribution + " (" + item.direction + ")").join("; ");
      readout.textContent = replay.dates[i] + ": " + fund + " at probability " + replay.probability[i] + (drivers ? ". Drivers: " + drivers : ".");
      if (box) box.hidden = true;
    }
    slider.addEventListener("input", paint);
    paint();
    if (reveal && box) {
      reveal.addEventListener("click", () => {
        const i = Number(slider.value);
        const item = replay.reveal[i] || {};
        box.hidden = false;
        box.textContent = "From the execution lag, C returned " + item.h21 + " over 21 sessions, " + item.h63 + " over 63, " + item.h126 + " over 126, and " + item.h252 + " over 252. The selected fund returned " + item.fund21 + " over 21 sessions. G returned " + item.g21 + " over 21 sessions. Empty values mean the window runs past the sample.";
      });
    }
  }

  const JOURNAL_KEY = "tsp-journal";

  function readJournal() {
    try { return JSON.parse(localStorage.getItem(JOURNAL_KEY) || "[]"); }
    catch (err) { return []; }
  }

  function paintJournal() {
    const node = document.getElementById("j-list");
    if (!node) return;
    const rows = readJournal();
    node.textContent = rows.length ? JSON.stringify(rows, null, 2) : "No journal entries in this browser.";
  }

  const journalForm = document.getElementById("journal-form");
  if (journalForm) {
    journalForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const rows = readJournal();
      rows.push({
        date: document.getElementById("j-date").value,
        fund: document.getElementById("j-fund").value,
        reason: document.getElementById("j-reason").value,
        confidence: Number(document.getElementById("j-conf").value),
      });
      localStorage.setItem(JOURNAL_KEY, JSON.stringify(rows));
      paintJournal();
    });
  }
  const exportButton = document.getElementById("j-export");
  if (exportButton) {
    exportButton.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(readJournal(), null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "tsp-journal.json";
      link.click();
    });
  }
  const importInput = document.getElementById("j-import");
  if (importInput) {
    importInput.addEventListener("change", () => {
      const file = importInput.files && importInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        const parsed = JSON.parse(String(reader.result));
        localStorage.setItem(JOURNAL_KEY, JSON.stringify(parsed));
        paintJournal();
      };
      reader.readAsText(file);
    });
  }
  paintJournal();

  function paintLocalPlan() {
    const balance = document.getElementById("balance");
    const retire = document.getElementById("retire");
    const note = document.getElementById("plan-note");
    if (balance && localStorage.getItem("tsp-balance")) balance.value = localStorage.getItem("tsp-balance");
    if (retire && localStorage.getItem("tsp-retire")) retire.value = localStorage.getItem("tsp-retire");
    function closest() {
      const year = Number(retire && retire.value);
      if (!year) return "L 2050";
      if (year <= 2028) return "L Income";
      const options = [2030, 2035, 2040, 2045, 2050, 2055, 2060, 2065, 2070, 2075];
      let best = options[0];
      options.forEach((option) => {
        if (Math.abs(option - year) < Math.abs(best - year)) best = option;
      });
      return "L " + best;
    }
    function refresh() {
      if (balance) localStorage.setItem("tsp-balance", balance.value);
      if (retire) localStorage.setItem("tsp-retire", retire.value);
      if (note) {
        note.textContent = "Retirement-year choice on this browser: " + closest() + ". The published scoreboard compares strategies with L 2050. Dollar figures use a hypothetical balance of " + (balance ? balance.value : "100000") + ".";
      }
    }
    if (balance) balance.addEventListener("change", refresh);
    if (retire) retire.addEventListener("change", refresh);
    refresh();
  }
  paintLocalPlan();

  load("alert.json").then((alert) => {
    const node = document.getElementById("alert");
    if (node && alert && alert.message) node.textContent = alert.message;
  }).catch(() => {});

  load("curves.json").then(drawCurves).catch(() => {});
  load("calibration.json").then(drawReliability).catch(() => {});
  load("calendar.json").then((calendar) => {
    (calendar.observed || []).forEach((day) => business.add(day));
    (calendar.projected || []).forEach((day) => business.add(day));
    renderIft();
    setInterval(renderIft, 30000);
  }).catch(() => { renderIft(); });
  load("history.json").then((history) => {
    renderReplay(history);
    const ribbon = document.getElementById("ribbon-chart");
    if (ribbon && window.Plotly && history.ribbon) {
      window.Plotly.newPlot(ribbon, [{
        type: "scatter",
        mode: "lines",
        name: "Regime (categorical codes are in the table)",
        x: history.ribbon.dates,
        y: history.ribbon.label.map((label) => label),
      }], {
        title: "Regime at month-end",
        paper_bgcolor: "#0b1528",
        plot_bgcolor: "#0b1528",
        font: { color: "#e7eef8" },
        xaxis: { title: "Date" },
        yaxis: { title: "Regime label" },
        margin: { t: 48 },
      }, plotConfig);
    }
  }).catch(() => {});

  const account = document.getElementById("ift-account");
  if (account) account.addEventListener("change", renderIft);
})();
