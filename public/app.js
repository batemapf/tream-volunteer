let days = [
  ["2026-12-02", "Wednesday, Dec 2"],
  ["2026-12-03", "Thursday, Dec 3"],
  ["2026-12-04", "Friday, Dec 4"],
  ["2026-12-05", "Saturday, Dec 5"],
  ["2026-12-06", "Sunday, Dec 6"],
];
// Local demo only; the deployed board receives configurable choices from the API.
const demoTasks = [
  { id: "sales", label: "Sales" },
  { id: "cashier", label: "Cashiering" },
  { id: "greenery", label: "Greenery Management" },
  { id: "lot-maintenance", label: "Lot Maintenance/Inventory Replenishment" },
  { id: "tree-prep", label: "Tree Prep (Chainsaw/Baling/Loading)" },
];
let jobs = [
  ["2026-12-02", "Lot setup & prep", "Setup", 10, 15, 15, true],
  ["2026-12-02", "Tree unloading", "Lifting", 16, 18, 75, true],
  ["2026-12-03", "Pre-opening setup", "Setup", 10, 15, 15, true],
  ["2026-12-03", "Lot sales", "Sales", 15, 19, 30, true],
  ["2026-12-04", "Pre-opening setup", "Setup", 10, 15, 10, true],
  ["2026-12-04", "Lot sales · afternoon", "Sales", 12, 15.5, 30, true],
  ["2026-12-04", "Lot sales · evening", "Sales", 15.5, 19, 30, true],
  ["2026-12-04", "Donate-a-tree delivery", "Delivery", 12, 16, 4, false],
  ["2026-12-05", "Lot sales · morning", "Sales", 9, 13, 30, true],
  ["2026-12-05", "Lot sales · afternoon", "Sales", 13, 17, 20, true],
  ["2026-12-05", "Morning delivery crew", "Delivery", 8, 12.5, 10, false],
  ["2026-12-05", "Afternoon delivery crew", "Delivery", 12.5, 17, 10, false],
  ["2026-12-06", "Lot sales · morning", "Sales", 9, 13, 15, true],
  ["2026-12-06", "Lot sales · afternoon", "Sales", 13, 17, 15, true],
  ["2026-12-06", "Morning delivery crew", "Delivery", 8.5, 12.5, 6, false],
  ["2026-12-06", "Afternoon delivery crew", "Delivery", 12.5, 17, 6, false],
  ["2026-12-06", "Take down & cleanup", "Setup", 15, 18, 15, true],
].map((a, id) => ({
  id,
  date: a[0],
  name: a[1],
  role: a[2],
  subJobs: a[2] === "Sales" ? demoTasks : [],
  start: a[3],
  end: a[4],
  capacity: a[5],
  flex: a[6],
}));
const $ = (s) => document.querySelector(s),
  modal = $("#modal");
const fmt = (t) => {
  const h = Math.floor(t) % 24;
  return `${h % 12 || 12}:${String(Math.round(t * 60) % 60).padStart(2, "0")} ${h >= 12 ? "pm" : "am"}`;
};
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const names = [
  "Alex M.",
  "Priya S.",
  "Chris W.",
  "Jordan L.",
  "Sam R.",
  "Taylor B.",
  "Morgan K.",
  "Casey T.",
  "Jamie H.",
  "Riley D.",
  "Drew P.",
  "Robin C.",
  "Lee A.",
  "Pat F.",
  "Avery J.",
  "Cameron N.",
  "Jules V.",
  "Reese G.",
  "Devon E.",
  "Skyler O.",
  "Quinn Z.",
  "Rowan I.",
  "Charlie U.",
  "Blair Y.",
  "Emery Q.",
  "Finley X.",
  "Sage M.",
  "Harper S.",
  "Parker W.",
  "Shawn L.",
];
const seedCounts = [8, 36, 15, 21, 3, 19, 9, 0, 18, 4, 7, 0, 5, 0, 6, 2, 1];
let seed = jobs.flatMap((j) =>
  Array.from({ length: seedCounts[j.id] }, (_, i) => ({
    job: j.id,
    start: j.start,
    end: j.flex && i % 4 === 0 ? Math.min(j.start + 2, j.end) : j.end,
    publicName:
      i % 6 === 5
        ? "Volunteer (name private)"
        : names[(i + j.id * 3) % names.length],
  })),
);
const apiBase = window.TREAM_CONFIG?.apiBase;
// Commitments live on the server and in email, never in a browser signup list.
try {
  localStorage.removeItem("tream-aws-manage");
  localStorage.removeItem("tream-board-demo");
} catch {}
async function api(path, options = {}) {
  const response = await fetch(apiBase + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Please try again.");
  return data;
}
async function loadSchedule() {
  if (!apiBase) return;
  $("#rows").setAttribute("aria-busy", "true");
  try {
    const data = await api("/schedule");
    jobs = data.shifts;
    days = [...new Set(jobs.map((j) => j.date))].sort().map((d) => [
      d,
      new Date(d + "T12:00:00").toLocaleDateString("en-US", {
        weekday: "long",
        month: "short",
        day: "numeric",
      }),
    ]);
    const roles = [...new Set(jobs.map((j) => j.role))].sort();
    if (!roles.includes(role)) role = "all";
    $("#jobfilter").innerHTML =
      '<option value="all">All jobs</option>' +
      roles.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`).join("");
    $("#jobfilter").value = role;
    if (day !== "all" && !days.some(([d]) => d === day)) day = "all";
    seed = jobs.flatMap((j) => j.roster.map((p) => ({ ...p, job: j.id })));
    render();
  } finally {
    $("#rows").setAttribute("aria-busy", "false");
  }
}
function secureToken() {
  const b = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...b))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
let entries = []; // In-memory sample mode only; reset on page reload.
let day = "all",
  role = "all",
  onlyNeed = false;
function people(id) {
  return [
    ...seed.filter((p) => p.job === id),
    ...(apiBase ? [] : entries.filter((p) => p.job === id)),
  ];
}
function present(j, t) {
  return people(j.id).filter((p) => p.start <= t && p.end > t).length;
}
function stats(j) {
  const roster = people(j.id);
  const points = [
    j.start,
    ...roster
      .flatMap((p) => [p.start, p.end])
      .filter((t) => t >= j.start && t < j.end),
  ];
  const counts = points.map((t) => present(j, t));
  return {
    min: Math.min(...counts),
    max: Math.max(...counts),
    total: roster.length,
  };
}
function free(j, s, e, skip = null) {
  const roster = people(j.id).filter((p) => p.id !== skip);
  const points = [
    s,
    ...roster.flatMap((p) => [p.start, p.end]).filter((t) => t >= s && t < e),
  ];
  return points.every(
    (t) =>
      roster.filter((p) => p.start <= t && p.end > t).length <
      (j.effectiveCapacity ?? j.capacity),
  );
}
function save() {
  render();
}
function toast(t) {
  $("#toast").textContent = t;
  $("#toast").style.display = "block";
  setTimeout(() => ($("#toast").style.display = "none"), 3000);
}
function render() {
  const shown = jobs.filter(
    (j) =>
      (day === "all" || day === j.date) &&
      (role === "all" || role === j.role) &&
      (!onlyNeed || stats(j).min < j.capacity),
  );
  $("#days").innerHTML = [
    ["all", "All days"],
    ...days.map(([d, l]) => [
      d,
      l.split(",")[0].slice(0, 3) + " " + d.slice(-2),
    ]),
  ]
    .map(
      ([d, l]) =>
        `<button data-day="${d}" class="${day === d ? "active" : ""}" aria-pressed="${day === d}">${l}</button>`,
    )
    .join("");
  $("#rows").innerHTML =
    shown
      .map((j, index) => {
        const groupHeading =
          index === 0 || shown[index - 1].date !== j.date
            ? `<tr class="day-divider"><th colspan="6" scope="rowgroup">${esc(days.find(([d]) => d === j.date)[1])}<span>${shown.filter((other) => other.date === j.date).length} shifts</span></th></tr>`
            : "";
        const s = stats(j),
          label = `${s.total}`,
          status =
            s.total >= j.capacity
              ? "Target reached"
              : s.total === 0
                ? ""
                : `${j.capacity - s.total} more to reach target`;
        return `${groupHeading}<tr class="shift-row"><td class="number">${jobs.indexOf(j) + 1}</td><td class="day">${days.find((x) => x[0] === j.date)[1].split(",")[0]}<small>${new Date(j.date + "T12:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric" })}</small></td><td class="job"><button class="job-title" data-open="${j.id}">${esc(j.name)}</button><small>${j.flex ? "Partial shifts welcome" : "Full crew window required"}</small></td><td class="time">${fmt(j.start)}–${fmt(j.end)}</td><td class="coverage ${s.total >= j.capacity ? "covered" : ""}"><strong><span class="mobile-label">Signed up </span>${label} / ${j.capacity}</strong><div class="track"><span style="width:${Math.min(100, (s.total / j.capacity) * 100)}%"></span></div><small>${status}</small></td><td><button class="join" data-open="${j.id}">${s.min >= j.capacity ? "View shift" : "View & join →"}</button></td></tr>`;
      })
      .join("") ||
    '<tr><td colspan="6" style="text-align:center;padding:40px">No shifts match these filters.</td></tr>';
  document.querySelectorAll("[data-day]").forEach(
    (b) =>
      (b.onclick = () => {
        day = b.dataset.day;
        render();
      }),
  );
  document
    .querySelectorAll("[data-open]")
    .forEach((b) => (b.onclick = () => openShift(b.dataset.open)));
}
function candidateTimes(j, kind) {
  const values = [];
  for (
    let t = j.start;
    t <= j.end + 0.00001;
    t += (j.attendance?.incrementMinutes ?? 30) / 60
  )
    values.push(Math.round(t * 60) / 60);
  if (!values.includes(j.end)) values.push(j.end);
  const allowed =
    j.attendance?.[kind === "start" ? "allowedStarts" : "allowedEnds"];
  return values.filter(
    (t) =>
      (!allowed ||
        allowed.some((a) => Math.round(a * 60) === Math.round(t * 60))) &&
      (kind === "start" ? t < j.end : t > j.start),
  );
}
function validEnds(j, start) {
  return candidateTimes(j, "end").filter(
    (end) =>
      end > start &&
      (end - start) * 60 >= (j.attendance?.minMinutes ?? 30) - 0.00001 &&
      (end - start) * 60 <= (j.attendance?.maxMinutes ?? 1440) + 0.00001,
  );
}
function options(j, val, kind = "end") {
  let values = candidateTimes(j, kind);
  if (!j.flex) values = [kind === "start" ? j.start : j.end];
  if (kind === "start" && j.flex)
    values = values.filter((start) => validEnds(j, start).length);
  if (!values.includes(val)) val = kind === "start" ? values[0] : values.at(-1);
  return values
    .map(
      (t) =>
        `<option value="${t}" ${t === val ? "selected" : ""}>${fmt(t)}</option>`,
    )
    .join("");
}

function closeWire() {
  modal.querySelector(".close").onclick = () => modal.close();
}
function publicLabel(name) {
  const parts = name.trim().split(/\s+/);
  return (
    parts[0] +
    (parts.length > 1
      ? " " + parts[parts.length - 1][0].toUpperCase() + "."
      : "")
  );
}
function taskChoices(j) {
  const options = (j.subJobs || []).filter(
    (option) => option.enabled !== false,
  );
  if (!options.length) return "";
  return `<fieldset class="task-options"><legend>What would you like to help with? <span>(optional)</span></legend><p class="sub">Choose any that interest you. The team will assign tasks on the day.</p>${options.map((option) => `<label class="check task-choice"><input type="checkbox" data-task value="${esc(option.id)}"><span>${esc(option.label)}${option.description ? `<small>${esc(option.description)}</small>` : ""}</span></label>`).join("")}</fieldset>`;
}
function openShift(id) {
  const j = jobs.find((x) => String(x.id) === String(id));
  id = j.id;
  let pending = null;
  const roster = people(id),
    s = stats(j);
  modal.innerHTML = `<button class="close" aria-label="Close">×</button><p class="eyebrow">${days.find((x) => x[0] === j.date)[1]} · ${esc(j.location || "Canal Park")}</p><h2>${esc(j.name)}</h2><p class="sub">${fmt(j.start)}–${fmt(j.end)} · ${j.flex ? "Choose all or part of the shift." : "This job needs the entire shift."}</p>${roster.length ? `<div class="roster">${roster.map((p) => `<div class="person"><span>${esc(p.publicName)}</span><span>${fmt(p.start)}–${fmt(p.end)}</span></div>`).join("")}</div>` : ""}${j.open === false || s.min >= (j.effectiveCapacity ?? j.capacity) ? '<div class="summary">This shift is not accepting signups in this window. Try another shift.</div>' : `<form id="signup"><div class="times"><div><label for="start">Arrive</label><select id="start" ${j.flex ? "" : "disabled"}>${options(j, j.start, "start")}</select></div><div><label for="end">Leave</label><select id="end" ${j.flex ? "" : "disabled"}>${options(j, j.end)}</select></div></div>${taskChoices(j)}<label for="name">Volunteer name</label><input id="name" placeholder="Full name" maxlength="70" required autocomplete="off"><label for="email">Email</label><input id="email" type="email" placeholder="parent@example.com" required autocomplete="off"><label for="phone">Phone number</label><input id="phone" type="tel" autocomplete="tel" inputmode="tel" maxlength="40" required><label class="check consent"><input id="share" type="checkbox"><span>Keep my name private on the board.</span></label><p class="error" id="error" role="alert"></p><button class="primary full">Sign up</button></form>`}`;
  modal.showModal();
  closeWire();
  if (j.open === false || s.min >= (j.effectiveCapacity ?? j.capacity)) return;
  if (j.flex) {
    const updateEnds = () => {
      const preferred = Number($("#end").value),
        values = validEnds(j, Number($("#start").value));
      const chosen = values.includes(preferred) ? preferred : values.at(-1);
      $("#end").innerHTML = values
        .map(
          (t) =>
            `<option value="${t}" ${t === chosen ? "selected" : ""}>${fmt(t)}</option>`,
        )
        .join("");
    };
    $("#start").onchange = updateEnds;
    updateEnds();
  }
  $("#signup").onsubmit = async (e) => {
    e.preventDefault();
    const start = +$("#start").value,
      end = +$("#end").value;
    if (start >= end || start < j.start || end > j.end) {
      $("#error").textContent =
        "Choose a departure later than your arrival, within this shift.";
      return;
    }
    if (!apiBase && !free(j, start, end)) {
      $("#error").textContent =
        "Part of that window is full. Try different hours or another shift.";
      return;
    }
    const name = $("#name").value.trim();
    if (!name) {
      $("#error").textContent = "Please enter a name.";
      return;
    }
    const selectedTasks = [
      ...modal.querySelectorAll("[data-task]:checked"),
    ].map((input) => input.value);
    const preferences = selectedTasks.map((id) => {
      const option = j.subJobs.find((option) => option.id === id);
      return { id: option.id, label: option.label };
    });
    const email = $("#email").value.trim();
    const entry = {
      id: Date.now(),
      job: id,
      subJobPreferences: preferences,
      start,
      end,
      publicName: !$("#share").checked
        ? publicLabel(name)
        : "Volunteer (name private)",
    };
    if (apiBase) {
      const selection = {
        shiftId: String(id),
        start,
        end,
        name,
        phone: $("#phone").value.trim(),
        shareName: !$("#share").checked,
        subJobs: selectedTasks,
      };
      const fingerprint = JSON.stringify([$("#email").value, selection]);
      if (!pending || pending.fingerprint !== fingerprint)
        pending = {
          fingerprint,
          idempotencyKey: crypto.randomUUID(),
          participantId: crypto.randomUUID(),
          manageToken: secureToken(),
        };
      const button = $("#signup button[type=submit]") || $("#signup .primary");
      button.disabled = true;
      try {
        const result = await api("/bookings", {
          method: "POST",
          body: JSON.stringify({
            email: $("#email").value,
            selections: [
              {
                ...selection,
                idempotencyKey: pending.idempotencyKey,
                participantId: pending.participantId,
                manageToken: pending.manageToken,
              },
            ],
          }),
        });
        const outcome = result.results[0];
        if (outcome.status !== "booked")
          throw new Error(
            outcome.message || "This selection could not be booked.",
          );
        entry.id = outcome.bookingId;
        entry.subJobPreferences = outcome.subJobPreferences || preferences;
        entry.token = pending.manageToken;
        await loadSchedule();
      } catch (error) {
        $("#error").textContent = error.message;
        button.disabled = false;
        return;
      }
    } else {
      entries.push(entry);
      save();
    }
    modal.innerHTML = `<button class="close" aria-label="Close">×</button><div class="success">✓</div><h2>You’re on the Tream.</h2><div class="summary"><strong>${esc(j.name)}</strong><br>${days.find((x) => x[0] === j.date)[1]}<br>${fmt(start)}–${fmt(end)} · ${esc(j.location || "Canal Park")}</div><p class="sub">On the board: ${esc(entry.publicName)}.<br>Your commitment ends at ${fmt(end)}.</p>${apiBase ? `<p class="sub">Confirmation email: ${esc(email)}</p><p><a class="primary" href="manage.html#${new URLSearchParams({ booking: entry.id, token: entry.token })}">View / change / cancel this signup</a></p>` : ""}${entry.subJobPreferences?.length ? `<p class="sub">Task preferences: ${entry.subJobPreferences.map((option) => esc(option.label)).join(", ")}</p>` : ""}<button class="primary full" id="done">Back to the board</button>`;
    closeWire();
    $("#done").onclick = () => modal.close();
  };
}
function findSignups() {
  modal.innerHTML = `<button class="close" aria-label="Close">×</button><h2>Find my signups</h2><p class="sub">Enter the email address used to sign up. We’ll email links for your active commitments.</p><form id="find-signups"><label for="recovery-email">Email</label><input id="recovery-email" type="email" autocomplete="email" required><p id="recovery-error" class="error" role="alert"></p><button class="primary full">Email my signup links</button></form><p class="sub">Need help with a mistyped address? <a href="mailto:batemapf@gmail.com">Contact the organizer</a>.</p>`;
  if (!modal.open) modal.showModal();
  closeWire();
  $("#find-signups").onsubmit = async (event) => {
    event.preventDefault();
    const button = $("#find-signups button");
    button.disabled = true;
    try {
      if (apiBase)
        await api("/recovery", {
          method: "POST",
          body: JSON.stringify({ email: $("#recovery-email").value.trim() }),
        });
      modal.innerHTML =
        '<button class="close" aria-label="Close">×</button><h2>Check your email</h2><p>If that address has active signups, you’ll receive their links by email.</p><p class="sub">Check your spam folder if needed. For help, <a href="mailto:batemapf@gmail.com">contact the organizer</a>.</p><button id="recovery-done">Back to the board</button>';
      closeWire();
      $("#recovery-done").onclick = () => modal.close();
    } catch (error) {
      $("#recovery-error").textContent = error.message;
      button.disabled = false;
    }
  };
}
$("#jobfilter").onchange = (e) => {
  role = e.target.value;
  render();
};
$("#need").onchange = (e) => {
  onlyNeed = e.target.checked;
  render();
};
$("#mine").onclick = findSignups;
render();

if (apiBase) {
  jobs = [];
  seed = [];
  render();
  $("#rows").innerHTML =
    '<tr><td colspan="6"><div class="schedule-loading" role="status"><span class="loading-spinner" aria-hidden="true"></span>Loading schedule…</div></td></tr>';
  loadSchedule().catch(() => {
    $("#rows").innerHTML =
      '<tr><td colspan="6">Unable to load the board. Refresh to try again.</td></tr>';
  });
}
