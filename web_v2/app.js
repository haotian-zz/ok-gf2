/* ok-gf2 新版界面（测试版）。只用框架 Web 模式现成的 /api 接口，不改旧界面。 */
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const c of children) if (c !== null && c !== undefined) node.append(c);
    return node;
  };

  const state = {
    catalog: null,
    tasks: [],          // /api/tasks 原样
    settings: [],       // /api/settings 原样
    status: null,
    selected: null,     // entry 对象
    page: "tasks",
    logTimer: null,
    captureTimer: null,
    eventKey: null,
  };

  // ---------- API ----------
  async function api(method, path, body) {
    const resp = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) {
      let detail = resp.statusText;
      try { detail = (await resp.json()).detail || detail; } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    const text = await resp.text();
    return text ? JSON.parse(text) : null;
  }
  const get = (p) => api("GET", p);
  const post = (p, b) => api("POST", p, b);

  function toast(msg, bad = false) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast show" + (bad ? " bad" : "");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => (t.className = "toast"), bad ? 5000 : 2200);
  }

  // ---------- 数据 ----------
  const taskByClass = (cls) => state.tasks.find((t) => t.class_name === cls);
  const taskPath = (task) => `/api/tasks/${encodeURIComponent(task.name)}`;
  const fieldOf = (task, key) => task && task.config.find((f) => f.key === key);

  async function refreshTasks() {
    state.tasks = await get("/api/tasks");
    ensureLeftoverEntry();
  }
  async function refreshStatus() {
    state.status = await get("/api/status");
  }
  async function refreshSettings() {
    state.settings = await get("/api/settings");
  }

  // ---------- 阵容场景（全局「阵容与助战」里的 <场景>编队 / <场景>助战） ----------
  // 优先级：内置默认 → 全局值 → 场景单独设置；场景留空 / 「沿用全局」就继承
  const LINEUP_GROUP = "阵容与助战";
  const LINEUP_PRESET = "编队名";
  const LINEUP_SUPPORT = "借好友助战";
  const SUPPORT_INHERIT = "沿用全局";
  const lineupGroup = () => state.settings.find((g) => g.name === LINEUP_GROUP);
  const lineupField = (key) => { const g = lineupGroup(); return g && g.fields.find((f) => f.key === key); };
  const lineupValue = (key) => { const f = lineupField(key); return f ? f.value : undefined; };
  // 有「X编队」键的 X 就是一个场景（「编队名」不以「编队」结尾，不会混进来）
  const lineupScopes = () => {
    const g = lineupGroup();
    return g ? g.fields.filter((f) => f.key.endsWith("编队")).map((f) => f.key.slice(0, -2)) : [];
  };
  const isScopeKey = (key) => lineupScopes().some((s) => key === `${s}编队` || key === `${s}助战`);
  function scopeState(scope) {
    const preset = String(lineupValue(`${scope}编队`) ?? "").trim();
    const globalPreset = String(lineupValue(LINEUP_PRESET) ?? "").trim();
    const supportField = lineupField(`${scope}助战`);
    const support = supportField ? supportField.value || SUPPORT_INHERIT : null;
    const globalSupport = lineupValue(LINEUP_SUPPORT) !== false;
    return {
      preset, globalPreset,
      effectivePreset: preset || globalPreset || "不切编队",
      support, globalSupport,
      effectiveSupport: support === null ? null : support === SUPPORT_INHERIT ? globalSupport : support === "开",
      overridden: !!preset || (support !== null && support !== SUPPORT_INHERIT),
    };
  }
  async function saveLineup(key, value) {
    const updated = await post(`/api/settings/${encodeURIComponent(LINEUP_GROUP)}/config`, { key, value });
    const idx = state.settings.findIndex((x) => x.name === updated.name);
    if (idx >= 0) state.settings[idx] = updated;
  }
  async function resetScope(scope) {
    if (lineupField(`${scope}编队`)) await saveLineup(`${scope}编队`, "");
    if (lineupField(`${scope}助战`)) await saveLineup(`${scope}助战`, SUPPORT_INHERIT);
  }

  function renderLineupCard(scope, rerender) {
    if (!lineupField(`${scope}编队`)) return null;
    const st = scopeState(scope);
    const card = el("div", { class: "lineup-card" + (st.overridden ? " overridden" : "") });
    const head = el("div", { class: "lineup-head" }, el("span", { class: "lineup-title", text: `阵容 · ${scope}` }));
    if (st.overridden) head.append(el("span", { class: "badge", text: "已单独设置" }));
    head.append(el("button", {
      class: "btn small ghost", text: "恢复全局", disabled: st.overridden ? null : "disabled",
      onclick: () => resetScope(scope).then(rerender).catch((err) => toast(`保存失败：${err.message}`, true)),
    }));
    card.append(head);
    const commit = (key, v) => saveLineup(key, v).then(rerender).catch((err) => toast(`保存失败：${err.message}`, true));

    const presetInput = el("input", { type: "text", value: st.preset, placeholder: `沿用全局（${st.globalPreset || "不切编队"}）` });
    presetInput.addEventListener("change", () => commit(`${scope}编队`, presetInput.value.trim()));
    card.append(el("div", { class: "lineup-row" },
      el("div", { class: "f-label", text: "编队" }),
      el("div", { class: "f-desc", text: "整备室配置里的编队名，留空沿用全局" }),
      el("div", { class: "f-ctl" }, presetInput)));

    if (st.support !== null) {
      const seg = el("div", { class: "seg" });
      const choices = [[SUPPORT_INHERIT, `沿用全局（${st.globalSupport ? "开" : "关"}）`], ["开", "开"], ["关", "关"]];
      for (const [value, label] of choices) {
        seg.append(el("button", { class: "seg-btn" + (st.support === value ? " on" : ""), text: label, onclick: () => commit(`${scope}助战`, value) }));
      }
      card.append(el("div", { class: "lineup-row" },
        el("div", { class: "f-label", text: "借好友助战" }),
        el("div", { class: "f-desc", text: `这一场景实际：${st.effectiveSupport ? "借" : "不借"}` }),
        el("div", { class: "f-ctl" }, seg)));
    }
    return card;
  }

  // 日常任务里没被任何板块/全局区收编的键，自动收进「其它」组，保证一项都不丢
  function ensureLeftoverEntry() {
    const cat = state.catalog;
    const daily = taskByClass(cat.daily_task);
    if (!daily) return;
    const covered = new Set();
    for (const g of cat.groups) for (const e of g.entries) {
      if (e.task !== cat.daily_task) continue;
      if (e.enable_key) covered.add(e.enable_key);
      if (Array.isArray(e.keys)) e.keys.forEach((k) => covered.add(k));
    }
    for (const s of cat.global_sections) if (s.task === cat.daily_task) s.keys.forEach((k) => covered.add(k));
    const leftover = daily.config.map((f) => f.key).filter((k) => !covered.has(k));
    let other = cat.groups.find((g) => g.id === "_other");
    if (!leftover.length) { if (other) cat.groups = cat.groups.filter((g) => g !== other); return; }
    if (!other) {
      other = { id: "_other", label: "其它日常选项", icon: "📦", desc: "目录里还没归类的日常配置项。", entries: [] };
      cat.groups.push(other);
    }
    other.entries = [{ id: "_other", label: "未归类的选项", task: cat.daily_task, enable_key: null, keys: leftover, doc: "这些键在 catalog.json 里还没分到板块，先放在这里，不会丢。" }];
  }

  // ---------- 任务列表 ----------
  function dailyInfo() {
    const daily = taskByClass(state.catalog.daily_task);
    const info = (daily && daily.info) || {};
    const findList = (needle) => {
      const k = Object.keys(info).find((x) => x.includes(needle));
      return Array.isArray(info[k]) ? info[k] : [];
    };
    return { done: findList("今日已完成"), retry: findList("今日待重试"), current: info.current_task, raw: info };
  }

  function renderGroups() {
    const wrap = $("#group-list");
    const collapsed = new Set(JSON.parse(localStorage.getItem("v2.collapsed") || "[]"));
    wrap.replaceChildren();
    const di = dailyInfo();
    for (const g of state.catalog.groups) {
      const group = el("div", { class: "group" + (collapsed.has(g.id) ? " collapsed" : "") });
      const head = el("div", { class: "group-head", title: g.desc || "" },
        el("span", { class: "chev", text: "▼" }),
        el("span", { text: `${g.icon || ""} ${g.label}` }),
        el("span", { class: "count", text: `${g.entries.length} 项` }));
      head.addEventListener("click", () => {
        group.classList.toggle("collapsed");
        if (group.classList.contains("collapsed")) collapsed.add(g.id); else collapsed.delete(g.id);
        localStorage.setItem("v2.collapsed", JSON.stringify([...collapsed]));
      });
      group.append(head);
      const entries = el("div", { class: "entries" });
      for (const e of g.entries) entries.append(renderEntry(e, di));
      group.append(entries);
      wrap.append(group);
    }
  }

  function renderEntry(e, di) {
    const task = taskByClass(e.task);
    const row = el("div", { class: "entry" + (state.selected && state.selected.id === e.id ? " selected" : "") });
    if (e.enable_key && task) {
      const f = fieldOf(task, e.enable_key);
      const cb = el("input", { type: "checkbox" });
      cb.checked = !!(f && f.value);
      cb.disabled = !f;
      cb.addEventListener("click", (ev) => ev.stopPropagation());
      cb.addEventListener("change", () => setTaskConfig(task, e.enable_key, cb.checked));
      row.append(cb);
    } else {
      row.append(el("span", { class: "spacer" }));
    }
    row.append(el("span", { class: "label", text: e.label }));
    if (!task) row.append(el("span", { class: "tag", text: "未注册" }));
    else if (task.class_name !== state.catalog.daily_task) {
      if (task.running) row.append(el("span", { class: "tag running", text: task.paused ? "已暂停" : "运行中" }));
      else if (task.trigger) row.append(el("span", { class: "tag" + (task.enabled ? " done" : ""), text: task.enabled ? "已启用" : "触发任务" }));
      else row.append(el("span", { class: "tag", text: "独立任务" }));
    } else if (e.enable_key) {
      if (di.done.includes(e.enable_key)) row.append(el("span", { class: "tag done", text: "今日已完成" }));
      else if (di.retry.includes(e.enable_key)) row.append(el("span", { class: "tag retry", text: "待重试" }));
    }
    row.addEventListener("click", () => selectEntry(e));
    return row;
  }

  function selectEntry(e) {
    state.selected = e;
    localStorage.setItem("v2.selected", e.id);
    renderGroups();
    renderOptions();
    updateStartButton();
  }

  // ---------- 选项面板 ----------
  function renderOptions() {
    const panel = $("#option-panel");
    const e = state.selected;
    panel.replaceChildren();
    if (!e) { panel.append(el("p", { class: "muted", text: "在左侧选一个任务项查看它的选项。" })); $("#option-title").textContent = "选项"; return; }
    const task = taskByClass(e.task);
    $("#option-title").textContent = e.label;
    if (!task) { panel.append(el("p", { class: "muted", text: `任务类 ${e.task} 没有注册，无法显示选项。` })); return; }
    if (e.doc) panel.append(el("div", { class: "option-doc", text: e.doc }));
    else if (task.description && task.class_name !== state.catalog.daily_task) panel.append(el("div", { class: "option-doc", text: task.description }));

    const actions = el("div", { class: "option-actions" });
    if (task.class_name === state.catalog.daily_task) {
      actions.append(el("span", { class: "muted", text: "属于「一键日常」，顶部「开始」会按勾选项整轮执行。" }));
    } else if (task.trigger) {
      actions.append(el("button", { class: "btn small", text: task.enabled ? "停用触发" : "启用触发", onclick: () => taskAction(task, task.enabled ? "disable" : "enable") }));
    } else {
      actions.append(el("button", { class: "btn small primary", text: `▶ 运行「${task.name}」`, onclick: () => startTask(task) }));
    }
    actions.append(el("button", { class: "btn small ghost", text: "恢复默认", onclick: () => resetTaskConfig(task, e) }));
    panel.append(actions);

    const keys = e.keys === "*" ? task.config.map((f) => f.key) : [...(e.enable_key ? [e.enable_key] : []), ...(e.keys || [])];
    let shown = 0;
    for (const key of keys) {
      const f = fieldOf(task, key);
      if (!f) continue;   // 被联动隐藏，或键不存在
      panel.append(renderField(f, (value) => setTaskConfig(task, key, value), key !== e.enable_key && f.sub_config));
      shown++;
    }
    for (const scope of e.lineup_scopes || []) {
      const card = renderLineupCard(scope, renderOptions);
      if (card) { panel.append(card); shown++; }
    }
    if (!shown) panel.append(el("p", { class: "muted", text: "这一项没有可调的选项。" }));
  }

  function renderField(f, onChange, sub) {
    const field = el("div", { class: "field" + (sub ? " sub" : "") });
    field.append(el("div", { class: "f-label", text: f.key }));
    if (f.description) field.append(el("div", { class: "f-desc", text: f.description }));
    const ctl = el("div", { class: "f-ctl" });
    const commit = (v) => onChange(v).catch((err) => toast(`保存失败：${err.message}`, true));
    switch (f.kind) {
      case "boolean": {
        const input = el("input", { type: "checkbox" });
        input.checked = !!f.value;
        input.addEventListener("change", () => commit(input.checked));
        ctl.append(el("label", { class: "switch" }, input, el("span", { class: "track" })));
        break;
      }
      case "integer":
      case "number": {
        const input = el("input", { type: "number", value: f.value ?? "" });
        if (f.minimum !== null && f.minimum !== undefined) input.min = f.minimum;
        if (f.maximum !== null && f.maximum !== undefined) input.max = f.maximum;
        if (f.kind === "number") input.step = "any";
        input.addEventListener("change", () => commit(f.kind === "integer" ? parseInt(input.value, 10) : parseFloat(input.value)));
        ctl.append(input);
        break;
      }
      case "select": {
        const sel = el("select");
        for (const o of f.options || []) sel.append(el("option", { value: String(o), text: String(o) }));
        sel.value = String(f.value);
        sel.addEventListener("change", () => commit(sel.value));
        ctl.append(sel);
        break;
      }
      case "multi_selection":
      case "list": {
        if (Array.isArray(f.options) && f.options.length) {
          const box = el("div", { class: "multi" });
          const current = new Set(Array.isArray(f.value) ? f.value : []);
          for (const o of f.options) {
            const cb = el("input", { type: "checkbox" });
            cb.checked = current.has(o);
            cb.addEventListener("change", () => { cb.checked ? current.add(o) : current.delete(o); commit([...current]); });
            box.append(el("label", {}, cb, " ", String(o)));
          }
          ctl.append(box);
        } else {
          const ta = el("textarea", { text: Array.isArray(f.value) ? f.value.join("\n") : "" });
          ta.addEventListener("change", () => commit(ta.value.split("\n").map((s) => s.trim()).filter(Boolean)));
          ctl.append(ta);
        }
        break;
      }
      case "multiline": {
        const ta = el("textarea", { text: f.value ?? "" });
        ta.addEventListener("change", () => commit(ta.value));
        ctl.append(ta);
        break;
      }
      default: {
        const input = el("input", { type: f.key.includes("密码") ? "password" : "text", value: f.value ?? "" });
        input.addEventListener("change", () => commit(input.value));
        ctl.append(input);
      }
    }
    field.append(ctl);
    return field;
  }

  async function setTaskConfig(task, key, value) {
    const updated = await post(`${taskPath(task)}/config`, { key, value });
    const idx = state.tasks.findIndex((t) => t.class_name === updated.class_name);
    if (idx >= 0) state.tasks[idx] = updated;
    ensureLeftoverEntry();
    renderGroups();
    renderOptions();
  }
  async function resetTaskConfig(task, e) {
    if (!confirm(`把「${task.name}」的全部选项恢复默认？（包括其它板块里属于它的项）`)) return;
    try {
      await post(`${taskPath(task)}/config/reset`);
      await refreshTasks(); renderGroups(); renderOptions(); toast("已恢复默认");
    } catch (err) { toast(`失败：${err.message}`, true); }
  }
  async function taskAction(task, action) {
    try { await post(`${taskPath(task)}/action`, { action }); await refreshAll(); }
    catch (err) { toast(`失败：${err.message}`, true); }
  }

  // ---------- 预设 ----------
  function renderPresets() {
    const bar = $("#preset-bar");
    bar.replaceChildren();
    for (const p of state.catalog.presets || []) {
      bar.append(el("button", { class: "btn small", text: p.label, title: p.desc || "", onclick: () => applyPreset(p) }));
    }
  }
  async function applyPreset(p) {
    const daily = taskByClass(state.catalog.daily_task);
    if (!daily) return toast("一键日常任务没有注册", true);
    const want = new Set(p.entries);
    let changed = 0;
    try {
      for (const g of state.catalog.groups) for (const e of g.entries) {
        if (e.task !== state.catalog.daily_task || !e.enable_key) continue;
        const f = fieldOf(daily, e.enable_key);
        const target = want.has(e.id);
        if (f && !!f.value !== target) { await post(`${taskPath(daily)}/config`, { key: e.enable_key, value: target }); changed++; }
      }
      await refreshTasks(); renderGroups(); renderOptions();
      toast(`已应用「${p.label}」，改了 ${changed} 项`);
    } catch (err) { toast(`应用预设失败：${err.message}`, true); }
  }

  // ---------- 运行控制 ----------
  function startTarget() {
    const e = state.selected;
    const cls = e ? e.task : state.catalog.daily_task;
    const task = taskByClass(cls);
    if (task && task.trigger) return taskByClass(state.catalog.daily_task);
    return task || taskByClass(state.catalog.daily_task);
  }
  function updateStartButton() {
    const t = startTarget();
    const btn = $("#btn-start");
    btn.textContent = t ? `▶ 开始「${t.name}」` : "▶ 开始";
    const running = state.status && state.status.running && state.status.current_task;
    btn.disabled = !t || !!running;
    $("#btn-pause").textContent = state.status && state.status.paused ? "▶ 继续" : "⏸ 暂停";
  }
  async function startTask(task) {
    try { await post(`${taskPath(task)}/start`); toast(`已启动「${task.name}」`); await refreshAll(); }
    catch (err) { toast(`启动失败：${err.message}`, true); }
  }
  $("#btn-start").addEventListener("click", () => { const t = startTarget(); if (t) startTask(t); });
  $("#btn-stop").addEventListener("click", async () => {
    try { await post("/api/executor/stop-task"); toast("已发送停止"); await refreshAll(); }
    catch (err) { toast(`停止失败：${err.message}`, true); }
  });
  $("#btn-pause").addEventListener("click", async () => {
    try {
      if (state.status && state.status.paused) await post("/api/executor/resume"); else await post("/api/executor/pause");
      await refreshAll();
    } catch (err) { toast(`操作失败：${err.message}`, true); }
  });

  // ---------- 状态 ----------
  function renderStatus() {
    const s = state.status || {};
    const dot = $("#state-dot");
    const running = s.running && s.current_task;
    dot.className = "dot" + (s.paused ? " paused" : running ? " running" : "");
    $("#state-text").textContent = s.paused ? "已暂停" : running ? `运行中：${s.current_task}` : s.starting ? "正在启动…" : "空闲";
    const panel = $("#status-panel");
    panel.replaceChildren();
    const row = (k, v) => panel.append(el("div", { class: "status-row" }, el("b", { text: k }), el("span", { text: v })));
    row("执行器", s.paused ? "暂停" : s.running ? "运行" : "停止");
    row("当前任务", s.current_task || "无");
    const di = dailyInfo();
    const skip = new Set(["今日已完成(含之前几次)", "今日待重试"]);
    for (const [k, v] of Object.entries(di.raw)) {
      if (skip.has(k)) continue;
      row(k, Array.isArray(v) ? v.join("、") : String(v));
    }
    if (di.done.length) row("今日已完成", di.done.join("、"));
    if (di.retry.length) row("今日待重试", di.retry.join("、"));
    updateStartButton();
  }

  // ---------- 日志 ----------
  const LOG_NOISE = /ocr_zone|detected but no match|emit_draw|find_feature|DEBUG|wait_until timeout/;
  async function pollLogs() {
    try {
      const level = $("#log-level").value;
      const query = $("#log-query").value.trim();
      const data = await get(`/api/logs?level=${encodeURIComponent(level)}&query=${encodeURIComponent(query)}`);
      const lines = (data.text || "").split("\n").filter(Boolean);
      const tail = lines.filter((l) => !LOG_NOISE.test(l)).slice(-60).map(trimLog);
      const tailEl = $("#log-tail");
      tailEl.textContent = tail.join("\n");
      tailEl.scrollTop = tailEl.scrollHeight;
      if (state.page === "logs") {
        const full = $("#log-full");
        full.textContent = lines.slice(-2000).join("\n");
        if ($("#log-follow").checked) full.scrollTop = full.scrollHeight;
      }
    } catch (_) { /* 后端没起来时静默 */ }
  }
  function trimLog(line) {
    // 2026-10-19 23:31:13,580 INFO TaskExecutor DailyTask:xxx → 23:31:13 xxx
    const m = line.match(/^\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d),\d+ (\w+) \S+ (?:\S+?:)?(.*)$/);
    return m ? `${m[1]} ${m[2] === "INFO" ? "" : m[2] + " "}${m[3]}` : line;
  }
  $("#log-query").addEventListener("keydown", (ev) => { if (ev.key === "Enter") pollLogs(); });
  $("#log-level").addEventListener("change", pollLogs);

  // ---------- 画面 ----------
  async function captureOnce() {
    try {
      const r = await post("/api/tools/capture");
      $("#capture-img").src = r.resource_url || `/api/capture/image?t=${Date.now()}`;
      $("#capture-msg").textContent = new Date().toLocaleTimeString();
    } catch (err) { $("#capture-msg").textContent = `抓帧失败：${err.message}`; }
  }
  $("#btn-capture").addEventListener("click", captureOnce);
  $("#capture-auto").addEventListener("change", (ev) => {
    clearInterval(state.captureTimer);
    if (ev.target.checked) { captureOnce(); state.captureTimer = setInterval(captureOnce, 3000); }
  });

  // ---------- 全局设置 ----------
  function renderSettings() {
    const wrap = $("#settings-wrap");
    wrap.replaceChildren();
    for (const sec of state.catalog.global_sections || []) {
      const task = taskByClass(sec.task);
      if (!task) continue;
      const card = el("div", { class: "settings-card" }, el("h3", { text: sec.label }));
      if (sec.desc) card.append(el("div", { class: "s-desc", text: sec.desc }));
      for (const key of sec.keys) {
        const f = fieldOf(task, key);
        if (f) card.append(renderField(f, (v) => setTaskConfig(task, key, v).then(renderSettings), f.sub_config));
      }
      wrap.append(card);
    }
    for (const g of state.settings) {
      const card = el("div", { class: "settings-card" }, el("h3", { text: g.name }));
      if (g.description) card.append(el("div", { class: "s-desc", text: g.description }));
      const isLineup = g.name === LINEUP_GROUP;
      for (const f of g.fields) {
        if (isLineup && isScopeKey(f.key)) continue;
        card.append(renderField(f, async (v) => {
          const updated = await post(`/api/settings/${encodeURIComponent(g.name)}/config`, { key: f.key, value: v });
          const idx = state.settings.findIndex((x) => x.name === updated.name);
          if (idx >= 0) state.settings[idx] = updated;
          renderSettings();
        }, f.sub_config));
      }
      if (isLineup) card.append(renderScopeTable());
      wrap.append(card);
    }
  }

  function entryOfScope(scope) {
    return state.catalog.groups.flatMap((g) => g.entries).find((e) => (e.lineup_scopes || []).includes(scope));
  }

  function renderScopeTable() {
    const box = el("div", { class: "scope-table" }, el("div", { class: "f-label", text: "各场景单独设置" }),
      el("div", { class: "f-desc", text: "在任务页对应板块的「阵容」卡片里改；这里一览哪些场景和全局不一样。" }));
    const table = el("table");
    table.append(el("tr", {}, el("th", { text: "场景" }), el("th", { text: "编队" }), el("th", { text: "借助战" }), el("th", { text: "" })));
    for (const scope of lineupScopes()) {
      const st = scopeState(scope);
      const presetCell = st.preset ? el("td", { class: "own", text: st.preset }) : el("td", { class: "muted", text: `沿用（${st.globalPreset || "不切"}）` });
      const supportCell = st.support === null ? el("td", { class: "muted", text: "—" })
        : st.support === SUPPORT_INHERIT ? el("td", { class: "muted", text: `沿用（${st.globalSupport ? "开" : "关"}）` })
        : el("td", { class: "own", text: st.support });
      const ops = el("td", {});
      const entry = entryOfScope(scope);
      if (entry) ops.append(el("button", { class: "btn small ghost", text: "去设置", onclick: () => { showPage("tasks"); selectEntry(entry); } }));
      if (st.overridden) ops.append(el("button", { class: "btn small ghost", text: "恢复全局", onclick: () => resetScope(scope).then(renderSettings).catch((err) => toast(`保存失败：${err.message}`, true)) }));
      table.append(el("tr", { class: st.overridden ? "overridden" : "" }, el("td", { text: scope }), presetCell, supportCell, ops));
    }
    box.append(table);
    return box;
  }

  // ---------- 页面切换 ----------
  for (const btn of document.querySelectorAll(".nav-item")) {
    btn.addEventListener("click", () => showPage(btn.dataset.page));
  }
  function showPage(name) {
    state.page = name;
    for (const b of document.querySelectorAll(".nav-item")) b.classList.toggle("active", b.dataset.page === name);
    for (const p of document.querySelectorAll(".page")) p.classList.toggle("active", p.id === `page-${name}`);
    if (name === "settings") refreshSettings().then(renderSettings).catch((e) => toast(e.message, true));
    if (name === "logs") pollLogs();
  }

  // ---------- 事件推送 ----------
  function connectEvents() {
    if (!state.eventKey) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/events?session_key=${encodeURIComponent(state.eventKey)}`);
    let pending = null;
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (["task", "task_list_updated", "executor_paused", "starting_emulator"].includes(data.event)) {
          clearTimeout(pending);
          pending = setTimeout(() => refreshAll().catch(() => {}), 300);
        }
      } catch (_) { /* ignore */ }
    };
    ws.onclose = () => setTimeout(connectEvents, 3000);
  }

  async function refreshAll() {
    await Promise.all([refreshTasks(), refreshStatus(), refreshSettings()]);
    renderGroups(); renderOptions(); renderStatus();
  }

  // ---------- 启动 ----------
  async function init() {
    try {
      state.catalog = await get("/v2/catalog.json");
      const ui = await get("/api/ui/capture");
      state.eventKey = ui.event_session_key;
      document.title = `${ui.title || "ok-gf2"} · 新版界面（测试）`;
      await refreshAll();
      renderPresets();
      const remembered = localStorage.getItem("v2.selected");
      const all = state.catalog.groups.flatMap((g) => g.entries);
      selectEntry(all.find((e) => e.id === remembered) || all[0]);
      connectEvents();
      pollLogs();
      state.logTimer = setInterval(() => { pollLogs(); refreshStatus().then(renderStatus).catch(() => {}); }, 2000);
    } catch (err) {
      $("#state-text").textContent = `连不上后端：${err.message}`;
      $("#state-dot").className = "dot error";
    }
  }
  init();
})();
