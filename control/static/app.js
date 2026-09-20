const state = {
  token: sessionStorage.getItem("paas_token") || "",
  user: sessionStorage.getItem("paas_user") || "",
  role: sessionStorage.getItem("paas_role") || "user",
  loginRole: "user",
  tab: "board",
  accounts: [],
  history: [],
  adminWorkerId: "",
  adminBoard: null,
  adminUser: "",
  adminUserDetail: null,
  adminUserJobTab: "submitted",
  workerAccounts: [],
  lastAuthError: "",
  workers: [],
  jobs: [],
  selectedJob: null,
  logAfter: 0,
  scan: null,
  verdicts: [],
  envId: "",
  authMode: "login",
  shareWorkerId: "",
  shareData: null,
  submitShare: null,
  sharePickId: "",
  displayFile: "",
  outputSig: "",
  sharePickSlot: "",
  place: "auto",
  placement: null,
};

const $ = (id) => document.getElementById(id);

function localizeError(msg) {
  const raw = String(msg || "");
  if (raw.includes("No Worker can run this")) return t("no_place");
  if (raw.includes("not accepting jobs")) return t("err_not_accepting");
  if (raw.includes("Installs & file changes")) return t("err_installs_off");
  if (raw.includes("Remote CPU/GPU limits")) return t("err_limits_off");
  if (raw === "cannot_block_admin") return t("cannot_block_admin");
  if (raw === "grant_required") return t("grant_required");
  if (raw === "too_large") return t("too_large");
  if (raw === "blocked") return t("blocked");
  if (raw === "cancelled") return t("cancelled");
  return raw;
}

function t(key, vars) {
  let s = I18N[key] || key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  }
  return s;
}

function applyI18n() {
  document.documentElement.lang = "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  applyRoleChrome();
  syncAuthForm();
  renderShare();
  renderAccounts();
  renderAdminBoard();
  renderAdminUser();
  if (state.lastAuthError && $("login-error") && !$("login-error").hidden) {
    $("login-error").textContent = authError(state.lastAuthError);
  }
  if ($("login") && !$("login").hidden) fillAccess();
  setFileStatus();
  fillSubmitShareSelects();
  syncPlace();
  if (state.workers.length) {
    renderWorkers();
    renderJobs();
    renderEnvs();
  }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let res;
  try {
    res = await fetch(path, { ...options, headers });
  } catch (err) {
    if (err && err.name === "AbortError") throw new Error("cancelled");
    throw err;
  }
  if (res.status === 401 && !path.startsWith("/api/v1/auth/")) {
    state.token = "";
    state.role = "user";
    sessionStorage.removeItem("paas_token");
    sessionStorage.removeItem("paas_role");
    showLogin();
    throw new Error(t("not_logged_in"));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg || d).join("; ") : (detail || res.statusText);
    throw new Error(localizeError(msg));
  }
  return data;
}

function showLogin() {
  $("login").hidden = false;
  $("app").hidden = true;
  fillAccess();
}

function fillAccess() {
  const box = $("access");
  if (!box) return;
  fetch("/api/v1/info")
    .then((res) => res.json())
    .then((info) => {
      const rec = info.recommended;
      const here = window.location.origin;
      const lines = [];
      if (rec && rec.url && rec.url.replace(/\/$/, "") !== here) {
        lines.push(`<div>${t("phone_use")} <a href="${rec.url}">${rec.url}</a></div>`);
      }
      box.hidden = !lines.length;
      box.innerHTML = lines.join("");
    })
    .catch(() => {
      box.hidden = true;
    });
}

function applyRoleChrome() {
  const admin = state.role === "admin";
  document.querySelectorAll(".admin-only").forEach((el) => {
    el.hidden = !admin;
  });
  document.querySelectorAll(".user-only").forEach((el) => {
    el.hidden = admin;
  });
}

function showApp() {
  $("login").hidden = true;
  $("app").hidden = false;
  applyRoleChrome();
  if ($("who")) {
    const label = state.role === "admin" ? "Admin" : "User";
    $("who").textContent = state.user ? `${label} ${groupDigits(state.user, 2)}` : label;
  }
  const logoutBtn = $("logout-btn");
  if (logoutBtn && !logoutBtn.disabled) logoutBtn.textContent = t("logout");
}

$("logout-btn").addEventListener("click", async () => {
  const btn = $("logout-btn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = t("logout_wait");
  try {
    let done = false;
    for (let i = 0; i < 3 && !done; i++) {
      try {
        await api("/api/v1/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        done = true;
      } catch (err) {
        if (err.message !== "still_running" || i === 2) throw err;
      }
    }
    state.token = "";
    state.user = "";
    sessionStorage.removeItem("paas_token");
    sessionStorage.removeItem("paas_user");
    sessionStorage.removeItem("paas_role");
    state.role = "user";
    state.adminWorkerId = "";
    state.adminBoard = null;
    btn.disabled = false;
    btn.textContent = t("logout");
    showLogin();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = t("logout");
    alert(err.message === "still_running" ? t("logout_fail") : err.message);
  }
});

function onlyDigits(value) {
  return String(value || "").replace(/\D/g, "");
}

function groupDigits(value, groups) {
  const digits = onlyDigits(value).slice(0, groups * 4);
  return digits.match(/.{1,4}/g)?.join(" ") || "";
}

function authError(code) {
  const raw = String(code || "").trim();
  let key = raw;
  if (/尚未激活|还没激活|還沒啟動|未激活|enter .dev/i.test(raw)) key = "platform_off";
  else if (raw === "重名" || raw === "duplicate") key = "label_taken";
  const map = {
    unregistered: t("unregistered"),
    bad_password: t("bad_password"),
    username_taken: t("username_taken"),
    bad_username: t("bad_username"),
    bad_password_format: t("bad_pw_format"),
    bad_pw_format: t("bad_pw_format"),
    already_logged_in: t("already_logged_in"),
    platform_off: t("platform_off"),
    label_taken: t("no_worker"),
    cannot_block_admin: t("cannot_block_admin"),
  };
  return map[key] || raw;
}

function setLoginRole(role) {
  state.loginRole = role;
  if (role === "admin") state.authMode = "login";
  $("login-error").hidden = true;
  $("login-ok").hidden = true;
  syncAuthForm();
}

function syncAuthForm() {
  const role = state.loginRole || "user";
  ["user", "worker", "admin"].forEach((id) => {
    const btn = $(`role-${id}`);
    if (btn) btn.classList.toggle("active", role === id);
  });
  const userTabs = $("user-tabs");
  const userFields = $("user-fields");
  const workerFields = $("worker-fields");
  const submit = $("auth-submit");
  if (userTabs) userTabs.hidden = role === "admin";
  if (userFields) userFields.hidden = role === "worker" && state.authMode !== "register";
  if (workerFields) workerFields.hidden = !(role === "worker" && state.authMode === "login");
  const loginTab = $("tab-login");
  const regTab = $("tab-register");
  if (loginTab) loginTab.classList.toggle("active", state.authMode === "login");
  if (regTab) regTab.classList.toggle("active", state.authMode === "register");
  if (submit) {
    const registering = (role === "user" || role === "worker") && state.authMode === "register";
    if (role === "worker" && state.authMode === "login") {
      submit.hidden = true;
      submit.disabled = true;
    } else {
      submit.hidden = false;
      submit.textContent = registering ? t("apply") : t("enter");
      const userOk = onlyDigits($("username") && $("username").value).length === 8;
      const pwOk = onlyDigits($("password") && $("password").value).length === 16;
      submit.disabled = !(userOk && pwOk);
    }
  }
}

function bindGroupedInput(el, groups) {
  if (!el) return;
  el.addEventListener("input", () => {
    const start = el.selectionStart;
    const before = onlyDigits(el.value.slice(0, start)).length;
    el.value = groupDigits(el.value, groups);
    let pos = 0;
    let seen = 0;
    while (pos < el.value.length && seen < before) {
      if (/\d/.test(el.value[pos])) seen += 1;
      pos += 1;
    }
    el.setSelectionRange(pos, pos);
    syncAuthForm();
  });
}

bindGroupedInput($("username"), 2);
bindGroupedInput($("password"), 4);
$("role-user")?.addEventListener("click", () => setLoginRole("user"));
$("role-worker")?.addEventListener("click", () => setLoginRole("worker"));
$("role-admin")?.addEventListener("click", () => setLoginRole("admin"));
$("tab-login").addEventListener("click", () => {
  state.authMode = "login";
  $("login-error").hidden = true;
  $("login-ok").hidden = true;
  syncAuthForm();
});
$("tab-register").addEventListener("click", () => {
  state.authMode = "register";
  $("login-error").hidden = true;
  $("login-ok").hidden = true;
  syncAuthForm();
});
syncAuthForm();

function rememberSession(data) {
  state.token = data.token;
  state.user = data.user || "";
  state.role = data.role || "user";
  sessionStorage.setItem("paas_token", data.token);
  sessionStorage.setItem("paas_user", state.user);
  sessionStorage.setItem("paas_role", state.role);
}

function consumeResume() {
  const raw = (location.hash || "").replace(/^#/, "");
  const params = new URLSearchParams(raw);
  const token = params.get("resume");
  if (!token) return;
  state.token = token;
  sessionStorage.setItem("paas_token", token);
  history.replaceState(null, "", location.pathname + location.search);
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("login-error").hidden = true;
  $("login-ok").hidden = true;
  if (state.loginRole === "worker" && state.authMode !== "register") return;
  const username = onlyDigits($("username").value);
  const password = onlyDigits($("password").value);
  if (username.length !== 8 || password.length !== 16) return;
  try {
    if ((state.loginRole === "user" || state.loginRole === "worker") && state.authMode === "register") {
      await api("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: state.loginRole, username, password }),
      });
      $("login-ok").hidden = false;
      $("login-ok").textContent = t("applied");
      $("auth-submit").disabled = true;
      setTimeout(() => {
        state.authMode = "login";
        $("login-ok").hidden = true;
        syncAuthForm();
      }, 2000);
      return;
    }
    const data = await api("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: state.loginRole, username, password }),
    });
    rememberSession(data);
    showApp();
    refresh();
  } catch (err) {
    state.lastAuthError = err.message;
    $("login-error").hidden = false;
    $("login-error").textContent = authError(err.message);
  }
});

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.tab = btn.dataset.tab;
    document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab").forEach((el) => {
      el.hidden = el.id !== `tab-${state.tab}`;
    });
    if (state.tab === "submit") {
      refreshSubmitShare().catch(() => {});
      renderEnvs();
      scheduleScan();
    }
    if (state.tab === "shared") refreshShare().catch(() => {});
  });
});

function isZipName(name) {
  return String(name || "").toLowerCase().endsWith(".zip");
}

function currentShareFile() {
  if (!state.sharePickId || !state.submitShare) return null;
  return (state.submitShare.files || []).find((f) => f.id === state.sharePickId) || null;
}

function setFileStatus() {
  const single = $("single-file") && $("single-file").files[0];
  const zip = $("project-zip") && $("project-zip").files[0];
  const share = currentShareFile();
  const shareSingle = state.sharePickSlot === "single" && share;
  const shareZip = state.sharePickSlot === "zip" && share;
  if ($("clear-single")) $("clear-single").hidden = !single && !shareSingle;
  if ($("clear-zip")) $("clear-zip").hidden = !zip && !shareZip;
  if ($("single-status")) {
    $("single-status").textContent = shareSingle
      ? `${t("selected")}: ${share.name}`
      : single
        ? `${t("selected")}: ${single.name}`
        : t("no_file");
  }
  if ($("zip-status")) {
    $("zip-status").textContent = shareZip
      ? `${t("selected")}: ${share.name}`
      : zip
        ? `${t("selected")}: ${zip.name}`
        : t("no_file");
  }
}

function clearSharePicks() {
  state.sharePickId = "";
  state.sharePickSlot = "";
  if ($("share-single")) $("share-single").value = "";
  if ($("share-zip")) $("share-zip").value = "";
}

function clearAllFiles() {
  if ($("single-file")) $("single-file").value = "";
  if ($("project-zip")) $("project-zip").value = "";
  clearSharePicks();
  state.scan = null;
  state.verdicts = [];
  state.envId = "";
  setFileStatus();
  renderEnvs();
}

function onFilePicked(which) {
  if (which === "single") $("project-zip").value = "";
  if (which === "zip") $("single-file").value = "";
  clearSharePicks();
  setFileStatus();
  scheduleScan();
}

function onShareSlot(slot) {
  const sel = $(slot === "zip" ? "share-zip" : "share-single");
  if ($("single-file")) $("single-file").value = "";
  if ($("project-zip")) $("project-zip").value = "";
  if (slot === "single" && $("share-zip")) $("share-zip").value = "";
  if (slot === "zip" && $("share-single")) $("share-single").value = "";
  state.sharePickId = sel && sel.value || "";
  state.sharePickSlot = state.sharePickId ? slot : "";
  setFileStatus();
  scheduleScan();
}

$("single-file").addEventListener("change", () => onFilePicked("single"));
$("single-file").addEventListener("input", () => onFilePicked("single"));
$("project-zip").addEventListener("change", () => onFilePicked("zip"));
$("project-zip").addEventListener("input", () => onFilePicked("zip"));
$("clear-single").addEventListener("click", clearAllFiles);
$("clear-zip").addEventListener("click", clearAllFiles);

$("share-single")?.addEventListener("change", () => onShareSlot("single"));
$("share-zip")?.addEventListener("change", () => onShareSlot("zip"));

$("worker-select").addEventListener("change", () => {
  state.envId = "";
  clearSharePicks();
  renderPicked();
  renderEnvs();
  refreshSubmitShare().then(() => scheduleScan()).catch(() => scheduleScan());
});
$("place-auto")?.addEventListener("click", () => setPlace("auto"));
$("place-manual")?.addEventListener("click", () => setPlace("manual"));
$("submit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("submit-error").hidden = true;
  const auto = state.place === "auto";
  const workerId = $("worker-select").value;
  if (!auto && !workerId) {
    $("submit-error").hidden = false;
    $("submit-error").textContent = t("pick_worker");
    return;
  }
  const single = $("single-file").files[0];
  const zip = $("project-zip").files[0];
  const shareId = auto ? "" : state.sharePickId;
  if ((single && zip) || (single && shareId) || (zip && shareId)) {
    $("submit-error").hidden = false;
    $("submit-error").textContent = t("both_slots");
    return;
  }
  const body = new FormData();
  body.append("place", auto ? "auto" : "manual");
  if (!auto) body.append("worker_id", workerId);
  try {
    if (shareId) {
      body.append("share_file_id", shareId);
      body.append("kind", state.sharePickSlot === "zip" ? "zip" : "single");
    } else if (single) {
      body.append("artifact", single);
      body.append("kind", "single");
    } else if (zip) {
      body.append("artifact", zip);
      body.append("kind", "zip");
    } else {
      throw new Error(t("need_upload"));
    }
    if (!auto && !state.envId) throw new Error(t("pick_env"));
    if (state.envId) body.append("env_id", state.envId);
    const data = await api("/api/v1/jobs", { method: "POST", body });
    state.selectedJob = data.job.id;
    state.logAfter = 0;
    $("logs").textContent = "";
    document.querySelector('[data-tab="jobs"]').click();
    await refreshJobs();
  } catch (err) {
    $("submit-error").hidden = false;
    $("submit-error").textContent = err.message;
  }
});

function setPlace(mode) {
  state.place = mode === "manual" ? "manual" : "auto";
  if (state.place === "auto") {
    state.sharePickId = "";
    state.sharePickSlot = "";
    if ($("share-single")) $("share-single").value = "";
    if ($("share-zip")) $("share-zip").value = "";
  }
  syncPlace();
  renderPicked();
  renderEnvs();
  refreshSubmitShare().then(() => scheduleScan()).catch(() => scheduleScan());
}

function syncPlace() {
  const auto = state.place === "auto";
  if ($("place-auto")) $("place-auto").className = "ghost" + (auto ? " active" : "");
  if ($("place-manual")) $("place-manual").className = "ghost" + (auto ? "" : " active");
  if ($("manual-worker")) $("manual-worker").hidden = auto;
  if ($("share-single")) $("share-single").hidden = auto;
  if ($("share-zip")) $("share-zip").hidden = auto;
}

function renderWorkers() {
  const root = $("workers");
  root.innerHTML = "";
  $("worker-count").textContent = `${state.workers.length} ${t("machines")}`.trim();
  const select = $("worker-select");
  const prev = select.value;
  select.innerHTML = "";
  for (const w of state.workers) {
    const card = document.createElement("div");
    card.className = "card" + (state.role === "admin" ? " pickable" : "") + (state.adminWorkerId === w.id ? " picked" : "");
    const status = !w.online ? [t("offline"), "bad"] : w.locks.run_open ? [t("accepting"), "ok"] : [t("run_closed"), "warn"];
    card.innerHTML = `
      <h3>${escapeHtml(w.name)}</h3>
      <div>
        <span class="pill ${status[1]}">${status[0]}</span>
        <span class="pill">${escapeHtml(w.os)}/${escapeHtml(w.arch)}</span>
        <span class="pill">${w.has_docker ? "Docker" : "native"}</span>
        <span class="pill">${w.locks.security_open ? t("security_on") : t("security_off")}</span>
        <span class="pill">${w.locks.admin_open ? t("admin_on") : t("admin_off")}</span>
        ${w.blocked_count ? `<span class="pill warn">${t("blocked_n", { n: w.blocked_count })}</span>` : ""}
      </div>
      <div class="bar" title="CPU"><span style="width:${Math.min(100, w.cpu_percent)}%"></span></div>
      <div class="muted">CPU ${w.cpu_percent.toFixed(0)}% · ${w.memory_percent.toFixed(0)}% · ${formatBytes(w.bytes_sent)}↑ ${formatBytes(w.bytes_recv)}↓</div>
      ${w.current_user ? `<div class="muted">${escapeHtml(w.current_user)} · ${Number(w.job_cpu_percent || 0).toFixed(0)}% CPU / ${w.job_proc_count || 0} process</div>` : ""}
      ${state.role === "admin" && w.current_job_id ? `<div class="job-actions"><button type="button" class="ghost danger tiny" data-wstop="${w.current_job_id}">${t("stop")}</button></div>` : ""}
      <div class="muted">${(w.runtimes || []).join(", ") || t("no_runtime")}</div>
    `;
    if (state.role === "admin") {
      card.addEventListener("click", (e) => {
        const btn = e.target instanceof HTMLElement ? e.target.closest("[data-wstop]") : null;
        if (btn) return;
        state.adminWorkerId = w.id;
        renderWorkers();
        refreshAdminBoard().catch(() => {});
      });
      card.querySelector("[data-wstop]")?.addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          await api(`/api/v1/admin/workers/${w.id}/jobs/${w.current_job_id}/stop`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          });
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      });
    }
    root.appendChild(card);
    const opt = document.createElement("option");
    opt.value = w.id;
    const load = !w.online ? t("offline") : w.current_job_id ? t("busy") : t("idle");
    opt.textContent = `${w.name} · ${load}`;
    select.appendChild(opt);
  }
  if (state.role === "admin") {
    for (const acc of state.workerAccounts || []) {
      if (state.workers.some((w) => w.id === acc.username)) continue;
      const card = document.createElement("div");
      card.className = "card pickable acct " + (acc.online ? "online" : "offline") + (state.adminWorkerId === acc.username ? " picked" : "");
      const st = acc.status === "approved" ? [t("acct_approved"), "ok"] : [t("acct_pending"), "warn"];
      card.innerHTML = `
        <h3>${escapeHtml(groupDigits(acc.username, 2))}</h3>
        <div>
          <span class="pill">${t("role_worker")}</span>
          <span class="pill ${st[1]}">${st[0]}</span>
        </div>
      `;
      card.addEventListener("click", () => {
        state.adminWorkerId = acc.username;
        renderWorkers();
        refreshAdminBoard().catch(() => {});
      });
      root.appendChild(card);
    }
  }
  if ([...select.options].some((o) => o.value === prev)) select.value = prev;
  fillShareWorkers();
  renderPicked();
  renderEnvs();
  refreshSubmitShare().catch(() => {});
}

function fillShareSlotSelect(sel, files, slot) {
  if (!sel) return;
  const keep = state.sharePickSlot === slot ? state.sharePickId : "";
  sel.innerHTML = "";
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = t("share_pick");
  sel.appendChild(blank);
  const addGroup = (label, list) => {
    if (!list.length) return;
    const group = document.createElement("optgroup");
    group.label = label;
    for (const file of list) {
      const opt = document.createElement("option");
      opt.value = file.id;
      opt.textContent = file.name;
      group.appendChild(opt);
    }
    sel.appendChild(group);
  };
  addGroup(t("share_open"), files.filter((f) => f.kind === "open"));
  addGroup(t("share_granted"), files.filter((f) => f.kind === "granted"));
  if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
  else if (state.sharePickSlot === slot) {
    state.sharePickId = "";
    state.sharePickSlot = "";
  }
}

function fillSubmitShareSelects() {
  const data = state.submitShare;
  const grantOk = !!(data && data.grant === "approved");
  const files = ((data && data.files) || []).filter((f) => f.kind === "open" || (f.kind === "granted" && grantOk));
  fillShareSlotSelect($("share-single"), files.filter((f) => !isZipName(f.name)), "single");
  fillShareSlotSelect($("share-zip"), files.filter((f) => isZipName(f.name)), "zip");
  setFileStatus();
}

async function refreshSubmitShare() {
  if (state.role !== "user") return;
  if (state.place === "auto") {
    state.submitShare = null;
    fillSubmitShareSelects();
    return;
  }
  const wid = $("worker-select") && $("worker-select").value;
  if (!wid) {
    state.submitShare = null;
    fillSubmitShareSelects();
    return;
  }
  state.submitShare = await api(`/api/v1/share?worker_id=${encodeURIComponent(wid)}`);
  fillSubmitShareSelects();
}

function fillShareWorkers() {
  const sel = $("share-worker");
  if (!sel) return;
  const prev = state.shareWorkerId || sel.value;
  sel.innerHTML = "";
  for (const w of state.workers) {
    const opt = document.createElement("option");
    opt.value = w.id;
    opt.textContent = w.name;
    sel.appendChild(opt);
  }
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
  else if (sel.options.length) sel.selectedIndex = 0;
  state.shareWorkerId = sel.value || "";
}

function renderPicked() {
  const box = $("picked-worker");
  const auto = state.place === "auto";
  const w = state.workers.find((x) => x.id === $("worker-select").value);
  if (auto && state.placement) {
    const hit = state.workers.find((x) => x.id === state.placement.worker_id) || w;
    const name = hit ? hit.name : state.placement.worker_name;
    const idle = hit && hit.current_job_id ? t("busy") : t("idle");
    box.innerHTML = `
      <div>${escapeHtml(name || "")} · ${escapeHtml((hit && hit.os) || "")}</div>
      <div class="muted">${t("place_system")} · ${escapeHtml(state.placement.env_label || "")} · ${idle}</div>
    `;
    return;
  }
  if (!w) {
    box.textContent = auto ? t("not_picked") : t("no_worker");
    return;
  }
  box.innerHTML = `
    <div>${escapeHtml(w.name)} · ${escapeHtml(w.os)}</div>
    <div class="muted">${t("run_open")} · ${w.locks.security_open ? t("security_on") : t("security_off")} · ${w.locks.admin_open ? t("admin_on") : t("admin_off")}</div>
      <div class="muted">${t("current_job")} ${w.current_job_id || t("none")}</div>
      ${w.current_user ? `<div class="muted">${escapeHtml(w.current_user)} · ${Number(w.job_cpu_percent || 0).toFixed(0)}% CPU / ${w.job_proc_count || 0} process${w.pause_all ? " · paused" : ""}</div>` : ""}
  `;
}

function envVerdict(env) {
  const hit = (state.verdicts || []).find((x) => x.id === env.id);
  if (hit) {
    if (hit.ok) return { ok: true, reason: t("env_ready") };
    if (hit.code === "lang") return { ok: false, reason: t("env_lang") };
    if (hit.code === "docker") return { ok: false, reason: t("env_docker") };
    if (hit.code === "admin") return { ok: false, reason: t("env_admin") };
    if (hit.code === "missing" || (hit.missing && hit.missing.length)) {
      return { ok: false, reason: t("env_missing", { mods: (hit.missing || []).join(", ") }) };
    }
    return { ok: false, reason: hit.reason || t("env_pending") };
  }
  if (state.scan) return { ok: false, reason: t("env_pending") };
  const file = ($("single-file") && $("single-file").files[0]) || ($("project-zip") && $("project-zip").files[0]) || currentShareFile();
  if (file) return { ok: false, reason: t("env_scanning") };
  return { ok: false, reason: t("env_pending") };
}

let scanTimer = 0;
function scheduleScan() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(rescanUpload, 200);
}

async function rescanUpload() {
  const single = $("single-file") && $("single-file").files[0];
  const zip = $("project-zip") && $("project-zip").files[0];
  const shareId = state.place === "auto" ? "" : state.sharePickId;
  const box = $("scan-status");
  if (!single && !zip && !shareId) {
    state.scan = null;
    state.verdicts = [];
    state.envId = "";
    state.placement = null;
    if (box) box.textContent = "";
    renderEnvs();
    renderPicked();
    return;
  }
  const auto = state.place === "auto";
  const workerId = $("worker-select").value;
  const body = new FormData();
  if (shareId) {
    body.append("share_file_id", shareId);
    body.append("kind", state.sharePickSlot === "zip" ? "zip" : "single");
  } else {
    body.append("artifact", single || zip);
    body.append("kind", single ? "single" : "zip");
  }
  body.append("place", auto ? "auto" : "manual");
  if (!auto && workerId) body.append("worker_id", workerId);
  if (box) box.textContent = t("env_scanning");
  try {
    const data = await api("/api/v1/jobs/scan", { method: "POST", body });
    state.scan = data.scan;
    state.verdicts = data.verdicts || [];
    state.placement = data.placement || null;
    if (state.placement && $("worker-select")) {
      $("worker-select").value = state.placement.worker_id;
      if (!state.envId) state.envId = state.placement.env_id;
    }
    if (state.envId) {
      const envOk = state.verdicts.find((v) => v.id === state.envId && v.ok);
      if (!envOk) state.envId = state.placement ? state.placement.env_id : "";
    }
    const ready = state.verdicts.filter((v) => v.ok);
    if (!state.envId && ready.length === 1) state.envId = ready[0].id;
    if (box) {
      const mods = (state.scan.imports || []).join(", ") || t("none");
      const mains = state.scan.mains || [];
      box.textContent =
        `${t("scan_imports")} ${mods}` +
        (mains.length > 1 ? ` · ${t("scan_mains", { n: mains.length })}` : "") +
        (state.scan.needs_admin ? ` · ${t("scan_admin")}` : "");
    }
  } catch (err) {
    state.scan = null;
    state.verdicts = [];
    state.placement = null;
    if (box) box.textContent = err.message;
  }
  renderEnvs();
  renderPicked();
}

function renderEnvs() {
  const root = $("env-list");
  if (!root) return;
  const auto = state.place === "auto";
  const wid = (state.placement && auto && state.placement.worker_id) || ($("worker-select") && $("worker-select").value);
  const w = state.workers.find((x) => x.id === wid);
  if (!w) {
    root.textContent = auto ? (state.scan ? t("no_place") : t("env_pending")) : t("pick_worker");
    return;
  }
  const envs = w.environments || [];
  if (!envs.length) {
    root.textContent = t("no_env_yet");
    return;
  }
  root.innerHTML = "";
  for (const env of envs) {
    const v = envVerdict(env);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "env-item" + (v.ok ? " ok" : " disabled") + (state.envId === env.id ? " active" : "");
    btn.disabled = !v.ok;
    btn.innerHTML = `<strong>${escapeHtml(env.label || env.id)}</strong><div class="muted">${escapeHtml(v.ok ? t("env_ready") : v.reason)}</div>`;
    if (v.ok) {
      btn.addEventListener("click", () => {
        state.envId = env.id;
        renderEnvs();
      });
    }
    root.appendChild(btn);
  }
}

function statePill(s) {
  if (s === "running") return "ok";
  if (s === "queued") return "warn";
  if (s === "failed") return "bad";
  if (s === "cancelled") return "bad";
  return "";
}

function selectJob(id) {
  if (id !== state.selectedJob) {
    const frame = $("job-ui");
    if (frame) {
      frame.removeAttribute("src");
      frame.removeAttribute("data-job");
      frame.hidden = true;
    }
  }
  state.selectedJob = id;
  state.logAfter = 0;
  state.displayFile = "";
  state.outputSig = "";
  $("logs").textContent = "";
  renderJobs();
  refreshLogs();
  refreshOutput();
}

async function stopJob(id) {
  await api(`/api/v1/jobs/${id}/stop`, { method: "POST" });
  await refreshJobs();
}

async function rerunJob(id) {
  const data = await api(`/api/v1/jobs/${id}/rerun`, { method: "POST" });
  if (data.job && data.job.id) {
    state.selectedJob = data.job.id;
    state.logAfter = 0;
    state.displayFile = "";
    state.outputSig = "";
    $("logs").textContent = "";
  }
  await refreshJobs();
}

async function storeJob(id) {
  await api(`/api/v1/jobs/${id}/store`, { method: "POST" });
}

function renderJobs() {
  const root = $("jobs");
  if (!root) return;
  root.innerHTML = "";
  if (!state.jobs.length) {
    root.innerHTML = `<p class="muted">${t("jobs_empty")}</p>`;
  }
  for (const job of state.jobs) {
    const row = document.createElement("div");
    row.className = "item" + (job.id === state.selectedJob ? " active" : "");
    const actions = [];
    if (job.state === "running" || job.state === "queued") {
      actions.push(`<button type="button" class="ghost danger tiny" data-act="stop">${t("stop")}</button>`);
    } else if (job.state === "succeeded" || job.state === "failed" || job.state === "cancelled") {
      actions.push(`<button type="button" class="ghost tiny" data-act="rerun">${t("run_again")}</button>`);
    }
    row.innerHTML = `
      <div class="item-row">
        <div>
          <strong>${escapeHtml(job.name)}</strong>
          <div class="muted"><span class="pill ${statePill(job.state)}">${escapeHtml(t("state_" + job.state) || job.state)}</span> · ${escapeHtml(job.user_name || "")} · ${job.id.slice(0, 8)}</div>
        </div>
        <div class="job-actions">${actions.join("")}</div>
      </div>`;
    row.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      selectJob(job.id);
    });
    row.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          if (btn.dataset.act === "stop") await stopJob(job.id);
          if (btn.dataset.act === "rerun") await rerunJob(job.id);
        } catch (err) {
          alert(err.message);
        }
      });
    });
    root.appendChild(row);
  }
  const job = state.jobs.find((j) => j.id === state.selectedJob);
  const stopBtn = $("stop-job");
  const rerunBtn = $("rerun-job");
  const storeBtn = $("store-job");
  const done = job && (job.state === "succeeded" || job.state === "failed" || job.state === "cancelled");
  if (stopBtn) stopBtn.hidden = !(job && (job.state === "running" || job.state === "queued"));
  if (rerunBtn) rerunBtn.hidden = !done;
  if (storeBtn) storeBtn.hidden = !done;
  syncJobUi(job);
}

function syncJobUi(job) {
  const frame = $("job-ui");
  const view = $("display-view");
  const thumbs = $("display-thumbs");
  const title = $("display-title");
  const ready = !!(job && job.state === "running" && job.ui && job.ui.ready);
  if (title) title.textContent = ready ? t("app") : t("display");
  if (!frame) return;
  if (ready) {
    const src = `/jobs/${job.id}/ui/`;
    if (frame.getAttribute("data-job") !== job.id) {
      frame.setAttribute("data-job", job.id);
      frame.src = src;
    }
    frame.hidden = false;
    if (view) view.hidden = true;
    if (thumbs) thumbs.hidden = true;
    return;
  }
  if (frame.getAttribute("data-job")) {
    frame.removeAttribute("src");
    frame.removeAttribute("data-job");
  }
  frame.hidden = true;
  if (view) view.hidden = false;
  if (thumbs) thumbs.hidden = false;
}

function renderStats(samples) {
  const byWorker = {};
  for (const s of samples) {
    (byWorker[s.worker_id] ||= []).push(s);
  }
  const root = $("stats");
  root.innerHTML = "";
  for (const [id, rows] of Object.entries(byWorker)) {
    const last = rows[rows.length - 1];
    const w = state.workers.find((x) => x.id === id);
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <h3>${escapeHtml(w ? w.name : id.slice(0, 8))}</h3>
      <div class="muted">${rows.length} ${t("samples")} · CPU ${last.cpu_percent.toFixed(1)}% · ${last.memory_percent.toFixed(1)}%</div>
      <div class="muted">${t("net")} ${formatBytes(last.bytes_sent)} / ${formatBytes(last.bytes_recv)}</div>
    `;
    root.appendChild(el);
  }
  if (!samples.length) root.innerHTML = `<p class="muted">${t("no_metrics")}</p>`;
}

async function refreshWorkers() {
  const data = await api("/api/v1/workers");
  state.workers = data.workers;
  renderWorkers();
}

async function refreshJobs() {
  const data = await api("/api/v1/jobs");
  state.jobs = data.jobs;
  if (state.selectedJob && !state.jobs.some((j) => j.id === state.selectedJob)) {
    state.selectedJob = null;
    state.logAfter = 0;
    state.displayFile = "";
    state.outputSig = "";
    $("logs").textContent = "";
  }
  if (!state.selectedJob && state.jobs[0]) state.selectedJob = state.jobs[0].id;
  renderJobs();
  await refreshLogs();
  await refreshOutput();
}

async function refreshLogs() {
  if (!state.selectedJob) {
    $("job-title").textContent = t("terminal");
    if ($("stdin-row")) $("stdin-row").hidden = true;
    if ($("output-files")) $("output-files").innerHTML = "";
    clearDisplay();
    return;
  }
  const job = state.jobs.find((j) => j.id === state.selectedJob);
  $("job-title").textContent = job ? `${job.name} · ${t("state_" + job.state) || job.state}` : t("logs");
  const link = $("result-link");
  if (job && job.result_path) {
    link.hidden = false;
    link.href = `#result-${job.id}`;
    link.onclick = async (e) => {
      e.preventDefault();
      const res = await fetch(`/api/v1/jobs/${job.id}/result`, {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "result.zip";
      a.click();
      URL.revokeObjectURL(url);
    };
  } else {
    link.hidden = true;
  }
  const stdinRow = $("stdin-row");
  if (stdinRow) stdinRow.hidden = !(job && job.state === "running");
  const data = await api(`/api/v1/jobs/${state.selectedJob}/logs?after=${state.logAfter}`);
  if (data.logs.length) {
    const extra = data.logs.map((l) => termLine(l.stream, l.line)).join("\n");
    const pre = $("logs");
    pre.textContent = (pre.textContent + "\n" + extra).trim();
    pre.scrollTop = pre.scrollHeight;
    state.logAfter = data.logs[data.logs.length - 1].id;
  }
}

async function sendStdin() {
  if (!state.selectedJob) return;
  const input = $("stdin-text");
  const text = input ? input.value : "";
  if (!text) return;
  await api(`/api/v1/jobs/${state.selectedJob}/stdin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (input) input.value = "";
  await refreshLogs();
}

const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"];

function isImageName(name) {
  const lower = String(name || "").toLowerCase();
  return IMAGE_EXTS.some((ext) => lower.endsWith(ext));
}

function termLine(stream, line) {
  const text = String(line || "");
  if (stream === "stdin") return `> ${text}`;
  if (stream === "system") return `# ${text}`;
  return text;
}

function outputUrl(jobId, name) {
  return `/api/v1/jobs/${jobId}/output/${String(name).split("/").map(encodeURIComponent).join("/")}`;
}

function clearDisplay() {
  const view = $("display-view");
  const thumbs = $("display-thumbs");
  if (view) view.innerHTML = "";
  if (thumbs) thumbs.innerHTML = "";
  state.displayFile = "";
  state.outputSig = "";
}

function outputEntries(files) {
  return (files || []).map((item) => {
    if (typeof item === "string") return { name: item, size: 0, mtime: 0 };
    return {
      name: String(item.name || ""),
      size: Number(item.size || 0),
      mtime: Number(item.mtime || 0),
    };
  }).filter((item) => item.name);
}

async function setBlobImg(img, jobId, name) {
  if (!img) return;
  const res = await fetch(outputUrl(jobId, name), {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (!res.ok) return;
  const blob = await res.blob();
  if (!img.isConnected) return;
  const prev = img.getAttribute("data-blob");
  if (prev) URL.revokeObjectURL(prev);
  const url = URL.createObjectURL(blob);
  img.setAttribute("data-blob", url);
  img.src = url;
}

async function refreshOutput() {
  const box = $("output-files");
  const view = $("display-view");
  const thumbs = $("display-thumbs");
  const job = state.jobs.find((j) => j.id === state.selectedJob);
  if (!box || !view || !thumbs) return;
  if (!job) {
    box.innerHTML = "";
    clearDisplay();
    return;
  }
  let files = [];
  try {
    const data = await api(`/api/v1/jobs/${job.id}/output`);
    files = outputEntries(data.files);
  } catch {
    files = [];
  }
  const images = files.filter((f) => isImageName(f.name));
  const others = files.filter((f) => !isImageName(f.name));
  const names = images.map((f) => f.name);
  const popouts = names.filter((name) => name.replace(/\\/g, "/").includes("_display/"));
  const preferred = popouts.length ? popouts : names;
  if (!names.length) state.displayFile = "";
  else if (!names.includes(state.displayFile)) state.displayFile = preferred[preferred.length - 1];
  const sig = `${job.id}:${files.map((f) => `${f.name}:${f.size}:${f.mtime}`).join("|")}:${state.displayFile}`;
  if (sig === state.outputSig) return;
  state.outputSig = sig;
  box.innerHTML = others.length
    ? others.map((f) => `<div class="item"><a href="#" data-out="${escapeHtml(f.name)}">${escapeHtml(f.name)}</a></div>`).join("")
    : "";
  box.querySelectorAll("a[data-out]").forEach((a) => {
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const res = await fetch(outputUrl(job.id, a.dataset.out), {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const dl = document.createElement("a");
      dl.href = url;
      dl.download = a.dataset.out.split("/").pop() || "file";
      dl.click();
      URL.revokeObjectURL(url);
    });
  });
  if (!images.length) {
    view.innerHTML = "";
    thumbs.innerHTML = "";
    state.displayFile = "";
    return;
  }
  view.innerHTML = `<img alt="" />`;
  await setBlobImg(view.querySelector("img"), job.id, state.displayFile);
  thumbs.innerHTML = names.map((name) =>
    `<button type="button" class="${name === state.displayFile ? "active" : ""}" data-img="${escapeHtml(name)}"><img alt="" /></button>`
  ).join("");
  for (const btn of thumbs.querySelectorAll("button[data-img]")) {
    const name = btn.dataset.img;
    await setBlobImg(btn.querySelector("img"), job.id, name);
    btn.addEventListener("click", () => {
      state.displayFile = name;
      state.outputSig = "";
      refreshOutput().catch(() => {});
    });
  }
}

async function refreshStats() {
  const data = await api("/api/v1/metrics");
  renderStats(data.samples);
}

function historyLabel(action) {
  return ({
    applied: t("history_applied"),
    approved: t("history_approved"),
    removed: t("history_removed"),
    revoked: t("history_revoked"),
  })[action] || action;
}

function jobCounts(acc) {
  return acc.jobs || { queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0 };
}

function formatWhen(ts) {
  if (!ts) return t("none");
  try {
    return new Date(Number(ts) * 1000).toLocaleString();
  } catch {
    return String(ts);
  }
}

function renderAccounts() {
  const root = $("accounts");
  const hist = $("approval-history");
  if (!root) return;
  root.innerHTML = "";
  if ($("account-count")) $("account-count").textContent = `${state.accounts.length} ${t("machines")}`.trim();
  if (!state.accounts.length) {
    root.innerHTML = `<p class="muted">${t("no_accounts")}</p>`;
  }
  for (const acc of state.accounts) {
    if (acc.kind === "worker") continue;
    const card = document.createElement("div");
    card.className = "card pickable acct " + (acc.online ? "online" : "offline") + (state.adminUser === acc.username ? " picked" : "");
    const counts = jobCounts(acc);
    const live = acc.online ? [t("user_online"), "ok"] : [t("user_offline"), "warn"];
    const st = acc.status === "approved" ? [t("acct_approved"), "ok"] : [t("acct_pending"), "warn"];
    const kind = acc.kind === "worker" ? t("role_worker") : t("role_user");
    card.innerHTML = `
      <h3>${escapeHtml(groupDigits(acc.username, 2))}</h3>
      <div>
        <span class="pill">${kind}</span>
        <span class="pill ${st[1]}">${st[0]}</span>
        <span class="pill ${live[1]}">${live[0]}</span>
        ${acc.blocked_count ? `<span class="pill warn">${t("blocked_n", { n: acc.blocked_count })}</span>` : ""}
      </div>
      <div class="muted">${t("jobs_submitted")} ${counts.queued + counts.running} · ${t("jobs_removed")} ${counts.cancelled}</div>
      <div class="muted">${t("jobs_done")} ${counts.succeeded} · ${t("jobs_failed")} ${counts.failed}</div>
    `;
    card.addEventListener("click", () => {
      state.adminUser = acc.username;
      state.adminUserJobTab = "submitted";
      renderAccounts();
      refreshAdminUser().catch(() => {});
    });
    root.appendChild(card);
  }
  if (hist) {
    hist.innerHTML = "";
    if (!state.history.length) {
      hist.innerHTML = `<p class="muted">${t("history_empty")}</p>`;
    } else {
      for (const ev of state.history) {
        const el = document.createElement("div");
        el.className = "item";
        const who = ev.actor ? t("by_actor", { who: groupDigits(ev.actor, 2) }) : "";
        el.innerHTML = `<strong>${escapeHtml(groupDigits(ev.username, 2))}</strong>
          <div class="muted">${historyLabel(ev.action)} ${who} · ${formatWhen(ev.created_at)}</div>`;
        hist.appendChild(el);
      }
    }
  }
  renderAdminUser();
}

function jobsForTab(jobs, tab) {
  return (jobs || []).filter((j) => {
    if (tab === "submitted") return j.state === "queued" || j.state === "running";
    if (tab === "done") return j.state === "succeeded";
    if (tab === "failed") return j.state === "failed";
    if (tab === "removed") return j.state === "cancelled";
    return true;
  });
}

function renderAdminUser() {
  const box = $("admin-user");
  if (!box) return;
  if (state.role !== "admin" || !state.adminUser) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const detail = state.adminUserDetail;
  const acc = (detail && detail.account) || state.accounts.find((a) => a.username === state.adminUser);
  if (!acc) {
    box.innerHTML = `<p class="muted">${t("access_loading")}</p>`;
    return;
  }
  const counts = jobCounts(acc);
  const jobs = (detail && detail.jobs) || [];
  const tab = state.adminUserJobTab || "submitted";
  const shown = jobsForTab(jobs, tab);
  const tabs = [
    ["submitted", t("jobs_submitted"), counts.queued + counts.running],
    ["done", t("jobs_done"), counts.succeeded],
    ["failed", t("jobs_failed"), counts.failed],
    ["removed", t("jobs_removed"), counts.cancelled],
  ];
  const jobHtml = shown.length
    ? shown.map((j) => `<div class="item">
        <strong>${escapeHtml(j.name || j.id)}</strong>
        <div class="muted"><span class="pill">${t("state_" + j.state) || j.state}</span> ${escapeHtml(j.worker_id || "").slice(0, 8)} · ${formatWhen(j.created_at)}</div>
        ${j.error ? `<div class="muted">${escapeHtml(j.error)}</div>` : ""}
        ${j.state === "running" ? `<button type="button" class="ghost danger tiny" data-jstop="${j.id}">${t("stop")}</button>` : ""}
      </div>`).join("")
    : `<p class="muted">${t("job_empty")}</p>`;
  box.innerHTML = `
    <h3>${escapeHtml(groupDigits(acc.username, 2))}</h3>
    <div>
      <span class="pill">${acc.kind === "worker" ? t("role_worker") : t("role_user")}</span>
      <span class="pill">${acc.status === "approved" ? t("acct_approved") : t("acct_pending")}</span>
      <span class="pill">${acc.online ? t("user_online") : t("user_offline")}</span>
    </div>
    <p class="muted">${t("created_at")} · ${formatWhen(acc.created_at)}</p>
    <h3>${t("blocked_on")}</h3>
    <div>${((detail && detail.blocked_on) || []).length
      ? (detail.blocked_on || []).map((b) => `<div class="item"><strong>${escapeHtml(b.worker_name)}</strong>
          <button type="button" class="ghost tiny" data-unw="${b.worker_id}" data-user="${acc.username}">${t("unblock_user")}</button></div>`).join("")
      : `<p class="muted">${t("blocklist_empty")}</p>`}</div>
    <div>
      ${acc.status === "pending"
        ? `<button type="button" class="ghost" data-approve="${acc.username}">${t("approve")}</button>`
        : `<button type="button" class="ghost" data-revoke="${acc.username}">${t("set_pending")}</button>`}
      <button type="button" class="ghost danger" data-remove="${acc.username}">${t("remove_account")}</button>
    </div>
    <div class="job-tabs">
      ${tabs.map(([id, label, n]) => `<button type="button" class="ghost${tab === id ? " active" : ""}" data-jobtab="${id}">${label} ${n}</button>`).join("")}
    </div>
    <div>${jobHtml}</div>
  `;
  box.onclick = async (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.dataset.jobtab) {
      state.adminUserJobTab = target.dataset.jobtab;
      renderAdminUser();
      return;
    }
    try {
      if (target.dataset.approve) {
        await api(`/api/v1/admin/accounts/${target.dataset.approve}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      } else if (target.dataset.revoke) {
        await api(`/api/v1/admin/accounts/${target.dataset.revoke}/status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "pending" }) });
      } else if (target.dataset.remove) {
        if (!confirm(t("remove_confirm"))) return;
        await api(`/api/v1/admin/accounts/${target.dataset.remove}`, { method: "DELETE" });
        state.adminUser = "";
        state.adminUserDetail = null;
      } else if (target.dataset.jstop) {
        await api(`/api/v1/jobs/${target.dataset.jstop}/stop`, { method: "POST" });
      } else if (target.dataset.unw && target.dataset.user) {
        await api(`/api/v1/admin/workers/${target.dataset.unw}/unblock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_name: target.dataset.user }),
        });
      } else return;
      await refreshAdmin();
    } catch (err) {
      alert(err.message);
    }
  };
}

async function refreshAdminUser() {
  if (state.role !== "admin" || !state.adminUser) {
    state.adminUserDetail = null;
    renderAdminUser();
    return;
  }
  state.adminUserDetail = await api(`/api/v1/admin/accounts/${state.adminUser}`);
  renderAdminUser();
}

function renderAdminBoard() {
  const box = $("admin-board");
  if (!box) return;
  if (state.role !== "admin") {
    box.hidden = true;
    return;
  }
  const b = state.adminBoard;
  if (!state.adminWorkerId) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  if (!b) {
    box.innerHTML = `<p class="muted">${t("access_loading")}</p>`;
    return;
  }
  if (b.pending_account) {
    const acc = b.pending_account;
    const st = acc.status === "approved" ? [t("acct_approved"), "ok"] : [t("acct_pending"), "warn"];
    box.innerHTML = `
      <h3>${escapeHtml(groupDigits(acc.username, 2))}</h3>
      <div>
        <span class="pill">${t("role_worker")}</span>
        <span class="pill ${st[1]}">${st[0]}</span>
      </div>
      <div>
        ${acc.status === "pending" ? `<button type="button" class="ghost" id="admin-approve-machine">${t("approve")}</button>` : ""}
        <button type="button" class="ghost danger" id="admin-remove-machine">${t("remove_machine")}</button>
      </div>
    `;
    $("admin-approve-machine")?.addEventListener("click", () => adminAct("approve_machine"));
    $("admin-remove-machine")?.addEventListener("click", () => adminAct("remove_machine"));
    return;
  }
  const occ = b.occupancy;
  const freeze = b.can_edit_queue;
  let occHtml = `<p class="muted">${t("no_job")}</p>`;
  if (occ) {
    occHtml = `<p><strong>${escapeHtml(occ.user_name)}</strong> · ${escapeHtml(occ.job_name)} · ${Number(occ.cpu_percent).toFixed(0)}% CPU
      <button type="button" class="ghost danger tiny" data-stop="${occ.job_id}">${t("stop")}</button></p>`;
  }
  const q = (b.queue || []).map((item) => {
    if (item.kind === "anchor") {
      return `<div class="item"><span class="pill">anchor</span> <button type="button" class="ghost tiny" data-release="${item.id}">${t("release")}</button></div>`;
    }
    const canDel = freeze && item.state === "queued";
    return `<div class="item${item.state === "running" ? " running" : ""}">
      <strong>${escapeHtml(item.name)}</strong>
      <div class="muted"><span class="pill">${item.state}</span> User ${escapeHtml(item.user_name || "?")} · ${item.id.slice(0, 8)}</div>
      <div>
        ${item.state === "running" ? `<button type="button" class="ghost danger tiny" data-stop="${item.id}">${t("stop")}</button>` : ""}
        ${item.state === "queued" ? `<button type="button" class="ghost tiny" data-before="${item.id}">${t("anchor_before")}</button>` : ""}
        ${item.state === "queued" || item.state === "running" ? `<button type="button" class="ghost tiny" data-after="${item.id}">${t("anchor_after")}</button>` : ""}
        ${canDel ? `<button type="button" class="ghost danger tiny" data-del="${item.id}">${t("delete_queued")}</button>` : ""}
      </div>
    </div>`;
  }).join("");
  const reorder = (b.can_reorder && (b.reorder_job_ids || []).length >= 2)
    ? `<div class="item">${(b.reorder_job_ids || []).map((id, i) => `<button type="button" class="ghost tiny" data-up="${id}" ${i === 0 ? "disabled" : ""}>▲ ${id.slice(0, 8)}</button>`).join("")}</div>`
    : "";
  box.innerHTML = `
    <h3>${escapeHtml((b.worker && b.worker.name) || state.adminWorkerId)}</h3>
    ${occHtml}
    <div>
      <button type="button" class="ghost" id="admin-pause" ${b.pause_all ? "disabled" : ""}>${t("pause_all")}</button>
      <button type="button" class="ghost" id="admin-resume" ${b.pause_all ? "" : "disabled"}>${t("resume_all")}</button>
      <button type="button" class="ghost danger" id="admin-remove-machine">${t("remove_machine")}</button>
    </div>
    <div>${q || `<p class="muted">${t("none")}</p>`}</div>
    ${reorder}
    <h3>${t("blocklist_title")}</h3>
    <div class="file-row">
      <input id="admin-block-user" inputmode="numeric" maxlength="9" />
      <button type="button" class="ghost danger tiny" id="admin-block-add">${t("block_user")}</button>
    </div>
    <div>${(b.blocked_users || []).length
      ? (b.blocked_users || []).map((u) => `<div class="item"><strong>${escapeHtml(groupDigits(u, 2))}</strong>
          <button type="button" class="ghost tiny" data-unblock="${u}">${t("unblock_user")}</button></div>`).join("")
      : `<p class="muted">${t("blocklist_empty")}</p>`}</div>
  `;
  $("admin-pause")?.addEventListener("click", () => adminAct("pause", { on: true }));
  $("admin-resume")?.addEventListener("click", () => adminAct("pause", { on: false }));
  $("admin-remove-machine")?.addEventListener("click", () => adminAct("remove_machine"));
  bindGroupedInput($("admin-block-user"), 2);
  $("admin-block-add")?.addEventListener("click", () => {
    const user = onlyDigits($("admin-block-user") && $("admin-block-user").value);
    if (user.length !== 8) return;
    adminAct("block", { user_name: user });
  });
  box.onclick = (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.dataset.stop) adminAct("stop", { id: target.dataset.stop });
    if (target.dataset.release) adminAct("release", { id: target.dataset.release });
    if (target.dataset.before) adminAct("anchor", { before_id: target.dataset.before });
    if (target.dataset.after) adminAct("anchor", { after_id: target.dataset.after });
    if (target.dataset.del) adminAct("delete", { id: target.dataset.del });
    if (target.dataset.unblock) adminAct("unblock", { user_name: target.dataset.unblock });
    if (target.dataset.up) {
      const ids = [...(b.reorder_job_ids || [])];
      const i = ids.indexOf(target.dataset.up);
      if (i > 0) {
        [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
        adminAct("reorder", { job_ids: ids });
      }
    }
  };
}

async function adminAct(kind, payload) {
  const wid = state.adminWorkerId;
  if (!wid) return;
  const base = `/api/v1/admin/workers/${wid}`;
  try {
    if (kind === "pause") await api(`${base}/pause`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (kind === "anchor") await api(`${base}/anchors`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (kind === "release") await api(`${base}/anchors/${payload.id}/release`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (kind === "reorder") await api(`${base}/reorder`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (kind === "delete") await api(`${base}/queue/${payload.id}`, { method: "DELETE" });
    if (kind === "stop") await api(`${base}/jobs/${payload.id}/stop`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (kind === "block") {
      if (onlyDigits(payload.user_name) === "54299486") throw new Error(t("cannot_block_admin"));
      await api(`${base}/block`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    }
    if (kind === "unblock") await api(`${base}/unblock`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (kind === "remove_machine") {
      if (!confirm(t("remove_machine_confirm"))) return;
      await api(base, { method: "DELETE" });
      if (state.shareWorkerId === wid) state.shareWorkerId = "";
      state.adminWorkerId = "";
      state.adminBoard = null;
      await refresh();
      return;
    }
    if (kind === "approve_machine") {
      await api(`/api/v1/admin/accounts/${wid}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      await refresh();
      return;
    }
    await refreshAdminBoard();
  } catch (err) {
    alert(err.message);
  }
}

async function refreshAdmin() {
  const data = await api("/api/v1/admin/accounts");
  state.accounts = data.accounts || [];
  state.workerAccounts = data.workers || [];
  state.history = data.history || [];
  if (state.adminUser && !state.accounts.some((a) => a.username === state.adminUser)) {
    state.adminUser = "";
    state.adminUserDetail = null;
  }
  renderAccounts();
  renderWorkers();
  await refreshAdminUser();
  await refreshAdminBoard();
}

function shareFileUrl(fileId) {
  if (state.role === "admin") return `/api/v1/admin/workers/${state.shareWorkerId}/share/files/${fileId}`;
  return `/api/v1/share/files/${fileId}`;
}

async function downloadShare(file) {
  const res = await fetch(shareFileUrl(file.id), { headers: { Authorization: `Bearer ${state.token}` } });
  if (!res.ok) throw new Error(t("share_empty"));
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = file.name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function shareFileRow(file) {
  const grantOk = !state.shareData || file.kind !== "granted" || state.shareData.grant === "approved";
  const use = state.role === "user" && grantOk
    ? `<button type="button" class="ghost tiny" data-use="${file.id}">${t("share_use")}</button>`
    : "";
  return `<div class="item">
    <strong>${escapeHtml(file.name)}</strong>
    <div class="muted">${file.kind} · ${formatBytes(file.size)} · ${formatWhen(file.created_at)}</div>
    <div>
      ${use}
      <button type="button" class="ghost tiny" data-dl="${file.id}">${t("download_result")}</button>
      <button type="button" class="ghost danger tiny" data-rm="${file.id}">${t("share_remove")}</button>
    </div>
  </div>`;
}

function shareUploadRow(upload, staff) {
  const who = staff ? `${groupDigits(upload.owner, 2)} · ` : "";
  return `<div class="item">
    <strong>${escapeHtml(upload.name)}</strong>
    <div class="muted">${who}${t("share_uploading")}</div>
    <div><button type="button" class="ghost danger tiny" data-cx="${upload.id}">${t("share_cancel")}</button></div>
  </div>`;
}

function shareOwnerBlocks(files, uploads, staff) {
  const ups = uploads || [];
  if (!files.length && !ups.length) return `<p class="muted">${t("share_empty")}</p>`;
  if (!staff) return ups.map((u) => shareUploadRow(u, false)).join("") + files.map(shareFileRow).join("");
  const groups = new Map();
  for (const upload of ups) {
    if (!groups.has(upload.owner)) groups.set(upload.owner, { files: [], uploads: [] });
    groups.get(upload.owner).uploads.push(upload);
  }
  for (const file of files) {
    if (!groups.has(file.owner)) groups.set(file.owner, { files: [], uploads: [] });
    groups.get(file.owner).files.push(file);
  }
  return [...groups.entries()].map(([owner, pack]) => `
    <div class="share-user">
      <div class="muted">${escapeHtml(groupDigits(owner, 2))}</div>
      ${pack.uploads.map((u) => shareUploadRow(u, false)).join("")}
      ${pack.files.map(shareFileRow).join("")}
    </div>
  `).join("");
}

function fillShareLists() {
  const data = state.shareData;
  if (!data) return;
  const staff = state.role === "admin";
  const files = data.files || [];
  const uploads = data.uploads || [];
  const openEl = $("share-open-list");
  const grantedEl = $("share-granted-list");
  if (openEl) openEl.innerHTML = shareOwnerBlocks(files.filter((f) => f.kind === "open"), uploads.filter((u) => u.kind === "open"), staff);
  if (grantedEl) grantedEl.innerHTML = shareOwnerBlocks(files.filter((f) => f.kind === "granted"), uploads.filter((u) => u.kind === "granted"), staff);
  const grantList = $("share-grant-list");
  if (grantList) {
    grantList.innerHTML = (data.grants || []).map((g) => `<div class="item">
      <strong>${escapeHtml(groupDigits(g.user_name, 2))}</strong>
      <span class="pill">${g.status === "approved" ? t("share_granted") : t("share_pending")}</span>
      <div>
        ${g.status !== "approved" ? `<button type="button" class="ghost tiny" data-ok="${g.user_name}">${t("approve")}</button>` : ""}
        <button type="button" class="ghost danger tiny" data-rv="${g.user_name}">${t("share_revoke")}</button>
      </div>
    </div>`).join("") || `<p class="muted">${t("none")}</p>`;
  }
  const logList = $("share-log-list");
  if (logList) {
    logList.innerHTML = (data.events || []).map((ev) => `<div class="item">
      <div>${escapeHtml(ev.file_name || ev.kind || ev.action)} · ${escapeHtml(ev.action)} · ${escapeHtml(groupDigits(ev.actor, 2) || ev.actor)}</div>
      <div class="muted">${formatWhen(ev.created_at)}</div>
    </div>`).join("") || `<p class="muted">${t("none")}</p>`;
  }
}

function shareBoxClick(e) {
  const el = e.target;
  if (!(el instanceof HTMLElement)) return;
  const files = (state.shareData && state.shareData.files) || [];
  const file = files.find((f) => f.id === el.dataset.dl || f.id === el.dataset.rm || f.id === el.dataset.use);
  if (el.dataset.dl && file) downloadShare(file).catch((err) => alert(err.message));
  if (el.dataset.rm && file) shareAct("remove", file.id);
  if (el.dataset.ok) shareAct("approve", el.dataset.ok);
  if (el.dataset.rv) shareAct("revoke", el.dataset.rv);
  if (el.dataset.cx) cancelShareUpload(el.dataset.cx);
  if (el.dataset.use && file) useShareFile(file);
}

function useShareFile(file) {
  if (state.shareWorkerId && $("worker-select")) $("worker-select").value = state.shareWorkerId;
  $("single-file").value = "";
  $("project-zip").value = "";
  state.sharePickId = file.id;
  state.sharePickSlot = isZipName(file.name) ? "zip" : "single";
  document.querySelector('[data-tab="submit"]').click();
  refreshSubmitShare().then(() => {
    const sel = $(state.sharePickSlot === "zip" ? "share-zip" : "share-single");
    if (sel) sel.value = file.id;
    setFileStatus();
    scheduleScan();
  }).catch(() => {});
}

function renderShare() {
  const box = $("share-box");
  if (!box) return;
  const wid = state.shareWorkerId;
  if (!wid) {
    box.dataset.key = "";
    box.innerHTML = `<p class="muted">${t("pick_worker")}</p>`;
    return;
  }
  const data = state.shareData;
  if (!data) {
    box.dataset.key = "";
    box.innerHTML = `<p class="muted">${t("access_loading")}</p>`;
    return;
  }
  const staff = state.role === "admin";
  const grant = data.grant || "";
  const key = `${wid}:${grant}:${staff}`;
  if (box.dataset.key !== key) {
    box.dataset.key = key;
    let grantedCtl = "";
    if (!staff) {
      if (grant === "approved") {
        grantedCtl = `<div class="file-row"><input type="file" id="share-granted-file" /><button type="button" class="ghost" id="share-granted-up">${t("share_upload")}</button></div>`;
      } else if (grant === "pending") {
        grantedCtl = `<button type="button" class="ghost" disabled>${t("share_pending")}</button>`;
      } else {
        grantedCtl = `<button type="button" class="ghost" id="share-apply">${t("share_apply")}</button>`;
      }
    }
    box.innerHTML = `
      <div class="split share-split">
        <div class="panel">
          <h3>${t("share_open")}</h3>
          ${staff ? "" : `<div class="file-row"><input type="file" id="share-open-file" /><button type="button" class="ghost" id="share-open-up">${t("share_upload")}</button></div>`}
          <div id="share-open-list"></div>
        </div>
        <div class="panel">
          <h3>${t("share_granted")}</h3>
          ${grantedCtl}
          <div id="share-granted-list"></div>
        </div>
      </div>
      ${staff ? `<div class="panel"><h3>${t("share_grants")}</h3><div id="share-grant-list"></div></div>` : ""}
      <div class="panel"><h3>${t("share_log")}</h3><div id="share-log-list"></div></div>
    `;
    $("share-apply")?.addEventListener("click", () => shareAct("apply"));
    $("share-open-up")?.addEventListener("click", () => shareUpload("open"));
    $("share-granted-up")?.addEventListener("click", () => shareUpload("granted"));
    box.onclick = shareBoxClick;
  }
  fillShareLists();
}

let shareAbort = null;
let shareUploadId = null;

async function shareUpload(kind) {
  const input = $(kind === "open" ? "share-open-file" : "share-granted-file");
  const file = input && input.files && input.files[0];
  if (!file || !state.shareWorkerId) return;
  try {
    const started = await api("/api/v1/share/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ worker_id: state.shareWorkerId, kind, name: file.name }),
    });
    shareUploadId = started.id;
    shareAbort = new AbortController();
    await refreshShare();
    const body = new FormData();
    body.append("artifact", file);
    state.shareData = await api(`/api/v1/share/uploads/${started.id}`, {
      method: "POST",
      body,
      signal: shareAbort.signal,
    });
    renderShare();
  } catch (err) {
    if (err.message !== "cancelled" && err.message !== t("cancelled")) alert(err.message);
    await refreshShare().catch(() => {});
  } finally {
    shareUploadId = null;
    shareAbort = null;
  }
}

async function cancelShareUpload(id) {
  const wid = state.shareWorkerId;
  if (!wid || !id) return;
  if (shareUploadId === id && shareAbort) shareAbort.abort();
  const url = state.role === "admin"
    ? `/api/v1/admin/workers/${wid}/share/uploads/${id}/cancel`
    : `/api/v1/share/uploads/${id}/cancel`;
  try {
    state.shareData = await api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    renderShare();
  } catch (err) {
    if (err.message !== "cancelled" && err.message !== t("cancelled")) alert(err.message);
    await refreshShare().catch(() => {});
  }
}

async function shareAct(kind, id) {
  const wid = state.shareWorkerId;
  if (!wid) return;
  try {
    if (kind === "apply") state.shareData = await api(`/api/v1/share/apply?worker_id=${encodeURIComponent(wid)}`, { method: "POST" });
    if (kind === "remove") {
      const url = state.role === "admin"
        ? `/api/v1/admin/workers/${wid}/share/files/${id}`
        : `/api/v1/share/files/${id}`;
      await api(url, { method: "DELETE" });
      await refreshShare();
      return;
    }
    if (kind === "approve") state.shareData = await api(`/api/v1/admin/workers/${wid}/share/grants/${id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (kind === "revoke") state.shareData = await api(`/api/v1/admin/workers/${wid}/share/grants/${id}/revoke`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    renderShare();
  } catch (err) {
    alert(err.message);
  }
}

async function refreshShare() {
  fillShareWorkers();
  const wid = state.shareWorkerId;
  if (!wid) {
    state.shareData = null;
    renderShare();
    return;
  }
  const url = state.role === "admin"
    ? `/api/v1/admin/workers/${wid}/share`
    : `/api/v1/share?worker_id=${encodeURIComponent(wid)}`;
  state.shareData = await api(url);
  renderShare();
}

$("share-worker")?.addEventListener("change", () => {
  state.shareWorkerId = $("share-worker").value;
  refreshShare().catch(() => {});
});

async function refreshAdminBoard() {
  if (state.role !== "admin" || !state.adminWorkerId) {
    state.adminBoard = null;
    renderAdminBoard();
    return;
  }
  const live = state.workers.some((w) => w.id === state.adminWorkerId);
  if (!live) {
    const acc = (state.workerAccounts || []).find((a) => a.username === state.adminWorkerId);
    if (!acc) {
      state.adminWorkerId = "";
      state.adminBoard = null;
      renderAdminBoard();
      return;
    }
    state.adminBoard = { pending_account: acc, worker: { name: groupDigits(acc.username, 2) } };
    renderAdminBoard();
    return;
  }
  state.adminBoard = await api(`/api/v1/admin/workers/${state.adminWorkerId}/board`);
  renderAdminBoard();
}

async function refresh() {
  if (!state.token) return;
  await refreshWorkers();
  if (state.role === "admin") {
    await refreshAdmin();
    if (state.tab === "shared") await refreshShare();
    return;
  }
  await refreshJobs();
  if (state.tab === "stats") await refreshStats();
  if (state.tab === "shared") await refreshShare();
  if (state.tab === "submit") await refreshSubmitShare();
}

$("stop-job")?.addEventListener("click", async () => {
  if (!state.selectedJob) return;
  try {
    await stopJob(state.selectedJob);
  } catch (err) {
    alert(err.message);
  }
});
$("rerun-job")?.addEventListener("click", async () => {
  if (!state.selectedJob) return;
  try {
    await rerunJob(state.selectedJob);
  } catch (err) {
    alert(err.message);
  }
});
$("store-job")?.addEventListener("click", async () => {
  if (!state.selectedJob) return;
  try {
    await storeJob(state.selectedJob);
  } catch (err) {
    alert(err.message);
  }
});
$("stdin-send")?.addEventListener("click", async () => {
  try {
    await sendStdin();
  } catch (err) {
    alert(err.message);
  }
});
$("stdin-text")?.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  sendStdin().catch((err) => alert(err.message));
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"'`]/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
    "`": "&#96;",
  })[c]);
}

function formatBytes(n) {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)}GB`;
}

consumeResume();
applyI18n();

if (state.token) {
  api("/api/v1/auth/me").then((me) => {
    state.role = me.role || "user";
    state.user = me.user || state.user;
    sessionStorage.setItem("paas_role", state.role);
    sessionStorage.setItem("paas_user", state.user);
    showApp();
    return refresh();
  }).catch(() => showLogin());
} else {
  showLogin();
}

setInterval(() => {
  refresh().catch(() => {});
}, 2000);
