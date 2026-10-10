(() => {
  "use strict";

  const root = document.getElementById("admin-root");
  const tokenKey = "eventsecure-admin-token";
  const userKey = "eventsecure-admin-user";
  const sections = {
    dashboard: ["Dashboard", "Operational overview from the shared EventSecure database."],
    events: ["Events", "Create, publish, edit, close, or cancel events."],
    participants: ["Participants", "Find participant profiles and review their registration history."],
    registrations: ["Registrations", "Review eligibility, manage status, and control QR passes."],
    "biometric-verifications": ["Biometric verification", "Monitor verification results and record authorized decisions."],
    "qr-passes": ["QR passes", "Search, revoke, or reissue registration passes."],
    "check-in": ["Event check-in", "Validate a pass and record an authorized gate entry."],
    reports: ["Reports", "Review registration, verification, and capacity reporting."],
    "audit-logs": ["Audit logs", "Review administrative actions recorded by the backend."],
    settings: ["Settings", "View active integration and verification configuration."],
    users: ["Admin users", "Review admin accounts and assigned roles."]
  };
  const navItems = [
    ["dashboard", "Overview", "▦"],
    ["events", "Events", "◷"],
    ["participants", "Participants", "♙"],
    ["registrations", "Registrations", "▤"],
    ["biometric-verifications", "Biometric review", "◎"],
    ["qr-passes", "QR passes", "▧"],
    ["check-in", "Check-in", "↗"],
    ["reports", "Reports", "▥"],
    ["audit-logs", "Audit logs", "≡"],
    ["settings", "Settings", "⚙"],
    ["users", "Admin users", "♧"]
  ];
  const roleMenus = {
    event_manager: ["dashboard", "events", "participants", "registrations", "biometric-verifications", "qr-passes", "check-in", "reports"],
    registration_manager: ["dashboard", "events", "participants", "registrations", "biometric-verifications", "qr-passes", "check-in", "reports"],
    biometric_reviewer: ["dashboard", "participants", "registrations", "biometric-verifications", "reports"],
    gate_operator: ["dashboard", "events", "check-in"],
    auditor: ["dashboard", "events", "participants", "registrations", "biometric-verifications", "qr-passes", "reports", "audit-logs"]
  };
  const token = () => sessionStorage.getItem(tokenKey);
  let user = null;
  let eventsCache = [];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
  }

  function toast(message, error = false) {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const item = document.createElement("div");
    item.className = `toast${error ? " error" : ""}`;
    item.textContent = message;
    region.append(item);
    window.setTimeout(() => item.remove(), 5000);
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token()) headers.set("Authorization", `Bearer ${token()}`);
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(`/api/admin${path}`, { ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      if (response.status === 401) logout();
      const detail = typeof body === "object" && body ? body.detail : body;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return body;
  }

  function currentSection() {
    return location.pathname.replace(/^\/admin\/?/, "").split("/")[0] || "dashboard";
  }

  function allowedSections() {
    if (!user) return [];
    if (user.role === "super_admin") return Object.keys(sections);
    return roleMenus[user.role] || ["dashboard"];
  }

  function shell(section, content) {
    const visibleItems = navItems.filter(([key]) => allowedSections().includes(key));
    const title = sections[section]?.[0] || "Admin";
    const description = sections[section]?.[1] || "";
    root.innerHTML = `
      <div class="admin-shell">
        <aside class="sidebar">
          <a class="brand" href="/admin/dashboard"><span class="brand-icon">ES</span><span class="brand-copy"><strong>EventSecure</strong><small>Administration</small></span></a>
          <div class="nav-label">Workspace</div>
          <nav class="side-nav" aria-label="Admin navigation">
            ${visibleItems.map(([key, label, symbol]) => `<a href="/admin/${key}" class="${key === section ? "active" : ""}" ${key === section ? 'aria-current="page"' : ""}><span class="nav-symbol">${symbol}</span>${label}</a>`).join("")}
          </nav>
          <div class="sidebar-foot"><div class="user-mini"><span class="avatar">${escapeHtml((user.username || "A").slice(0, 1).toUpperCase())}</span><span>${escapeHtml(user.username)}<small>${escapeHtml(user.role.replaceAll("_", " "))}</small></span></div><button class="btn btn-quiet" id="logout-button" type="button">Sign out</button></div>
        </aside>
        <section class="main-area">
          <header class="topbar"><div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div><div class="topbar-right"><span class="role-chip">${escapeHtml(user.role.replaceAll("_", " "))}</span><span>${escapeHtml(user.email)}</span></div></header>
          <main class="content">${content}</main>
        </section>
      </div>`;
    document.getElementById("logout-button")?.addEventListener("click", () => logout());
  }

  function pageHeading(title, description, action = "") {
    return `<div class="page-heading"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>${action}</div>`;
  }

  function metric(label, value, note = "") {
    return `<article class="metric"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div><div class="metric-note">${escapeHtml(note)}</div></article>`;
  }

  function statusPill(value) {
    const safe = String(value || "unknown");
    return `<span class="status status-${escapeHtml(safe.toLowerCase())}">${escapeHtml(safe.replaceAll("_", " "))}</span>`;
  }

  function table(headers, rows, empty = "No records found.") {
    if (!rows.length) return `<div class="empty">${escapeHtml(empty)}</div>`;
    return `<div class="table-wrap"><table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }

  function detailItem(label, value) {
    return `<div class="detail-item"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value || "—")}</strong></div>`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  async function loginPage() {
    root.innerHTML = `
      <section class="login-screen"><div class="login-card">
        <div class="login-brand"><span class="brand-icon">ES</span><span class="brand-copy"><strong>EventSecure Admin</strong><small>Secure operations console</small></span></div>
        <h1>Admin sign in</h1><p>Sign in with your authorized administrator account.</p>
        <form id="login-form" class="form-grid">
          <label class="span-2">Email or username<input name="identifier" autocomplete="username" required minlength="3"></label>
          <label class="span-2">Password<input name="password" type="password" autocomplete="current-password" required minlength="4"></label>
          <label class="span-2">MFA code <span class="muted">(if required)</span><input name="mfa_code" inputmode="numeric" autocomplete="one-time-code" maxlength="12"></label>
          <div class="span-2" id="login-error" role="alert"></div>
          <button class="btn btn-primary span-2" type="submit">Sign in securely</button>
        </form>
        <p style="margin:1.2rem 0 0;font-size:.76rem">Participant registration is a separate application.</p>
      </div></section>`;
    const form = document.getElementById("login-form");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const button = form.querySelector("button");
      button.disabled = true;
      const errorBox = document.getElementById("login-error");
      errorBox.textContent = "";
      try {
        const response = await fetch("/api/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            identifier: data.get("identifier"),
            password: data.get("password"),
            mfa_code: data.get("mfa_code") || null
          })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Sign-in failed");
        sessionStorage.setItem(tokenKey, result.token);
        sessionStorage.setItem(userKey, JSON.stringify(result.user));
        location.replace("/admin/dashboard");
      } catch (error) {
        errorBox.className = "notice error-notice span-2";
        errorBox.textContent = error.message;
        button.disabled = false;
      }
    });
  }

  function logout(redirect = true) {
    sessionStorage.removeItem(tokenKey);
    sessionStorage.removeItem(userKey);
    user = null;
    if (redirect) location.replace("/admin/login");
  }

  async function loadDashboard() {
    const [summary, eventRows, registrations] = await Promise.all([
      api("/dashboard"), api("/events"), api("/registrations")
    ]);
    eventsCache = eventRows;
    const activity = (summary.recent_activity || []).map((entry) => `<div class="activity-row">${escapeHtml(entry)}<small>Recent registration</small></div>`);
    const recent = registrations.slice(0, 6).map((row) => `<tr><td>${escapeHtml(row.registration_id)}</td><td>${escapeHtml(row.full_name)}</td><td>${escapeHtml(row.event_id)}</td><td>${statusPill(row.status)}</td><td>${escapeHtml(formatDate(row.created_at))}</td></tr>`);
    shell("dashboard", `${pageHeading("Operations overview", "Live counts and activity from the shared registration database.", `<button class="btn" id="refresh-dashboard">Refresh data</button>`)}
      <div class="cards">
        ${metric("Events", summary.total_events, "All event records")}
        ${metric("Participants", summary.total_participants, "Participant profiles")}
        ${metric("Registrations", summary.total_registrations, "All registration records")}
        ${metric("Pending verification", Number(summary.pending_otp_verification) + Number(summary.pending_biometric_verification), `${summary.pending_otp_verification} OTP · ${summary.pending_biometric_verification} biometric`)}
        ${metric("Verified participants", summary.verified_participants, "Registered or checked in")}
        ${metric("QR passes issued", summary.qr_passes_issued, "Passes currently recorded")}
        ${metric("Today's check-ins", summary.today_checkins, "Confirmed today")}
        ${metric("Failed verification", summary.failed_verification_attempts, "Rejected registration records")}
      </div>
      <div class="split"><section class="panel"><div class="panel-head"><h3>Recent registrations</h3><a class="btn" href="/admin/registrations">All registrations</a></div>${table(["Registration", "Participant", "Event", "Status", "Created"], recent)}</section>
      <section class="panel"><div class="panel-head"><h3>Recent activity</h3><a class="btn" href="/admin/audit-logs">Audit log</a></div><div class="panel-body activity-list">${activity.length ? activity.join("") : '<div class="empty">No recent activity.</div>'}</div></section></div>`);
    document.getElementById("refresh-dashboard").addEventListener("click", () => route());
  }

  function eventEditor(event = null) {
    const editing = Boolean(event);
    const value = (key, fallback = "") => event?.[key] ?? fallback;
    const dt = (input) => input ? new Date(input).toISOString().slice(0, 16) : "";
    return `<section class="panel"><div class="panel-head"><h3>${editing ? "Edit event" : "Create event"}</h3><button class="btn btn-quiet" type="button" id="close-event-form">Close</button></div>
      <form id="event-form" class="panel-body form-grid">
      <label>Event ID<input name="event_id" required minlength="2" value="${escapeHtml(value("event_id"))}" ${editing ? "readonly" : ""}></label>
      <label>Event name<input name="event_name" required minlength="2" value="${escapeHtml(value("event_name"))}"></label>
      <label>Date and time<input name="event_date" type="datetime-local" required value="${escapeHtml(dt(value("event_date")))}"></label>
      <label>Venue<input name="venue" value="${escapeHtml(value("venue"))}"></label>
      <label>Maximum capacity<input name="capacity" type="number" min="1" required value="${escapeHtml(value("capacity", 500))}"></label>
      <label>Registration start<input name="registration_start" type="datetime-local" value="${escapeHtml(dt(value("registration_start")))}"></label>
      <label>Registration end<input name="registration_end" type="datetime-local" value="${escapeHtml(dt(value("registration_end")))}"></label>
      <label>Participant types (comma-separated)<input name="participant_types" value="${escapeHtml(value("participant_types", "Attendee,Speaker,VIP,Organizer,Delegate"))}"></label>
      <label>Verification requirements (comma-separated)<input name="verification_requirements" value="${escapeHtml(value("verification_requirements", "otp,face,liveness,pad"))}"></label>
      <label>Status<select name="status">${["draft","published","closed","cancelled"].map((s) => `<option value="${s}" ${value("status", "draft") === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
      <div class="span-2"><button class="btn btn-primary" type="submit">${editing ? "Save event" : "Create event"}</button></div>
      </form></section>`;
  }

  async function loadEvents(openCreate = false) {
    eventsCache = await api("/events");
    const rows = eventsCache.map((event) => `<tr>
      <td><strong>${escapeHtml(event.event_name)}</strong><small class="muted" style="display:block">${escapeHtml(event.event_id)}</small></td>
      <td>${escapeHtml(formatDate(event.event_date))}</td><td>${escapeHtml(event.venue)}</td>
      <td>${escapeHtml(event.registered_count)} / ${escapeHtml(event.capacity)}</td><td>${statusPill(event.status)}</td>
      <td><div class="inline-actions"><button class="btn" data-edit-event="${escapeHtml(event.event_id)}">Edit</button>${event.status === "published" ? `<button class="btn" data-event-status="${escapeHtml(event.event_id)}" data-status="closed">Close</button>` : event.status === "draft" ? `<button class="btn" data-event-status="${escapeHtml(event.event_id)}" data-status="published">Publish</button>` : ""}</div></td></tr>`);
    shell("events", `${pageHeading("Event management", "Manage event details, capacity, dates, and verification policy.", `<button class="btn btn-primary" id="new-event">＋ Create event</button>`)}
      <div id="event-editor"></div><section class="panel">${table(["Event", "Date", "Venue", "Capacity", "Status", "Actions"], rows)}</section>`);
    const editor = document.getElementById("event-editor");
    const showEditor = (event = null) => {
      const editingEvent = event?.event_id || null;
      editor.innerHTML = eventEditor(event);
      document.getElementById("close-event-form").addEventListener("click", () => { editor.innerHTML = ""; });
      document.getElementById("event-form").addEventListener("submit", async (submitEvent) => {
        submitEvent.preventDefault();
        const form = submitEvent.currentTarget;
        const data = Object.fromEntries(new FormData(form));
        data.capacity = Number(data.capacity);
        for (const key of ["event_date", "registration_start", "registration_end"]) {
          data[key] = data[key] ? new Date(data[key]).toISOString() : null;
        }
        try {
          await api(editingEvent ? `/events/${encodeURIComponent(editingEvent)}` : "/events", {
            method: editingEvent ? "PATCH" : "POST", body: JSON.stringify(data)
          });
          toast(editingEvent ? "Event updated." : "Event created.");
          await loadEvents();
        } catch (error) { toast(error.message, true); }
      });
    };
    document.getElementById("new-event").addEventListener("click", () => showEditor());
    if (openCreate) showEditor();
    document.querySelectorAll("[data-edit-event]").forEach((button) => button.addEventListener("click", () => {
      const event = eventsCache.find((item) => item.event_id === button.dataset.editEvent);
      if (event) showEditor(event);
    }));
    document.querySelectorAll("[data-event-status]").forEach((button) => button.addEventListener("click", async () => {
      try {
        await api(`/events/${encodeURIComponent(button.dataset.eventStatus)}`, {
          method: "PATCH", body: JSON.stringify({ status: button.dataset.status })
        });
        toast(`Event ${button.dataset.status}.`);
        await loadEvents();
      } catch (error) { toast(error.message, true); }
    }));
  }

  async function loadParticipants(participantKey = "") {
    shell("participants", `${pageHeading("Participant directory", "Search by participant ID, name, email, or mobile.")}
      <section class="panel"><div class="panel-body toolbar"><input id="participant-search" placeholder="Search participants…" aria-label="Search participants"><button class="btn btn-primary" id="participant-search-button">Search</button></div><div id="participant-table"></div></section>
      <section class="panel"><div class="panel-head"><h3>Participant profile</h3></div><div class="panel-body" id="participant-detail"><span class="muted">Select a participant to view their profile and history.</span></div></section>`);
    const search = document.getElementById("participant-search");
    const render = async () => {
      try {
        const query = search.value.trim();
        const rows = await api(`/participants${query ? `?q=${encodeURIComponent(query)}` : ""}`);
        document.getElementById("participant-table").innerHTML = table(["Participant ID", "Name", "Email", "Mobile", "Type", "Created", "Profile"], rows.map((row) => `<tr><td>${escapeHtml(row.participant_id)}</td><td>${escapeHtml(row.full_name)}</td><td>${escapeHtml(row.email)}</td><td>${escapeHtml(row.mobile)}</td><td>${escapeHtml(row.participant_type)}</td><td>${escapeHtml(formatDate(row.created_at))}</td><td><button class="btn" data-participant="${escapeHtml(row.participant_id)}">View</button></td></tr>`));
        document.querySelectorAll("[data-participant]").forEach((button) => button.addEventListener("click", () => showParticipant(button.dataset.participant)));
      } catch (error) { toast(error.message, true); }
    };
    const showParticipant = async (id) => {
      try {
        const [person, registrations, biometrics, passes] = await Promise.all([
          api(`/participants/${encodeURIComponent(id)}`),
          api(`/registrations?q=${encodeURIComponent(id)}`),
          api(`/biometric-verifications?participant_id=${encodeURIComponent(id)}`),
          api(`/qr-passes?q=${encodeURIComponent(id)}`)
        ]);
        const host = document.getElementById("participant-detail");
        const history = registrations.map((row) => `<tr><td>${escapeHtml(row.registration_id)}</td><td>${escapeHtml(row.event_id)}</td><td>${statusPill(row.status)}</td><td>${escapeHtml(formatDate(row.created_at))}</td></tr>`);
        const bioSummary = biometrics.map((row) => `<div class="activity-row">${escapeHtml(row.verification_id)} · face ${row.face_verified ? "passed" : "not passed"}, liveness ${row.liveness_verified ? "passed" : "not passed"}, PAD ${row.pad_verified ? "passed" : "not passed"}<small>Consent ref: ${escapeHtml(row.consent_id)}</small></div>`).join("") || '<div class="muted">No biometric records found.</div>';
        host.innerHTML = `<div class="detail-grid">${detailItem("Participant ID", person.participant_id)}${detailItem("Full name", person.full_name)}${detailItem("Email", person.email)}${detailItem("Mobile", person.mobile)}${detailItem("Participant type", person.participant_type)}${detailItem("Organization", person.organization)}${detailItem("Profile created", formatDate(person.created_at))}${detailItem("QR pass history records", passes.length)}</div>
          <div class="panel-head" style="padding-inline:0;border:0"><h3>Registration history</h3></div>${table(["Registration", "Event", "Status", "Created"], history)}
          <div class="panel-head" style="padding-inline:0;border:0"><h3>Biometric and consent references</h3></div><div>${bioSummary}</div>
          <div class="notice" style="margin-top:.8rem">Contact verification and consent withdrawal history are not exposed by the current backend API.</div>`;
      } catch (error) { toast(error.message, true); }
    };
    document.getElementById("participant-search-button").addEventListener("click", render);
    search.addEventListener("keydown", (event) => { if (event.key === "Enter") render(); });
    await render();
    if (participantKey) await showParticipant(decodeURIComponent(participantKey));
  }

  async function loadRegistrations(registrationKey = "") {
    const events = await api("/events");
    const options = events.map((event) => `<option value="${escapeHtml(event.event_id)}">${escapeHtml(event.event_name)}</option>`).join("");
    shell("registrations", `${pageHeading("Registration management", "Filter registrations, inspect verification status, and administer eligibility and passes.")}
      <section class="panel"><div class="panel-body toolbar">
        <input id="registration-search" placeholder="Registration, participant, name, or email">
        <select id="registration-event"><option value="">All events</option>${options}</select>
        <select id="registration-status"><option value="">All statuses</option>${["otp_pending","face_pending","liveness_pending","pad_pending","registered","checked_in","waitlist","rejected","cancelled"].map((s) => `<option value="${s}">${s.replaceAll("_"," ")}</option>`).join("")}</select>
        <input id="registration-from" type="date" aria-label="Created from">
        <input id="registration-to" type="date" aria-label="Created to">
        <button class="btn btn-primary" id="registration-search-button">Apply filters</button></div><div id="registration-table"></div></section>
      <section class="panel"><div class="panel-head"><h3>Registration detail</h3></div><div class="panel-body" id="registration-detail"><span class="muted">Select a registration to view details and available actions.</span></div></section>`);
    const render = async () => {
      const params = new URLSearchParams();
      const q = document.getElementById("registration-search").value.trim();
      const eventId = document.getElementById("registration-event").value;
      const status = document.getElementById("registration-status").value;
      const createdFrom = document.getElementById("registration-from").value;
      const createdTo = document.getElementById("registration-to").value;
      if (q) params.set("q", q);
      if (eventId) params.set("event_id", eventId);
      if (status) params.set("status", status);
      if (createdFrom) params.set("created_from", new Date(`${createdFrom}T00:00:00`).toISOString());
      if (createdTo) {
        const endDate = new Date(`${createdTo}T00:00:00`);
        endDate.setDate(endDate.getDate() + 1);
        params.set("created_to", endDate.toISOString());
      }
      try {
        const rows = await api(`/registrations${params.size ? `?${params}` : ""}`);
        document.getElementById("registration-table").innerHTML = table(["Code", "Participant", "Event", "Created", "Eligibility", "Status", "Actions"], rows.map((row) => {
          const otp = row.status === "otp_pending" ? "OTP pending" : "OTP complete";
          const eligibility = `${otp} · Face ${row.face_verified ? "passed" : "pending"} · Live ${row.liveness_verified ? "passed" : "pending"} · PAD ${row.pad_verified ? "passed" : "pending"}`;
          return `<tr><td>${escapeHtml(row.registration_id)}</td><td>${escapeHtml(row.full_name)}<small class="muted" style="display:block">${escapeHtml(row.participant_id)}</small></td><td>${escapeHtml(row.event_id)}</td><td>${escapeHtml(formatDate(row.created_at))}</td><td>${escapeHtml(eligibility)}</td><td>${statusPill(row.status)}</td><td><button class="btn" data-registration="${row.id}">Details</button></td></tr>`;
        }));
        document.querySelectorAll("[data-registration]").forEach((button) => button.addEventListener("click", () => showRegistration(button.dataset.registration)));
      } catch (error) { toast(error.message, true); }
    };
    const showRegistration = async (id) => {
      try {
        const item = await api(`/registrations/${id}`);
        const host = document.getElementById("registration-detail");
        host.innerHTML = `<div class="detail-grid">${detailItem("Registration ID", item.registration_id)}${detailItem("Participant", item.full_name)}${detailItem("Participant ID", item.participant_id)}${detailItem("Event", item.event_id)}${detailItem("Email", item.email)}${detailItem("Mobile", item.mobile)}${detailItem("Created", formatDate(item.created_at))}${detailItem("Registered", formatDate(item.registered_at))}${detailItem("Face", item.face_verified ? "Passed" : "Pending / not passed")}${detailItem("Liveness", item.liveness_verified ? "Passed" : "Pending / not passed")}${detailItem("PAD", item.pad_verified ? "Passed" : "Pending / not passed")}${detailItem("QR pass", item.qr_token ? "Active token recorded" : "No active token")}${detailItem("Check-in", formatDate(item.checked_in_at))}</div>
          <div class="toolbar" style="margin-top:1rem"><select id="new-registration-status">${["registered","rejected","waitlist","cancelled"].map((s) => `<option value="${s}" ${item.status === s ? "selected" : ""}>${s}</option>`).join("")}</select><input id="registration-reason" placeholder="Reason for status change" maxlength="500"><button class="btn btn-primary" id="save-registration-status">Update status</button>${item.qr_token ? '<button class="btn btn-danger" id="revoke-registration-qr">Revoke pass</button>' : '<button class="btn" id="reissue-registration-qr">Issue / reissue pass</button>'}</div>
          <div class="notice" style="margin-top:.8rem">The current backend does not expose per-registration audit history. Admin status changes are recorded in the global audit log.</div>`;
        document.getElementById("save-registration-status").addEventListener("click", async () => {
          const reason = document.getElementById("registration-reason").value.trim();
          if (reason.length < 3) { toast("Provide a reason of at least 3 characters for this status change.", true); return; }
          try {
            await api(`/registrations/${id}/status`, { method: "PATCH", body: JSON.stringify({ status: document.getElementById("new-registration-status").value, reason }) });
            toast("Registration status updated."); await render(); await showRegistration(id);
          } catch (error) { toast(error.message, true); }
        });
        document.getElementById("revoke-registration-qr")?.addEventListener("click", async () => {
          const reason = (prompt("Reason for revoking this QR pass:") || "").trim();
          if (reason.length < 3) { toast("A reason of at least 3 characters is required.", true); return; }
          try { await api(`/registrations/${id}/qr/revoke?reason=${encodeURIComponent(reason)}`, { method: "POST" }); toast("QR pass revoked."); await render(); await showRegistration(id); }
          catch (error) { toast(error.message, true); }
        });
        document.getElementById("reissue-registration-qr")?.addEventListener("click", async () => {
          try { await api(`/registrations/${id}/qr/reissue`, { method: "POST" }); toast("New QR pass issued; previous token invalidated."); await render(); await showRegistration(id); }
          catch (error) { toast(error.message, true); }
        });
      } catch (error) { toast(error.message, true); }
    };
    document.getElementById("registration-search-button").addEventListener("click", render);
    await render();
    if (registrationKey) await showRegistration(decodeURIComponent(registrationKey));
  }

  async function loadBiometrics() {
    shell("biometric-verifications", `${pageHeading("Biometric verification queue", "Review result metadata only. This panel does not collect or display face images.")}
      <section class="panel"><div class="panel-body toolbar"><input id="bio-search" placeholder="Verification ID or participant ID"><select id="bio-status"><option value="">All results</option><option value="passed">Passed</option><option value="failed">Failed / incomplete</option></select><button class="btn btn-primary" id="bio-search-button">Search</button></div><div id="bio-table"></div></section>`);
    const render = async () => {
      try {
        const q = document.getElementById("bio-search").value.trim();
        const records = await api(`/biometric-verifications${q ? `?q=${encodeURIComponent(q)}` : ""}`);
        const statusFilter = document.getElementById("bio-status").value;
        const filtered = records.filter((row) => !statusFilter || (statusFilter === "passed" ? row.face_verified && row.liveness_verified && row.pad_verified : !(row.face_verified && row.liveness_verified && row.pad_verified)));
        document.getElementById("bio-table").innerHTML = table(["Verification ID", "Participant", "Provider reference", "Face", "Liveness", "PAD", "Consent ref", "Verified", "Actions"], filtered.map((row) => `<tr><td>${escapeHtml(row.verification_id)}</td><td>${escapeHtml(row.participant_id)}</td><td>${escapeHtml(row.provider_reference)}</td><td>${statusPill(row.face_verified ? "passed" : "failed")}</td><td>${statusPill(row.liveness_verified ? "passed" : "failed")}</td><td>${statusPill(row.pad_verified ? "passed" : "failed")}</td><td>${escapeHtml(row.consent_id)}</td><td>${escapeHtml(formatDate(row.verified_at))}</td><td><div class="inline-actions"><button class="btn" data-bio-review="${escapeHtml(row.verification_id)}" data-decision="approve">Approve</button><button class="btn btn-danger" data-bio-review="${escapeHtml(row.verification_id)}" data-decision="reject">Reject</button></div></td></tr>`));
        document.querySelectorAll("[data-bio-review]").forEach((button) => button.addEventListener("click", async () => {
          const reason = (prompt(`Reason for ${button.dataset.decision}:`) || "").trim();
          if (reason.length < 3) { toast("A review reason of at least 3 characters is required.", true); return; }
          let registrationId = null;
          const registrationInput = prompt("Associated registration numeric ID (leave blank if none):");
          if (registrationInput) {
            registrationId = Number(registrationInput);
            if (!Number.isInteger(registrationId) || registrationId < 1) { toast("Registration ID must be a positive integer.", true); return; }
          }
          try {
            await api(`/biometric-verifications/${encodeURIComponent(button.dataset.bioReview)}/review`, { method: "POST", body: JSON.stringify({ decision: button.dataset.decision, reason, registration_id: registrationId }) });
            toast("Biometric review recorded."); await render();
          } catch (error) { toast(error.message, true); }
        }));
      } catch (error) { toast(error.message, true); }
    };
    document.getElementById("bio-search-button").addEventListener("click", render);
    await render();
  }

  async function loadQrPasses() {
    shell("qr-passes", `${pageHeading("QR pass management", "Search active and revoked passes; replace or revoke tokens through audited backend operations.")}
      <section class="panel"><div class="panel-body toolbar"><input id="pass-search" placeholder="Registration, participant, or event ID"><button class="btn btn-primary" id="pass-search-button">Search passes</button></div><div id="pass-table"></div></section>`);
    const render = async () => {
      try {
        const q = document.getElementById("pass-search").value.trim();
        const passes = await api(`/qr-passes${q ? `?q=${encodeURIComponent(q)}` : ""}`);
        document.getElementById("pass-table").innerHTML = table(["Registration", "Participant", "Event", "Status", "Pass status", "Token", "Usage", "Action"], passes.map((item) => `<tr><td>${escapeHtml(item.registration_code)}</td><td>${escapeHtml(item.full_name)}<small class="muted" style="display:block">${escapeHtml(item.participant_id)}</small></td><td>${escapeHtml(item.event_id)}</td><td>${statusPill(item.status)}</td><td>${statusPill(item.revoked ? "revoked" : "active")}</td><td>${item.qr_token ? `<code>${escapeHtml(item.qr_token)}</code>` : "—"}</td><td>${escapeHtml(formatDate(item.checked_in_at))}</td><td><div class="inline-actions">${item.revoked ? `<button class="btn" data-reissue="${item.registration_id}">Reissue</button>` : `<button class="btn" data-view-qr="${item.registration_id}">View / download</button><button class="btn btn-danger" data-revoke="${item.registration_id}">Revoke</button>`}</div></td></tr>`));
        document.querySelectorAll("[data-view-qr]").forEach((button) => button.addEventListener("click", () => {
          window.open(`/api/registrations/${button.dataset.viewQr}/qr`, "_blank", "noopener");
        }));
        document.querySelectorAll("[data-revoke]").forEach((button) => button.addEventListener("click", async () => {
          const reason = prompt("Reason for revoking this pass:") || "";
          try { await api(`/registrations/${button.dataset.revoke}/qr/revoke?reason=${encodeURIComponent(reason)}`, { method: "POST" }); toast("Pass revoked."); await render(); }
          catch (error) { toast(error.message, true); }
        }));
        document.querySelectorAll("[data-reissue]").forEach((button) => button.addEventListener("click", async () => {
          try { await api(`/registrations/${button.dataset.reissue}/qr/reissue`, { method: "POST" }); toast("Pass reissued with a new token."); await render(); }
          catch (error) { toast(error.message, true); }
        }));
      } catch (error) { toast(error.message, true); }
    };
    document.getElementById("pass-search-button").addEventListener("click", render);
    await render();
  }

  async function loadCheckIn() {
    const events = await api("/events");
    shell("check-in", `${pageHeading("Gate check-in", "Check the pass at the gate and record the result. Face verification is required unless the operator has a documented override.")}
      <div class="split"><section class="panel"><div class="panel-head"><h3>Validate entry</h3></div><form id="checkin-form" class="panel-body form-grid">
        <label>Event<select name="event_id" required><option value="">Select event</option>${events.map((event) => `<option value="${escapeHtml(event.event_id)}">${escapeHtml(event.event_name)}</option>`).join("")}</select></label>
        <label>Gate / entry point<input name="gate" required value="main"></label>
        <label class="span-2">QR token<input name="qr_token" placeholder="Scan or enter QR token"></label>
        <div class="span-2 camera-box"><video id="gate-camera" playsinline muted hidden></video><div class="toolbar"><button class="btn" id="start-gate-camera" type="button">Start face camera</button><button class="btn" id="capture-gate-face" type="button" disabled>Capture face</button><span class="muted" id="gate-camera-state">Face capture is required unless an authorized override is recorded.</span></div><canvas id="gate-face-canvas" hidden></canvas><input id="gate-face-payload" type="hidden"></div>
        <label class="span-2"><span><input type="checkbox" name="skip_face" value="true"> Authorized manual check-in override (skip face match)</span></label>
        <label class="span-2">Manual override reason<input name="override_reason" placeholder="Required only when the manual override is selected" maxlength="500"></label>
        <button class="btn btn-primary span-2" type="submit">Validate and check in</button>
      </form></section>
      <section class="panel"><div class="panel-head"><h3>Entry result</h3></div><div class="panel-body" id="checkin-result"><span class="muted">Awaiting a pass scan.</span></div></section></div>
      <div class="notice">QR validation and registration checks run on the backend. The current backend does not record distinct gate-operator authorization beyond the signed-in admin role. Manual override usage is recorded in the admin audit log.</div>`);
    let gateStream = null;
    document.getElementById("start-gate-camera").addEventListener("click", async () => {
      const video = document.getElementById("gate-camera");
      const stateLabel = document.getElementById("gate-camera-state");
      if (!navigator.mediaDevices?.getUserMedia) { stateLabel.textContent = "Camera access is not available in this browser."; return; }
      try {
        gateStream?.getTracks().forEach((track) => track.stop());
        gateStream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: "user", width: { ideal: 640 } } });
        video.srcObject = gateStream;
        video.hidden = false;
        await video.play();
        document.getElementById("capture-gate-face").disabled = false;
        stateLabel.textContent = "Camera ready. Capture the person at the gate.";
      } catch (error) { stateLabel.textContent = `Could not start camera: ${error.message}`; }
    });
    document.getElementById("capture-gate-face").addEventListener("click", () => {
      const video = document.getElementById("gate-camera");
      if (!video.videoWidth) { toast("Wait for the camera preview before capture.", true); return; }
      const canvas = document.getElementById("gate-face-canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      document.getElementById("gate-face-payload").value = canvas.toDataURL("image/jpeg", 0.85);
      document.getElementById("gate-camera-state").textContent = "Face capture ready for verification.";
      gateStream?.getTracks().forEach((track) => track.stop());
      gateStream = null;
      video.srcObject = null;
      video.hidden = true;
      document.getElementById("capture-gate-face").disabled = true;
    });
    document.getElementById("checkin-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      const skipFace = data.get("skip_face") === "true";
      if (skipFace && !confirm("Confirm authorized manual override: this check-in will skip face verification.")) return;
      const overrideReason = String(data.get("override_reason") || "").trim();
      if (skipFace && overrideReason.length < 3) { toast("Enter a reason for the manual override.", true); return; }
      const facePayload = document.getElementById("gate-face-payload").value;
      if (!skipFace && !facePayload) { toast("Capture the gate face or use an authorized manual override.", true); return; }
      try {
        const result = await api("/check-in", { method: "POST", body: JSON.stringify({ event_id: data.get("event_id"), gate: data.get("gate"), qr_token: data.get("qr_token"), face_payload: facePayload || "", skip_face: skipFace, override_reason: skipFace ? overrideReason : null }) });
        document.getElementById("checkin-result").innerHTML = `<div class="notice success-notice">${escapeHtml(result.message)}</div><div class="detail-grid" style="margin-top:.8rem">${detailItem("Participant", result.full_name)}${detailItem("Registration", result.registration_id)}${detailItem("Participant ID", result.participant_id)}${detailItem("Event", result.event_id)}${detailItem("Checked in", formatDate(result.checked_in_at))}</div>`;
      } catch (error) {
        document.getElementById("checkin-result").innerHTML = `<div class="notice error-notice">${escapeHtml(error.message)}</div>`;
      }
    });
  }

  async function loadReports() {
    const report = await api("/reports/summary");
    const capacity = report.capacity_utilization || [];
    const capRows = capacity.map((item) => `<tr><td>${escapeHtml(item.event_name)}</td><td>${escapeHtml(item.registered)}</td><td>${escapeHtml(item.capacity)}</td><td>${escapeHtml(item.utilization_percent)}%</td></tr>`);
    const regRows = Object.entries(report.registrations_by_status || {}).map(([key, value]) => `<tr><td>${statusPill(key)}</td><td>${escapeHtml(value)}</td></tr>`);
    const eventRows = Object.entries(report.events_by_status || {}).map(([key, value]) => `<tr><td>${statusPill(key)}</td><td>${escapeHtml(value)}</td></tr>`);
    shell("reports", `${pageHeading("Reports and analytics", "Summary is calculated from live records. Download CSV snapshots for the listed data.")}
      <div class="cards">${metric("Biometric pass rate", `${report.verification_pass_rate}%`, "All recorded biometric verifications")}${metric("Events reported", capacity.length, "Capacity utilization rows")}</div>
      <div class="split"><section class="panel"><div class="panel-head"><h3>Capacity utilization</h3><button class="btn" id="export-capacity">Export CSV</button></div>${table(["Event", "Registered", "Capacity", "Utilization"], capRows)}</section>
      <section class="panel"><div class="panel-head"><h3>Registrations by status</h3><button class="btn" id="export-status">Export CSV</button></div>${table(["Status", "Count"], regRows)}</section></div>
      <section class="panel"><div class="panel-head"><h3>Events by status</h3></div>${table(["Status", "Count"], eventRows)}</section>`);
    document.getElementById("export-capacity").addEventListener("click", () => downloadCsv("capacity-utilization.csv", ["event_name","registered","capacity","utilization_percent"], capacity));
    document.getElementById("export-status").addEventListener("click", () => downloadCsv("registration-status.csv", ["status","count"], Object.entries(report.registrations_by_status || {}).map(([status, count]) => ({ status, count }))));
  }

  function downloadCsv(filename, columns, rows) {
    const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const content = [columns.map(quote).join(","), ...rows.map((row) => columns.map((column) => quote(row[column])).join(","))].join("\r\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function loadAuditLogs() {
    const records = await api("/audit-logs?limit=200");
    const rows = records.map((row) => `<tr><td>${escapeHtml(formatDate(row.created_at))}</td><td>${escapeHtml(row.admin_username)}</td><td>${escapeHtml(row.action)}</td><td>${escapeHtml(row.entity_type)} · ${escapeHtml(row.entity_id)}</td><td>${escapeHtml(row.details)}</td></tr>`);
    shell("audit-logs", `${pageHeading("Administrative audit log", "Recent administrative actions recorded by the backend.")}
      <section class="panel">${table(["Time", "Admin", "Action", "Record", "Details"], rows)}</section>`);
  }

  async function loadSettings() {
    const settings = await api("/settings");
    const rows = Object.entries(settings).map(([key, value]) => `<tr><td>${escapeHtml(key.replaceAll("_", " "))}</td><td>${escapeHtml(typeof value === "boolean" ? value ? "Enabled" : "Disabled" : value)}</td></tr>`);
    shell("settings", `${pageHeading("System settings", "Read-only integration values exposed by the backend. Secrets are never returned to the browser.")}
      <div class="notice">Provider settings are displayed only. This backend does not expose authenticated APIs to modify provider credentials, MFA policy, retention, consent versions, or event-wide policy settings.</div>
      <section class="panel" style="margin-top:1rem">${table(["Setting", "Current value"], rows)}</section>`);
  }

  async function loadUsers() {
    const records = await api("/users");
    const rows = records.map((item) => `<tr><td>${escapeHtml(item.username)}</td><td>${escapeHtml(item.email)}</td><td>${escapeHtml(item.role.replaceAll("_", " "))}</td><td>${statusPill(item.is_active ? "active" : "disabled")}</td><td>${item.mfa_enabled ? "Enabled" : "Disabled"}</td><td>${escapeHtml(formatDate(item.last_login_at))}</td></tr>`);
    shell("users", `${pageHeading("Administrator accounts", "Review admin accounts and assign a built-in role.", `<button class="btn btn-primary" id="new-admin-user">＋ Add admin</button>`)}
      <div id="admin-user-form"></div><section class="panel">${table(["Username", "Email", "Role", "Status", "MFA", "Last login"], rows)}</section>
      <div class="notice">New accounts require a password of at least 12 characters. MFA enrollment and account editing are not exposed by the current backend.</div>`);
    document.getElementById("new-admin-user").addEventListener("click", () => {
      const host = document.getElementById("admin-user-form");
      host.innerHTML = `<section class="panel"><div class="panel-head"><h3>Create administrator</h3><button class="btn btn-quiet" id="cancel-new-admin">Close</button></div>
        <form id="new-admin-form" class="panel-body form-grid"><label>Username<input name="username" required minlength="3" maxlength="100"></label><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" minlength="12" required autocomplete="new-password"></label><label>Role<select name="role">${["event_manager","registration_manager","biometric_reviewer","gate_operator","auditor","super_admin"].map((role) => `<option value="${role}">${role.replaceAll("_"," ")}</option>`).join("")}</select></label><div class="span-2"><button class="btn btn-primary" type="submit">Create account</button></div></form></section>`;
      document.getElementById("cancel-new-admin").addEventListener("click", () => { host.innerHTML = ""; });
      document.getElementById("new-admin-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = Object.fromEntries(new FormData(event.currentTarget));
        try { await api("/users", { method: "POST", body: JSON.stringify(data) }); toast("Administrator account created."); await loadUsers(); }
        catch (error) { toast(error.message, true); }
      });
    });
  }

  async function route() {
    if (!token()) { await loginPage(); return; }
    try {
      user = JSON.parse(sessionStorage.getItem(userKey) || "null");
      if (!user) {
        user = await api("/me");
        sessionStorage.setItem(userKey, JSON.stringify(user));
      }
      const section = currentSection();
      if (section === "login") { location.replace("/admin/dashboard"); return; }
      if (!sections[section]) { location.replace("/admin/dashboard"); return; }
      if (!allowedSections().includes(section)) {
        root.innerHTML = `<section class="login-screen"><div class="login-card"><h1>Access denied</h1><p>Your admin role does not have access to this area.</p><a class="btn" href="/admin/dashboard">Return to dashboard</a></div></section>`;
        return;
      }
      if (section === "dashboard") await loadDashboard();
      else if (section === "events") await loadEvents(location.pathname.replace(/^\/admin\/events\/?/, "") === "create");
      else if (section === "participants") await loadParticipants(location.pathname.replace(/^\/admin\/participants\/?/, ""));
      else if (section === "registrations") await loadRegistrations(location.pathname.replace(/^\/admin\/registrations\/?/, ""));
      else if (section === "biometric-verifications") await loadBiometrics();
      else if (section === "qr-passes") await loadQrPasses();
      else if (section === "check-in") await loadCheckIn();
      else if (section === "reports") await loadReports();
      else if (section === "audit-logs") await loadAuditLogs();
      else if (section === "settings") await loadSettings();
      else if (section === "users") await loadUsers();
    } catch (error) {
      if (token()) root.innerHTML = `<section class="login-screen"><div class="login-card"><h1>Admin panel error</h1><p class="notice error-notice">${escapeHtml(error.message)}</p><button class="btn" id="retry-admin">Retry</button><button class="btn btn-quiet" id="admin-signout">Sign out</button></div></section>`;
      document.getElementById("retry-admin")?.addEventListener("click", route);
      document.getElementById("admin-signout")?.addEventListener("click", () => logout());
    }
  }

  route();
})();
