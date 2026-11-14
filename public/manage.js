const $ = (q) => document.querySelector(q),
  esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    ),
  params = new URLSearchParams(location.hash.slice(1)),
  bookingId = params.get("booking"),
  token = params.get("token"),
  apiBase = window.TREAM_CONFIG?.apiBase;
let booking, shifts;
async function api(path, body) {
  const response = await fetch(apiBase + path, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.message || "Please try again.");
  return data;
}
const fmt = (n) =>
  `${Math.floor(n) % 12 || 12}:${String(Math.round((n % 1) * 60)).padStart(2, "0")} ${n < 12 ? "am" : "pm"}`;
function render() {
  const shift = shifts.find((s) => s.id === booking.shiftId);
  if (!shift)
    throw Error(
      "This shift is no longer available. Please contact the organizer.",
    );
  $("#management").innerHTML =
    `<div class="summary"><strong>${esc(booking.name)}</strong><p>${esc(shift.name)}<br>${esc(shift.date)} · ${fmt(booking.start)}–${fmt(booking.end)} Eastern<br>${esc(shift.location)}</p><p>${booking.status === "active" ? "Confirmed" : "Canceled"}</p></div>${booking.status === "active" ? '<p><button id="change">Change signup</button> <button id="cancel">Cancel signup</button></p><p><button id="resend">Resend confirmation email</button></p>' : "<p>Your place has reopened. You can choose a new shift on the board.</p>"}`;
  if (booking.status !== "active") return;
  $("#change").onclick = edit;
  $("#cancel").onclick = () => {
    $("#management").innerHTML =
      '<h2>Cancel this signup?</h2><p>Your place will reopen on the board.</p><button id="confirm">Yes, cancel</button> <button id="keep">Keep signup</button>';
    $("#keep").onclick = render;
    $("#confirm").onclick = async () => {
      $("#confirm").disabled = true;
      try {
        await api(`/bookings/${encodeURIComponent(bookingId)}/cancel`, {});
        await load();
      } catch (e) {
        fail(e);
        $("#confirm").disabled = false;
      }
    };
  };
  $("#resend").onclick = async () => {
    $("#resend").disabled = true;
    try {
      const result = await api(
        `/bookings/${encodeURIComponent(bookingId)}/resend`,
        {},
      );
      $("#manage-error").textContent = result.queued
        ? "Confirmation email queued."
        : "Email delivery is restricted to the test inbox.";
    } catch (e) {
      fail(e);
      $("#resend").disabled = false;
    }
  };
}
function edit() {
  $("#manage-error").textContent = "";
  const options = shifts.filter((s) => s.open || s.id === booking.shiftId);
  $("#management").innerHTML =
    `<form id="edit"><label for="shift">Shift</label><select id="shift">${options.map((s) => `<option value="${esc(s.id)}" ${s.id === booking.shiftId ? "selected" : ""}>${esc(s.date)} · ${esc(s.name)} · ${fmt(s.start)}–${fmt(s.end)}</option>`).join("")}</select><div class="times"><div><label for="start">Arrive</label><select id="start"></select></div><div><label for="end">Leave</label><select id="end"></select></div></div><div id="tasks"></div><p><button class="primary" id="save">Save changes</button> <button type="button" id="back">Keep current signup</button></p></form>`;
  const populate = () => {
    const s = shifts.find((s) => s.id === $("#shift").value),
      step = (s.attendance?.incrementMinutes ?? 30) / 60;
    const values = [];
    for (let t = s.start; t <= s.end + 0.001; t += step)
      values.push(Math.round(t * 60) / 60);
    if (!values.includes(s.end)) values.push(s.end);
    const option = (v, chosen) =>
      `<option value="${v}" ${v === chosen ? "selected" : ""}>${fmt(v)}</option>`;
    const original = s.id === booking.shiftId;
    $("#start").innerHTML = (s.flex ? values.slice(0, -1) : [s.start])
      .map((v) => option(v, original ? booking.start : s.start))
      .join("");
    const ends = () => {
      const previous = Number($("#end").value),
        min = (s.attendance?.minMinutes ?? 30) / 60;
      const valid = s.flex
        ? values.filter((v) => v - Number($("#start").value) >= min - 0.001)
        : [s.end];
      const chosen = valid.includes(previous)
        ? previous
        : original && valid.includes(booking.end)
          ? booking.end
          : valid.at(-1);
      $("#end").innerHTML = valid.map((v) => option(v, chosen)).join("");
    };
    $("#start").onchange = ends;
    ends();
    $("#tasks").innerHTML = s.subJobs?.length
      ? `<p>Task preferences (optional)</p>${s.subJobs.map((t) => `<label class="check"><input type="checkbox" data-task value="${esc(t.id)}" ${original && booking.subJobPreferences?.some((p) => p.id === t.id) ? "checked" : ""}>${esc(t.label)}</label>`).join("")}`
      : "";
  };
  $("#shift").onchange = populate;
  populate();
  $("#back").onclick = render;
  let submitted;
  $("#edit").onsubmit = async (e) => {
    e.preventDefault();
    $("#save").disabled = true;
    const payload = {
      revision: booking.revision,
      shiftId: $("#shift").value,
      start: Number($("#start").value),
      end: Number($("#end").value),
      subJobs: [...document.querySelectorAll("[data-task]:checked")].map(
        (t) => t.value,
      ),
    };
    const fingerprint = JSON.stringify(payload);
    if (!submitted || submitted.fingerprint !== fingerprint)
      submitted = { fingerprint, requestId: crypto.randomUUID() };
    try {
      await api(`/bookings/${encodeURIComponent(bookingId)}/change`, {
        ...payload,
        requestId: submitted.requestId,
      });
      await load();
    } catch (e) {
      fail(e);
      $("#save").disabled = false;
    }
  };
}
function fail(error) {
  $("#manage-error").textContent = error.message;
}
async function load() {
  if (!apiBase || !bookingId || !token)
    throw Error("Open the private management link in your confirmation email.");
  [booking, { shifts }] = await Promise.all([
    api(`/bookings/${encodeURIComponent(bookingId)}`),
    api("/schedule"),
  ]);
  $("#manage-error").textContent = "";
  render();
}
load().catch((e) => {
  $("#management").textContent = "";
  fail(e);
});
