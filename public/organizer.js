(() => {
  "use strict";
  const $ = (s) => document.querySelector(s),
    root = $("#admin"),
    dialog = $("#dialog"),
    config = window.TREAM_CONFIG || {};
  const esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const fmt = (t) =>
    `${Math.floor(t) % 12 || 12}:${String(Math.round((t % 1) * 60)).padStart(2, "0")} ${t >= 12 ? "pm" : "am"}`;
  const dateLabel = (d) =>
    new Date(d + "T12:00:00").toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  const timeValue = (t) =>
    `${String(Math.floor(t)).padStart(2, "0")}:${String(Math.round((t % 1) * 60)).padStart(2, "0")}`;
  const hour = (s) => {
    const [h, m] = s.split(":").map(Number);
    return h + m / 60;
  };
  let token = "",
    username = "",
    challenge = null,
    data = null,
    view = "coverage",
    day = "",
    role = "",
    search = "",
    showReviewed = false,
    selected = new Set(),
    preview = null;
  try {
    token = sessionStorage.getItem("tream-organizer-access") || "";
  } catch {}
  function toast(message) {
    $("#toast").textContent = message;
    $("#toast").style.display = "block";
    setTimeout(() => ($("#toast").style.display = "none"), 4000);
  }
  function setToken(value) {
    token = value;
    try {
      if (value) sessionStorage.setItem("tream-organizer-access", value);
      else sessionStorage.removeItem("tream-organizer-access");
    } catch {}
  }
  function logout(message = "") {
    setToken("");
    data = null;
    selected.clear();
    challenge = null;
    preview = null;
    dialog.close();
    dialog.innerHTML = "";
    login(message);
  }
  $("#logout").onclick = () => logout();
  async function cognito(action, body) {
    const response = await fetch(
      `https://cognito-idp.${config.region || "us-east-2"}.amazonaws.com/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/x-amz-json-1.1",
          "X-Amz-Target": "AWSCognitoIdentityProviderService." + action,
        },
        body: JSON.stringify(body),
      },
    );
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Unable to sign in.");
    return result;
  }
  async function api(path, { method = "GET", body, raw = false } = {}) {
    const credential = token;
    const response = await fetch(config.apiBase + path, {
      method,
      headers: {
        Authorization: "Bearer " + credential,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const result =
      raw && response.ok
        ? await response.text()
        : await response.json().catch(() => ({}));
    if (token !== credential)
      throw new Error("Session changed. Please sign in again.");
    if (!response.ok) {
      if (response.status === 401 || response.status === 403)
        logout(
          response.status === 403
            ? "Your account needs membership in the organizers group."
            : "Your session expired. Please sign in again.",
        );
      throw new Error(result.message || "Request failed.");
    }
    return result;
  }

  function login(message = "") {
    $("#logout").hidden = true;
    root.innerHTML = `<section class="a-login"><p class="eyebrow">BRENT HOLIDAY SALE</p><h1>${challenge ? "Choose your password" : "Organizer sign-in"}</h1><p class="sub">${challenge ? "Replace your temporary password to continue." : "Private contacts and schedule management."}</p><form id="login-form">${challenge ? "" : `<label for="username">Username</label><input id="username" autocomplete="username" required value="${esc(username)}">`}<label for="password">${challenge ? "New password" : "Password"}</label><input id="password" type="password" autocomplete="${challenge ? "new-password" : "current-password"}" required ${challenge ? 'minlength="12"' : ""}>${challenge ? '<label for="confirm-password">Confirm new password</label><input id="confirm-password" type="password" autocomplete="new-password" required><p class="sub">At least 12 characters, including uppercase, lowercase, a number and a symbol.</p>' : ""}<p id="login-error" class="a-error" role="alert">${esc(message)}</p><button class="primary full" ${config.organizerClientId ? "" : "disabled"}>${challenge ? "Set password and sign in" : "Sign in"}</button></form><p class="a-footnote">${config.organizerClientId ? "Accounts are created by the team owner. For a password reset, contact the owner." : "Organizer access is not configured in this local preview."}</p></section>`;
    $("#login-form").onsubmit = async (event) => {
      event.preventDefault();
      const button = $("#login-form button");
      const password = $("#password").value;
      if (challenge && password !== $("#confirm-password").value) {
        $("#login-error").textContent = "The passwords do not match.";
        return;
      }
      button.disabled = true;
      try {
        let result;
        if (challenge) {
          result = await cognito("RespondToAuthChallenge", {
            ClientId: config.organizerClientId,
            ChallengeName: "NEW_PASSWORD_REQUIRED",
            Session: challenge.Session,
            ChallengeResponses: {
              USERNAME:
                challenge.ChallengeParameters.USER_ID_FOR_SRP || username,
              NEW_PASSWORD: password,
            },
          });
        } else {
          username = $("#username").value.trim();
          result = await cognito("InitiateAuth", {
            ClientId: config.organizerClientId,
            AuthFlow: "USER_PASSWORD_AUTH",
            AuthParameters: { USERNAME: username, PASSWORD: password },
          });
        }
        $("#password").value = "";
        if (result.ChallengeName === "NEW_PASSWORD_REQUIRED") {
          challenge = result;
          login();
          return;
        }
        if (!result.AuthenticationResult?.AccessToken)
          throw new Error(
            "This account needs an additional sign-in step. Contact the owner.",
          );
        setToken(result.AuthenticationResult.AccessToken);
        challenge = null;
        await refresh();
      } catch (error) {
        const target = $("#login-error");
        if (target) target.textContent = error.message;
        button.disabled = false;
      }
    };
  }
  async function refresh() {
    const result = await api("/admin/overview");
    data = result;
    const active = new Set(data.bookings.map((b) => b.id));
    selected = new Set([...selected].filter((id) => active.has(id)));
    render();
  }
  function shifts() {
    return data.shifts.filter(
      (s) => (!day || s.date === day) && (!role || s.role === role),
    );
  }
  function bookings() {
    const ids = new Set(shifts().map((s) => s.id));
    return data.bookings.filter(
      (b) =>
        ids.has(b.shiftId) &&
        (!search ||
          (b.name + " " + b.email)
            .toLowerCase()
            .includes(search.toLowerCase())),
    );
  }
  function job(id) {
    return data.shifts.find((s) => s.id === id);
  }
  function commonControls() {
    const dates = [...new Set(data.shifts.map((s) => s.date))].sort(),
      roles = [...new Set(data.shifts.map((s) => s.role))].sort();
    return `<div class="a-controls"><label class="sr" for="filter-day">Day</label><select id="filter-day"><option value="">All days</option>${dates.map((d) => `<option value="${esc(d)}" ${day === d ? "selected" : ""}>${esc(dateLabel(d))}</option>`).join("")}</select><label class="sr" for="filter-role">Job type</label><select id="filter-role"><option value="">All job types</option>${roles.map((r) => `<option ${role === r ? "selected" : ""}>${esc(r)}</option>`).join("")}</select></div>`;
  }
  function wireFilters() {
    $("#filter-day").onchange = (e) => {
      day = e.target.value;
      render();
    };
    $("#filter-role").onchange = (e) => {
      role = e.target.value;
      render();
    };
  }
  function render() {
    $("#logout").hidden = false;
    const gap = data.shifts.reduce(
        (n, s) =>
          n +
          s.coverage.reduce(
            (total, c) =>
              total + Math.max(0, c.target - c.count) * (c.end - c.start),
            0,
          ),
        0,
      ),
      pending = data.conflicts.filter((c) => !c.reviewed).length;
    root.innerHTML = `<div class="a-title"><div><p class="eyebrow">TREAM HEADQUARTERS</p><h1>Organizer desk</h1></div><button id="refresh">Refresh</button></div><div class="a-banner">Development · draft schedule · email sending is disabled. Use sample contact details.</div><div class="a-metrics"><div class="a-metric"><span>Active commitments</span><strong>${data.bookings.length}</strong></div><div class="a-metric"><span>Contact emails</span><strong>${new Set(data.bookings.map((b) => b.email)).size}</strong></div><div class="a-metric"><span>Overlaps to review</span><strong>${pending}</strong></div><div class="a-metric"><span>Unfilled volunteer-hours</span><strong>${Number(gap.toFixed(1))}</strong></div></div><nav class="a-tabs" aria-label="Organizer sections">${[
      ["coverage", "Coverage & shifts"],
      ["volunteers", "Volunteers"],
      ["conflicts", "Overlaps" + (pending ? " · " + pending : "")],
      ["messages", "Messages"],
    ]
      .map(
        ([id, label]) =>
          `<button data-view="${id}" class="${view === id ? "active" : ""}" aria-current="${view === id ? "page" : "false"}">${label}</button>`,
      )
      .join("")}</nav><section id="pane"></section>`;
    $("#refresh").onclick = () => refresh().catch((e) => toast(e.message));
    document.querySelectorAll("[data-view]").forEach(
      (b) =>
        (b.onclick = () => {
          view = b.dataset.view;
          preview = null;
          render();
        }),
    );
    if (view === "coverage") renderCoverage();
    if (view === "volunteers") renderVolunteers();
    if (view === "conflicts") renderConflicts();
    if (view === "messages") renderMessages();
  }
  function renderCoverage() {
    $("#pane").innerHTML =
      commonControls() +
      shifts()
        .map(
          (s) =>
            `<article class="a-card"><div class="a-card-header"><div><h2>${esc(s.name)}</h2><div class="sub">${esc(dateLabel(s.date))} · ${fmt(s.start)}–${fmt(s.end)} · ${esc(s.location || "Canal Park")}<br>Target ${s.capacity} · limit ${s.effectiveCapacity} (${s.overflowPercent || 0}% overflow) · ${s.open ? "Accepting signups" : "Signups closed"}</div></div><button data-edit="${s.id}">Edit shift</button></div><div class="a-timeline" aria-label="Staffing by time">${s.coverage.map((c) => `<div class="a-slot ${c.count < c.target ? "low" : ""}"><span>${fmt(c.start)}</span><strong>${c.count} / ${c.target}</strong><small>${c.count < c.target ? c.target - c.count + " needed" : "Target met"}<br>until ${fmt(c.end)}</small></div>`).join("")}</div><p class="a-footnote">${s.flex ? "Partial attendance allowed" : "Entire shift required"} · minimum ${s.attendance?.minMinutes ?? 30} minutes · only actual committed hours count</p></article>`,
        )
        .join("");
    wireFilters();
    document
      .querySelectorAll("[data-edit]")
      .forEach((b) => (b.onclick = () => editShift(b.dataset.edit)));
  }
  function openModal(html) {
    dialog.innerHTML =
      '<button class="close" aria-label="Close">×</button>' + html;
    if (!dialog.open) dialog.showModal();
    dialog.querySelector(".close").onclick = () => dialog.close();
  }
  function editShift(id) {
    const s = job(id),
      a = s.attendance || {};
    openModal(
      `<h2>Edit shift</h2><p class="sub">Existing commitments stay protected. Changes are recorded in the audit history.</p><form id="shift-form" class="a-modal-form"><label for="shift-name">Job name</label><input id="shift-name" required maxlength="100" value="${esc(s.name)}"><div class="times"><div><label for="shift-role">Job type</label><input id="shift-role" required maxlength="50" value="${esc(s.role)}"></div><div><label for="shift-date">Day</label><input id="shift-date" type="date" required value="${esc(s.date)}"></div></div><label for="shift-location">Location</label><input id="shift-location" required maxlength="180" value="${esc(s.location || "Canal Park")}"><div class="times"><div><label for="shift-start">Start</label><input id="shift-start" type="time" step="300" required value="${timeValue(s.start)}"></div><div><label for="shift-end">End</label><input id="shift-end" type="time" step="300" required value="${timeValue(s.end)}"></div></div><div class="times"><div><label for="shift-capacity">Staffing target / capacity</label><input id="shift-capacity" type="number" min="1" max="500" required value="${s.capacity}"></div><div><label for="shift-overflow">Allowed overflow (%)</label><input id="shift-overflow" type="number" min="0" max="100" step="any" required value="${s.overflowPercent || 0}"></div></div><div class="a-limit" id="limit-preview"></div><label class="a-checkbox"><input id="shift-flex" type="checkbox" ${s.flex ? "checked" : ""}> Allow partial attendance</label><label class="a-checkbox"><input id="shift-open" type="checkbox" ${s.open ? "checked" : ""}> Accept new signups</label><div class="times"><div><label for="shift-minimum">Minimum minutes</label><input id="shift-minimum" type="number" min="5" max="1440" step="5" value="${a.minMinutes || 30}" required></div><div><label for="shift-increment">Time-choice increment</label><select id="shift-increment">${[5, 10, 15, 20, 30, 60, 120].map((n) => `<option value="${n}" ${n === (a.incrementMinutes || 30) ? "selected" : ""}>${n} minutes</option>`).join("")}</select></div></div><details><summary>Advanced attendance rules</summary><label for="shift-maximum">Maximum commitment (minutes)</label><input id="shift-maximum" type="number" min="5" max="1440" value="${a.maxMinutes || 1440}"><label for="allowed-starts">Allowed arrival hours (JSON array, or null for any)</label><textarea id="allowed-starts" rows="2">${esc(JSON.stringify(a.allowedStarts ?? null))}</textarea><label for="allowed-ends">Allowed departure hours (JSON array, or null for any)</label><textarea id="allowed-ends" rows="2">${esc(JSON.stringify(a.allowedEnds ?? null))}</textarea><p class="sub">Example: [9, 9.5, 10]. Times must fit the shift and increment.</p></details><p id="shift-error" class="a-error" role="alert"></p><button class="primary full">Save shift</button></form>`,
    );
    const limit = () => {
      $("#limit-preview").textContent =
        "Effective limit: " +
        Math.floor(
          Number($("#shift-capacity").value) *
            (1 + Number($("#shift-overflow").value) / 100),
        ) +
        " people at a time.";
    };
    $("#shift-capacity").oninput = limit;
    $("#shift-overflow").oninput = limit;
    limit();
    $("#shift-form").onsubmit = async (event) => {
      event.preventDefault();
      const button = $("#shift-form .primary");
      button.disabled = true;
      try {
        const body = {
          revision: s.revision,
          name: $("#shift-name").value,
          role: $("#shift-role").value,
          location: $("#shift-location").value,
          date: $("#shift-date").value,
          start: hour($("#shift-start").value),
          end: hour($("#shift-end").value),
          capacity: Number($("#shift-capacity").value),
          overflowPercent: Number($("#shift-overflow").value),
          flex: $("#shift-flex").checked,
          open: $("#shift-open").checked,
          attendance: {
            incrementMinutes: Number($("#shift-increment").value),
            minMinutes: Number($("#shift-minimum").value),
            maxMinutes: Number($("#shift-maximum").value),
            allowedStarts: JSON.parse($("#allowed-starts").value),
            allowedEnds: JSON.parse($("#allowed-ends").value),
          },
        };
        await api("/admin/shifts/" + id, { method: "POST", body });
        dialog.close();
        await refresh();
        toast("Shift saved.");
      } catch (error) {
        const target = $("#shift-error");
        if (target)
          target.textContent =
            error instanceof SyntaxError
              ? "Advanced rules must be JSON arrays or null."
              : error.message;
        button.disabled = false;
      }
    };
  }
  function renderVolunteers() {
    const rows = bookings();
    $("#pane").innerHTML =
      commonControls() +
      `<div class="a-controls"><label class="sr" for="search">Search volunteers</label><input id="search" type="search" placeholder="Search name or email" value="${esc(search)}"><button id="message-selected" ${selected.size ? "" : "disabled"}>Message selected (${selected.size})</button><button id="export">Export filtered roster</button></div><div class="a-table-wrap"><table class="a-table"><thead><tr><th><input type="checkbox" id="select-all" aria-label="Select visible volunteers" ${rows.length && rows.every((b) => selected.has(b.id)) ? "checked" : ""}></th><th>Volunteer / private contact</th><th>Job</th><th>Committed hours</th><th>Public name</th><th>Actions</th></tr></thead><tbody>${rows.map((b) => `<tr><td><input type="checkbox" data-select="${b.id}" aria-label="Select ${esc(b.name)}" ${selected.has(b.id) ? "checked" : ""}></td><td><strong>${esc(b.name)}</strong><small>${esc(b.email)}</small></td><td>${esc(job(b.shiftId)?.name)}<small>${esc(dateLabel(job(b.shiftId).date))}</small></td><td>${fmt(b.start)}–${fmt(b.end)}</td><td>${esc(b.publicName)}</td><td><button data-message="${b.id}">Message</button> <button class="danger" data-cancel="${b.id}">Cancel</button></td></tr>`).join("") || '<tr><td colspan="6">No active commitments match these filters.</td></tr>'}</tbody></table></div><p class="a-footnote">Contacts are private. Shared email addresses can belong to several family members. Message recipients are deduplicated by email.</p>`;
    wireFilters();
    $("#search").oninput = (e) => {
      search = e.target.value;
      const start = e.target.selectionStart;
      renderVolunteers();
      $("#search").focus();
      $("#search").setSelectionRange(start, start);
    };
    $("#select-all").onchange = (e) => {
      rows.forEach((b) => {
        if (e.target.checked) selected.add(b.id);
        else selected.delete(b.id);
      });
      renderVolunteers();
    };
    document.querySelectorAll("[data-select]").forEach(
      (input) =>
        (input.onchange = () => {
          if (input.checked) selected.add(input.dataset.select);
          else selected.delete(input.dataset.select);
          renderVolunteers();
        }),
    );
    const compose = () => {
      view = "messages";
      preview = null;
      render();
    };
    $("#message-selected").onclick = compose;
    document.querySelectorAll("[data-message]").forEach(
      (button) =>
        (button.onclick = () => {
          selected = new Set([button.dataset.message]);
          compose();
        }),
    );
    document
      .querySelectorAll("[data-cancel]")
      .forEach((b) => (b.onclick = () => cancelBooking(b.dataset.cancel)));
    $("#export").onclick = async () => {
      try {
        const params = new URLSearchParams();
        if (day) params.set("day", day);
        if (role) params.set("role", role);
        if (search) params.set("q", search);
        const text = await api("/admin/export.csv?" + params, { raw: true });
        const url = URL.createObjectURL(
          new Blob([text], { type: "text/csv;charset=utf-8" }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = "tream-roster.csv";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) {
        toast(error.message);
      }
    };
  }
  function cancelBooking(id) {
    const b = data.bookings.find((p) => p.id === id);
    openModal(
      `<h2>Cancel this commitment?</h2><div class="summary"><strong>${esc(b.name)}</strong><br>${esc(job(b.shiftId).name)}<br>${dateLabel(job(b.shiftId).date)} · ${fmt(b.start)}–${fmt(b.end)}</div><p class="sub">Their space will reopen. No notification is sent while email is disabled.</p><p id="cancel-error" class="a-error" role="alert"></p><button class="primary" id="cancel-confirm">Yes, cancel commitment</button>`,
    );
    $("#cancel-confirm").onclick = async () => {
      $("#cancel-confirm").disabled = true;
      try {
        await api("/admin/bookings/" + id + "/cancel", {
          method: "POST",
          body: {},
        });
        dialog.close();
        await refresh();
        toast("Commitment canceled.");
      } catch (error) {
        if ($("#cancel-error")) $("#cancel-error").textContent = error.message;
        if ($("#cancel-confirm")) $("#cancel-confirm").disabled = false;
      }
    };
  }
  function renderConflicts() {
    const byId = new Map(data.bookings.map((b) => [b.id, b]));
    const rows = data.conflicts.filter((c) => showReviewed || !c.reviewed);
    $("#pane").innerHTML =
      `<div class="a-controls"><label class="a-checkbox"><input type="checkbox" id="show-reviewed" ${showReviewed ? "checked" : ""}> Include reviewed overlaps</label></div><p class="sub">These flags never block a signup. Shared family email addresses need a human check.</p>` +
      (rows
        .map(
          (c) =>
            `<article class="a-card a-conflict"><div class="a-card-header"><div><h2>${c.kind === "same_person" ? "Possible same-person overlap" : "Shared-email overlap"}</h2><span class="sub">${esc(c.email)}</span></div>${c.reviewed ? '<span class="a-reviewed">Reviewed</span>' : ""}</div>${c.bookingIds
              .map((id) => {
                const b = byId.get(id);
                return `<p><strong>${esc(b.name)}</strong> · ${esc(job(b.shiftId).name)}<br><span class="sub">${esc(dateLabel(job(b.shiftId).date))} · ${fmt(b.start)}–${fmt(b.end)}</span></p>`;
              })
              .join(
                "",
              )}${c.note ? `<p class="a-note">${esc(c.note)}</p>` : ""}<div class="a-action-row"><button data-review="${c.id}">${c.reviewed ? "Update review" : "Mark reviewed"}</button>${c.bookingIds.map((id) => `<button data-cancel="${id}" class="danger">Cancel ${esc(byId.get(id).name)}’s booking</button>`).join("")}</div></article>`,
        )
        .join("") || '<div class="a-empty">No overlaps need review.</div>');
    $("#show-reviewed").onchange = (e) => {
      showReviewed = e.target.checked;
      renderConflicts();
    };
    document
      .querySelectorAll("[data-cancel]")
      .forEach((b) => (b.onclick = () => cancelBooking(b.dataset.cancel)));
    document.querySelectorAll("[data-review]").forEach(
      (button) =>
        (button.onclick = () => {
          const c = data.conflicts.find((c) => c.id === button.dataset.review);
          openModal(
            `<h2>Review overlap</h2><p class="sub">Record why these commitments can coexist, or what you confirmed with the family.</p><form id="review-form" class="a-modal-form"><label for="review-note">Note (optional)</label><textarea id="review-note" maxlength="500" rows="4">${esc(c.note || "")}</textarea><p id="review-error" class="a-error" role="alert"></p><button class="primary full">Save review</button></form>`,
          );
          $("#review-form").onsubmit = async (e) => {
            e.preventDefault();
            try {
              await api("/admin/conflicts/" + c.id + "/review", {
                method: "POST",
                body: { note: $("#review-note").value },
              });
              dialog.close();
              await refresh();
              toast("Overlap marked reviewed.");
            } catch (error) {
              if ($("#review-error"))
                $("#review-error").textContent = error.message;
            }
          };
        }),
    );
  }
  function renderMessages() {
    $("#pane").innerHTML =
      `<div class="a-message"><section class="a-card"><h2>Compose a team update</h2><p class="sub">One volunteer, a group, or everyone. Preview the individual recipient list before saving.</p><form id="message-form"><label for="recipient-mode">Recipients</label><select id="recipient-mode"><option value="selected" ${selected.size ? "selected" : ""}>Selected volunteers (${selected.size})</option><option value="group">A group</option><option value="all" ${selected.size ? "" : "selected"}>All active volunteers</option></select><div id="group-fields" hidden><label for="group-field">Group by</label><select id="group-field"><option value="date">Day</option><option value="role">Job type</option><option value="shiftId">Shift</option></select><label for="group-value">Choose group</label><select id="group-value"></select></div><label for="subject">Subject</label><input id="subject" required maxlength="180" placeholder="Saturday morning: where to meet"><label for="message-body">Message</label><textarea id="message-body" required maxlength="8000" placeholder="Hi Tream…"></textarea><p class="a-error" id="message-error" role="alert"></p><button class="primary full">Preview recipients</button></form></section><section class="a-card" id="message-preview"><h2>Recipient preview</h2><p class="sub">Email is disabled. You can preview and save a private draft; nothing will be sent or automatically queued for later.</p></section></div><section class="a-card" id="saved-drafts"><h2>Saved drafts</h2><p class="sub">Loading…</p></section>`;
    const groups = () => {
      const field = $("#group-field").value;
      const values =
        field === "shiftId"
          ? data.shifts.map((s) => [s.id, s.name + " · " + dateLabel(s.date)])
          : [...new Set(data.shifts.map((s) => s[field]))]
              .sort()
              .map((v) => [v, field === "date" ? dateLabel(v) : v]);
      $("#group-value").innerHTML = values
        .map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`)
        .join("");
    };
    groups();
    $("#group-field").onchange = () => {
      groups();
      invalidate();
    };
    $("#recipient-mode").onchange = () => {
      $("#group-fields").hidden = $("#recipient-mode").value !== "group";
      invalidate();
    };
    function invalidate() {
      preview = null;
      if ($("#save-draft")) $("#save-draft").disabled = true;
    }
    async function loadDrafts() {
      try {
        const result = await api("/admin/messages");
        const target = $("#saved-drafts");
        if (!target) return;
        const drafts = result.drafts || [];
        target.innerHTML =
          '<div class="a-card-header"><h2>Saved drafts</h2><button id="refresh-drafts">Refresh drafts</button></div><p class="sub">Private drafts expire after 30 days. Loading one always requires a new recipient preview.</p>' +
          (drafts.length
            ? drafts
                .map(
                  (d) =>
                    `<div class="a-recipient"><strong>${esc(d.subject)}</strong><p class="sub">${new Date(d.createdAt * 1000).toLocaleString()} · ${d.recipientCount} contacts</p><button data-load-draft="${d.id}">Load draft</button></div>`,
                )
                .join("")
            : '<p class="sub">No saved drafts.</p>');
        $("#refresh-drafts").onclick = loadDrafts;
        target.querySelectorAll("[data-load-draft]").forEach(
          (b) =>
            (b.onclick = () => {
              const draft = drafts.find((d) => d.id === b.dataset.loadDraft),
                selector = draft.selector || { mode: "all" };
              if (selector.mode === "selected") {
                const active = new Set(data.bookings.map((b) => b.id));
                selected = new Set(
                  selector.bookingIds.filter((id) => active.has(id)),
                );
                $('#recipient-mode option[value="selected"]').textContent =
                  "Selected volunteers (" + selected.size + ")";
              }
              $("#recipient-mode").value = selector.mode;
              $("#group-fields").hidden = selector.mode !== "group";
              if (selector.mode === "group") {
                $("#group-field").value = selector.field;
                groups();
                $("#group-value").value = selector.value;
              }
              $("#subject").value = draft.subject;
              $("#message-body").value = draft.body;
              invalidate();
              $("#message-preview").innerHTML =
                '<h2>Draft loaded</h2><p class="sub">Preview the current recipients before saving. Email is still disabled.</p>';
              $("#subject").focus();
            }),
        );
      } catch (error) {
        const target = $("#saved-drafts");
        if (target) target.textContent = error.message;
      }
    }
    loadDrafts();
    $("#group-value").onchange = invalidate;
    $("#subject").oninput = invalidate;
    $("#message-body").oninput = invalidate;
    $("#message-form").onsubmit = async (e) => {
      e.preventDefault();
      const mode = $("#recipient-mode").value;
      const selector =
        mode === "selected"
          ? { mode, bookingIds: [...selected] }
          : mode === "group"
            ? {
                mode,
                field: $("#group-field").value,
                value: $("#group-value").value,
              }
            : { mode };
      const body = {
        selector,
        subject: $("#subject").value,
        body: $("#message-body").value,
      };
      try {
        preview = await api("/admin/messages/preview", {
          method: "POST",
          body,
        });
        $("#message-error").textContent = "";
        $("#message-preview").innerHTML =
          `<h2>${preview.recipientCount} contact${preview.recipientCount === 1 ? "" : "s"} · ${preview.volunteerCount} commitments</h2><p class="sub">Each contact receives their own message. No shared To/CC list.</p><h3>${esc(preview.subject)}</h3><p class="a-preview-body">${esc(preview.body)}</p>${preview.recipients.map((r) => `<div class="a-recipient"><strong>${esc(r.email)}</strong><ul>${r.commitments.map((c) => `<li>${esc(c.name)} · ${esc(c.shift)} · ${esc(dateLabel(c.date))}, ${fmt(c.start)}–${fmt(c.end)}</li>`).join("")}</ul></div>`).join("")}<button class="primary full" id="save-draft">Save draft · sending disabled</button><p class="a-inline-message" id="draft-status" role="status"></p>`;
        $("#save-draft").onclick = async () => {
          $("#save-draft").disabled = true;
          try {
            await api("/admin/messages", {
              method: "POST",
              body: { ...body, fingerprint: preview.fingerprint },
            });
            $("#draft-status").textContent =
              "Private draft saved. No messages sent.";
            loadDrafts();
          } catch (error) {
            if ($("#draft-status"))
              $("#draft-status").textContent = error.message;
          }
        };
      } catch (error) {
        if ($("#message-error"))
          $("#message-error").textContent = error.message;
      }
    };
  }
  if (token && config.apiBase)
    refresh().catch((error) => {
      if (!$("#login-form")) login(error.message);
    });
  else login();
})();
