/* MyMeeting front end: history sidebar, new-note composer, note view. No dependencies. */
(function () {
  "use strict";

  /* ======================================================================
     Helpers
     ====================================================================== */
  const $ = (selector, root = document) => root.querySelector(selector);
  const body = document.body;
  const ALLOWED = (body.dataset.exts || "").split(",").filter(Boolean);
  const MAX_MB = Number(body.dataset.maxMb) || 300;

  const view = $("#view");
  const scrollEl = $("#scroll");
  const historyEl = $("#history");
  const searchInput = $("#search");
  const fileInput = $("#file-input");

  /** Build a DOM element. Text is always inserted as text, never as HTML. */
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value == null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    paperclip: '<path d="m21 11-8.6 8.6a5 5 0 0 1-7-7L14 4a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4L15 7"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 14h6M9 17h4"/>',
    audio: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    loader: '<path d="M12 3a9 9 0 1 0 9 9"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
    pencil: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    calendar: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14-4L4 9M4 4v5h5M4 13a8 8 0 0 0 14 4l2-2M20 20v-5h-5"/>',
  };

  function icon(name, size = 18) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = ICONS[name] || "";
    return svg;
  }

  const pad = (n) => String(n).padStart(2, "0");
  function fmtTs(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  }
  function fmtDur(sec) {
    sec = Math.round(sec || 0);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (h) return `${h} h ${pad(m)} min`;
    if (m) return `${m} min ${pad(s)} s`;
    return `${s} s`;
  }
  function fmtSize(bytes) {
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  const LANGUAGE_NAMES = {
    en: "English", es: "Spanish", fr: "French", de: "German", it: "Italian", pt: "Portuguese",
    nl: "Dutch", ja: "Japanese", zh: "Chinese", ko: "Korean", hi: "Hindi", ar: "Arabic",
    ru: "Russian", tr: "Turkish", pl: "Polish", sv: "Swedish", uk: "Ukrainian", vi: "Vietnamese",
  };
  function langName(code) {
    if (!code) return "";
    try {
      const name = new Intl.DisplayNames([navigator.language || "en"], { type: "language" }).of(code);
      if (name && name.toLowerCase() !== code.toLowerCase()) return name;
    } catch (_) { /* fall through to the built-in list */ }
    return LANGUAGE_NAMES[code] || code.toUpperCase();
  }
  const isActive = (note) => note && (note.status === "queued" || note.status === "processing");

  function toast(message, kind) {
    const node = el("div", { class: "toast" + (kind === "error" ? " error" : "") }, message);
    $("#toasts").append(node);
    setTimeout(() => node.remove(), kind === "error" ? 5000 : 2600);
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    let data = null;
    try { data = await res.json(); } catch (_) { /* not JSON */ }
    if (!res.ok) throw new Error((data && data.error) || `The request failed (${res.status}).`);
    return data;
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (_) {
      const area = el("textarea", { style: "position:fixed;opacity:0" });
      area.value = text;
      document.body.append(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
      area.remove();
      return ok;
    }
  }

  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(localStorage.getItem(key));
      localStorage.setItem(key, JSON.stringify(value));
    } catch (_) { /* storage unavailable */ }
    return null;
  }

  /* ======================================================================
     State
     ====================================================================== */
  const state = {
    notes: [],
    currentId: null,
    current: null,
    tab: "notes",
    search: "",
    file: null,
    submitting: false,
    rec: null,
    pollTimer: null,
    historySig: "",
    statusSeen: {},
    audio: null,
    rows: [],
    proc: null,
    composer: null,
  };

  /* ======================================================================
     Dialog
     ====================================================================== */
  const dlg = $("#dialog");
  function openDialog({ title, message = "", input = null, ok = "OK", danger = false }) {
    return new Promise((resolve) => {
      const form = $("#dialog-form"), field = $("#dialog-input");
      $("#dialog-title").textContent = title;
      $("#dialog-message").textContent = message;
      $("#dialog-ok").textContent = ok;
      dlg.classList.toggle("danger", danger);
      field.hidden = input === null;
      if (input !== null) field.value = input;

      const finish = (value) => {
        form.removeEventListener("submit", onSubmit);
        $("#dialog-cancel").removeEventListener("click", onCancel);
        dlg.removeEventListener("cancel", onCancel);
        if (dlg.open) dlg.close();
        resolve(value);
      };
      const onSubmit = (e) => { e.preventDefault(); finish(input === null ? true : field.value.trim() || null); };
      const onCancel = (e) => { if (e) e.preventDefault(); finish(input === null ? false : null); };
      form.addEventListener("submit", onSubmit);
      $("#dialog-cancel").addEventListener("click", onCancel);
      dlg.addEventListener("cancel", onCancel);
      dlg.showModal();
      if (input !== null) field.select(); else $("#dialog-ok").focus();
    });
  }

  /* ======================================================================
     Sidebar: history
     ====================================================================== */
  function bucketOf(iso) {
    const d = new Date(iso), now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
    const diff = Math.round((day(now) - day(d)) / 86400000);
    if (diff <= 0) return "Today";
    if (diff === 1) return "Yesterday";
    if (diff < 8) return "Previous 7 days";
    if (diff < 31) return "Previous 30 days";
    return "Older";
  }

  function shortWhen(iso, bucket) {
    const d = new Date(iso);
    if (bucket === "Today" || bucket === "Yesterday") return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function historyItem(note, bucket) {
    const active = isActive(note);
    let sub;
    if (active) sub = `${note.stage || "Working"} ${Math.round(note.progress || 0)}%`;
    else if (note.status === "failed") sub = "Needs attention";
    else sub = [shortWhen(note.created_at, bucket), note.duration ? fmtDur(note.duration) : ""].filter(Boolean).join(", ");

    const ico = icon(active ? "loader" : note.status === "failed" ? "alert" : "audio", 17);
    if (active) ico.classList.add("spin");

    const stop = (fn) => (e) => { e.preventDefault(); e.stopPropagation(); fn(); };
    return el("a", {
      class: "hist-item" + (note.id === state.currentId ? " active" : "") + (note.status === "failed" ? " failed" : ""),
      href: `#/note/${note.id}`,
      title: note.title,
      "data-id": note.id,
    },
      el("span", { class: "hist-ico" }, ico),
      el("span", { class: "hist-text" },
        el("span", { class: "hist-title" }, note.title),
        el("span", { class: "hist-sub" }, sub)),
      el("span", { class: "hist-actions" },
        el("button", { class: "mini-btn", type: "button", title: "Rename", "aria-label": `Rename ${note.title}`, onclick: stop(() => renameNote(note.id, note.title)) }, icon("pencil", 14)),
        el("button", { class: "mini-btn danger", type: "button", title: "Delete", "aria-label": `Delete ${note.title}`, onclick: stop(() => deleteNote(note.id, note.title)) }, icon("trash", 14))),
      active ? el("span", { class: "hist-bar" }, el("span", { style: `width:${note.progress || 0}%` })) : null);
  }

  function renderHistory(force) {
    const sig = JSON.stringify(state.notes.map((n) => [n.id, n.title, n.status, Math.round(n.progress || 0), n.stage, n.duration])) + state.currentId;
    if (!force && sig === state.historySig) return;
    state.historySig = sig;
    historyEl.replaceChildren();
    if (!state.notes.length) {
      historyEl.append(el("p", { class: "hist-empty" }, state.search ? "No notes match that search." : "Your notes will show up here. Upload a recording to create the first one."));
      return;
    }
    let last = null;
    for (const note of state.notes) {
      const bucket = bucketOf(note.created_at);
      if (bucket !== last) { historyEl.append(el("div", { class: "hist-group" }, bucket)); last = bucket; }
      historyEl.append(historyItem(note, bucket));
    }
  }

  async function refreshList() {
    const q = state.search ? `?q=${encodeURIComponent(state.search)}` : "";
    const data = await api(`/api/notes${q}`);
    // Tell the person when a note finishes while they are looking at something else.
    for (const n of data.notes) {
      const before = state.statusSeen[n.id];
      if (before && (before === "queued" || before === "processing") && n.status === "done" && n.id !== state.currentId) {
        toast(`Notes are ready: ${n.title}`);
      }
      state.statusSeen[n.id] = n.status;
    }
    state.notes = data.notes;
    renderHistory();
    ensurePolling();
  }

  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.search = searchInput.value.trim(); refreshList().catch(() => {}); }, 220);
  });

  /* ======================================================================
     Polling for notes that are still being processed
     ====================================================================== */
  function ensurePolling() {
    const needed = state.notes.some(isActive) || isActive(state.current);
    if (needed && !state.pollTimer) state.pollTimer = setInterval(pollTick, 1500);
    if (!needed && state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  async function pollTick() {
    try {
      await refreshList();
      if (state.currentId && isActive(state.current)) {
        const fresh = await api(`/api/notes/${state.currentId}`);
        if (fresh.id === state.currentId) applyUpdate(fresh);
      }
    } catch (_) { /* transient; try again on the next tick */ }
    ensurePolling();
  }

  function applyUpdate(fresh) {
    const before = state.current;
    state.current = fresh;
    if (!before || before.status !== fresh.status) {
      renderNote(fresh);
      if (fresh.status === "done") toast("Your notes are ready.");
    } else if (isActive(fresh)) {
      updateProgress(fresh);
    }
  }

  /* ======================================================================
     Routing
     ====================================================================== */
  function route() {
    closeSidebar();
    cancelRecording();
    const match = location.hash.match(/^#\/note\/([0-9a-f]+)/);
    if (match) openNote(match[1]); else showNew();
  }
  window.addEventListener("hashchange", route);

  function setPageTitle(text) { document.title = text ? `${text} | MyMeeting` : "MyMeeting"; }

  /* ======================================================================
     New note view
     ====================================================================== */
  const HERO_BARS = [14, 24, 40, 28, 54, 70, 38, 22, 62, 78, 50, 32, 70, 44, 26, 58, 74, 36, 22, 52, 66, 30, 18, 44, 60, 34, 24, 14];
  const HERO_HL = new Set([9, 15, 21]);

  function showNew() {
    state.currentId = null;
    state.current = null;
    state.audio = null;
    state.proc = null;
    setPageTitle("");
    renderHistory(true);
    scrollEl.scrollTop = 0;

    const attach = el("div", { class: "attach-row" });
    const input = el("textarea", {
      class: "composer-input", rows: "2", maxlength: "1000", "aria-label": "Meeting context (optional)",
      placeholder: "Add context (optional): who was in the meeting, the project, or what to focus on",
    });
    input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submitNew(); } });

    const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    const attachBtn = el("button", { class: "tool-btn", type: "button", onclick: () => fileInput.click() }, icon("paperclip", 17), el("span", { class: "label" }, "Attach recording"));
    const recBtn = canRecord ? el("button", { class: "tool-btn", type: "button", onclick: startRecording }, icon("mic", 17), el("span", { class: "label" }, "Record")) : null;
    const sendBtn = el("button", { class: "send-btn", type: "button", "aria-label": "Create notes", title: "Create notes", onclick: submitNew }, icon("send", 20));

    state.composer = { attach, input, sendBtn, attachBtn, recBtn };

    view.replaceChildren(el("div", { class: "new-view" },
      el("section", { class: "hero" },
        el("div", { class: "hero-wave", "aria-hidden": "true" },
          HERO_BARS.map((h, i) => el("i", { class: HERO_HL.has(i) ? "hl" : "", style: `--h:${h}px;--i:${i}` }))),
        el("h1", null, "Upload a meeting. Get notes you can act on."),
        el("p", { class: "hero-sub" }, "MyMeeting transcribes your recording, then writes the summary, decisions and action items. It all runs on this computer."),
        el("div", { class: "hero-actions" },
          el("button", { class: "btn primary", type: "button", onclick: () => fileInput.click() }, icon("upload", 18), "Upload recording"),
          canRecord ? el("button", { class: "btn", type: "button", onclick: startRecording }, icon("mic", 18), "Record audio") : null),
        el("div", { class: "outputs" },
          el("span", null, "Summary"), el("span", null, "Decisions"), el("span", { class: "hl" }, "Action items"),
          el("span", null, "Topic timeline"), el("span", null, "Searchable transcript"))),
      el("div", { class: "composer-wrap" },
        el("div", { class: "composer" },
          attach, input,
          el("div", { class: "composer-bar" }, attachBtn, recBtn, el("span", { class: "composer-hint" }, "Ctrl+Enter to create"), sendBtn)),
        el("p", { class: "fineprint" }, "MyMeeting uses small open-source models and can make mistakes. Check names, numbers and dates against the transcript."))));
    updateComposer();
  }

  function updateComposer() {
    const c = state.composer;
    if (!c || !c.attach.isConnected) return;
    c.attach.replaceChildren();
    if (state.rec) {
      const time = el("span", { class: "rec-time" }, "0:00");
      state.rec.timeEl = time;
      c.attach.append(el("div", { class: "rec-bar" },
        el("span", { class: "rec-dot" }), time, el("span", { class: "grow" }, "Recording from your microphone"),
        el("button", { class: "btn small", type: "button", onclick: () => stopRecording(true) }, icon("stop", 16), "Stop")));
    } else if (state.file) {
      c.attach.append(el("div", { class: "file-chip" },
        el("span", { class: "file-ico" }, icon("audio", 18)),
        el("span", { class: "file-text" },
          el("div", { class: "file-name" }, state.file.name),
          el("div", { class: "file-size" }, fmtSize(state.file.size)),
          state.submitting ? el("div", { class: "upload-bar" }, el("span", { id: "upload-fill" })) : null),
        state.submitting ? null : el("button", { class: "mini-btn", type: "button", "aria-label": "Remove file", title: "Remove file", onclick: () => { state.file = null; updateComposer(); } }, icon("trash", 16))));
    }
    c.sendBtn.disabled = !state.file || state.submitting || !!state.rec;
    c.input.disabled = state.submitting;
    if (c.recBtn) c.recBtn.disabled = state.submitting || !!state.rec;
    c.attachBtn.disabled = state.submitting || !!state.rec;
  }

  function validateFile(file) {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED.includes(ext)) return `${ext === "." ? "That file" : ext} isn't a supported type. Use an audio or video recording such as MP3, WAV, M4A or MP4.`;
    if (file.size === 0) return "That file is empty. Choose a different recording.";
    if (file.size > MAX_MB * 1048576) return `That file is ${fmtSize(file.size)}. The limit is ${MAX_MB} MB.`;
    return null;
  }

  function setFile(file) {
    const problem = validateFile(file);
    if (problem) { toast(problem, "error"); return; }
    state.file = file;
    if (!state.composer || !state.composer.attach.isConnected) location.hash = "#/";
    if (!state.composer || !state.composer.attach.isConnected) showNew();
    updateComposer();
  }

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) setFile(fileInput.files[0]);
    fileInput.value = "";
  });

  function upload(formData, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/notes");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.error || `The upload failed (${xhr.status}).`));
      };
      xhr.onerror = () => reject(new Error("The upload failed. Check that MyMeeting is still running."));
      xhr.send(formData);
    });
  }

  async function submitNew() {
    if (!state.file || state.submitting) return;
    state.submitting = true;
    updateComposer();
    const form = new FormData();
    form.append("audio", state.file, state.file.name);
    form.append("context", state.composer.input.value.trim());
    const sendBtn = state.composer.sendBtn;
    sendBtn.classList.add("busy");
    try {
      const note = await upload(form, (fraction) => {
        const fill = $("#upload-fill");
        if (fill) fill.style.width = `${Math.round(fraction * 100)}%`;
        sendBtn.replaceChildren(`Uploading ${Math.round(fraction * 100)}%`);
      });
      state.file = null;
      state.submitting = false;
      state.statusSeen[note.id] = note.status;
      await refreshList().catch(() => {});
      location.hash = `#/note/${note.id}`;
    } catch (err) {
      state.submitting = false;
      sendBtn.classList.remove("busy");
      sendBtn.replaceChildren(icon("send", 20));
      updateComposer();
      toast(err.message, "error");
    }
  }

  /* ---------- Microphone recording ---------- */
  async function startRecording() {
    if (state.rec) return;
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (_) { toast("MyMeeting can't use the microphone. Allow microphone access in your browser, or upload a file instead.", "error"); return; }
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const rec = { recorder, stream, started: Date.now(), save: true, timeEl: null, timer: null };
    recorder.onstop = () => {
      clearInterval(rec.timer);
      stream.getTracks().forEach((t) => t.stop());
      state.rec = null;
      if (rec.save && chunks.length) {
        const type = recorder.mimeType || mime || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        const stamp = new Date().toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).replace(/[:,]/g, ".");
        state.file = new File(chunks, `Recording ${stamp}.${ext}`, { type });
      }
      updateComposer();
    };
    rec.timer = setInterval(() => {
      if (rec.timeEl) rec.timeEl.textContent = fmtTs((Date.now() - rec.started) / 1000);
    }, 500);
    state.rec = rec;
    state.file = null;
    recorder.start(1000);
    updateComposer();
  }
  function stopRecording(save) {
    if (!state.rec) return;
    state.rec.save = save;
    if (state.rec.recorder.state !== "inactive") state.rec.recorder.stop();
  }
  function cancelRecording() { stopRecording(false); }

  /* ---------- Drag and drop anywhere ---------- */
  const overlay = $("#drop-overlay");
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; overlay.classList.add("show"); } });
  window.addEventListener("dragleave", (e) => { if (hasFiles(e)) { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) overlay.classList.remove("show"); } });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove("show");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });

  /* ======================================================================
     Note view
     ====================================================================== */
  function loadingView() {
    view.replaceChildren(el("div", { class: "skeleton", "aria-busy": "true" }, el("i", { style: "width:60%;height:34px" }), el("i", { style: "width:35%" }), el("i"), el("i", { style: "width:90%" }), el("i", { style: "width:75%" })));
  }

  function messageView({ title, text, iconName = "alert", actions = [] }) {
    view.replaceChildren(el("div", { class: "msg-card" },
      el("div", { class: "icon-big" }, icon(iconName, 28)),
      el("h1", null, title),
      el("p", null, text),
      el("div", { class: "row" }, actions)));
  }

  async function openNote(id) {
    state.currentId = id;
    state.current = null;
    state.audio = null;
    state.proc = null;
    renderHistory(true);
    loadingView();
    scrollEl.scrollTop = 0;
    try {
      const note = await api(`/api/notes/${id}`);
      if (state.currentId !== id) return;
      state.current = note;
      state.statusSeen[note.id] = note.status;
      renderNote(note);
      ensurePolling();
    } catch (err) {
      if (state.currentId !== id) return;
      messageView({
        title: "Note not found", text: err.message,
        actions: [el("a", { class: "btn primary", href: "#/" }, icon("plus", 18), "New note")],
      });
    }
  }

  function renderNote(note) {
    state.proc = null;
    state.audio = null;
    setPageTitle(note.title);
    renderHistory(true);
    if (note.status === "done") renderDone(note);
    else if (note.status === "failed") renderFailed(note);
    else renderProgress(note);
    ensurePolling();
  }

  /* ---------- Processing ---------- */
  function renderProgress(note) {
    const steps = [
      el("li", { class: "step done" }, el("span", { class: "dot" }, icon("check", 13)), "Recording uploaded"),
      el("li", { class: "step", "data-step": "transcribe" }, el("span", { class: "dot" }), "Transcribing the audio"),
      el("li", { class: "step", "data-step": "notes" }, el("span", { class: "dot" }), "Writing the notes"),
    ];
    const stage = el("p", { class: "proc-stage" });
    const fill = el("span");
    const pct = el("p", { class: "pct" });
    state.proc = { stage, fill, pct, steps };
    view.replaceChildren(el("div", { class: "proc" },
      el("div", { class: "proc-wave", "aria-hidden": "true" }, Array.from({ length: 23 }, (_, i) => el("i", { style: `--i:${i}` }))),
      el("h1", null, "Creating your notes"),
      el("p", { class: "proc-file" }, note.filename),
      stage,
      el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100" }, fill),
      pct,
      el("ul", { class: "steps" }, steps),
      el("p", { class: "proc-hint" }, "Long recordings can take several minutes on a laptop. You can leave this page; the note stays in your history and finishes in the background.")));
    updateProgress(note);
  }

  function updateProgress(note) {
    const p = state.proc;
    if (!p) return;
    const value = Math.round(note.progress || 0);
    const stage = note.stage || "Working";
    p.stage.textContent = note.status === "queued"
      ? "Waiting for the previous recording to finish"
      : /^Loading/.test(stage) ? `${stage}. The first run downloads the model, which can take a few minutes.` : stage;
    p.fill.style.width = `${value}%`;
    p.fill.parentElement.setAttribute("aria-valuenow", String(value));
    p.pct.textContent = `${value}%`;
    const transcribing = value < 50;
    p.steps.forEach((step) => {
      const which = step.dataset.step;
      if (!which) return;
      const done = which === "transcribe" ? !transcribing : false;
      const active = which === "transcribe" ? transcribing && note.status === "processing" : !transcribing;
      step.className = "step" + (done ? " done" : active ? " active" : "");
      const dot = step.firstChild;
      dot.replaceChildren(done ? icon("check", 13) : "");
    });
  }

  /* ---------- Failure ---------- */
  function renderFailed(note) {
    setPageTitle(note.title);
    messageView({
      title: "These notes couldn't be created",
      text: note.error || "Something went wrong while processing the recording.",
      actions: [
        note.has_audio ? el("button", { class: "btn primary", type: "button", onclick: () => retryNote(note.id) }, icon("refresh", 18), "Retry") : null,
        el("button", { class: "btn danger", type: "button", onclick: () => deleteNote(note.id, note.title) }, icon("trash", 18), "Delete"),
      ],
    });
  }

  async function retryNote(id) {
    try {
      const note = await api(`/api/notes/${id}/retry`, { method: "POST" });
      state.current = note;
      renderNote(note);
      await refreshList();
    } catch (err) { toast(err.message, "error"); }
  }

  /* ---------- Finished note ---------- */
  function renderDone(note) {
    const n = note.notes || {};
    const hasAudio = note.has_audio;
    const seek = (sec) => {
      if (!state.audio) return;
      state.audio.currentTime = sec;
      state.audio.play().catch(() => {});
    };

    const titleEl = el("h1", { title: "Rename", tabindex: "0", role: "button", onclick: () => renameNote(note.id, note.title), onkeydown: (e) => { if (e.key === "Enter") renameNote(note.id, note.title); } }, note.title);

    const menu = el("div", { class: "menu", hidden: true },
      el("a", { href: `/api/notes/${note.id}/export?format=md&download=1` }, icon("download", 16), "Notes and transcript (.md)"),
      el("a", { href: `/api/notes/${note.id}/export?format=txt&download=1` }, icon("file", 16), "Transcript only (.txt)"),
      el("a", { href: `/api/notes/${note.id}/export?format=json&download=1` }, icon("file", 16), "Raw data (.json)"));
    const exportBtn = el("button", { class: "btn", type: "button", "aria-haspopup": "true", onclick: (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; } }, icon("download", 17), "Export", icon("chevron", 15));
    document.addEventListener("click", () => { menu.hidden = true; }, { once: true });

    const notesPanel = buildNotesPanel(note, n, seek);
    const transcriptPanel = buildTranscript(note, seek);
    const tabNotes = el("button", { class: "tab", role: "tab", type: "button", "aria-selected": "true" }, "Notes");
    const tabTranscript = el("button", { class: "tab", role: "tab", type: "button", "aria-selected": "false" }, "Transcript", el("small", null, String((note.transcript || []).length)));
    const select = (which) => {
      state.tab = which;
      tabNotes.setAttribute("aria-selected", String(which === "notes"));
      tabTranscript.setAttribute("aria-selected", String(which === "transcript"));
      notesPanel.hidden = which !== "notes";
      transcriptPanel.hidden = which !== "transcript";
    };
    tabNotes.addEventListener("click", () => select("notes"));
    tabTranscript.addEventListener("click", () => select("transcript"));

    const audio = hasAudio ? el("audio", { controls: true, preload: "metadata", src: `/api/notes/${note.id}/audio` }) : null;
    state.audio = audio;
    if (audio) audio.addEventListener("timeupdate", () => highlightRow(audio.currentTime));

    view.replaceChildren(el("article", { class: "note-view" },
      el("header", { class: "note-head" },
        titleEl,
        el("div", { class: "note-meta" },
          el("span", null, icon("calendar", 15), new Date(note.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })),
          el("span", null, icon("file", 15), note.filename)),
        el("div", { class: "note-actions" },
          el("button", { class: "btn", type: "button", onclick: async () => {
            try {
              const text = await (await fetch(`/api/notes/${note.id}/export?format=md`)).text();
              toast((await copyText(text)) ? "Notes copied" : "Couldn't copy. Use Export instead.", "");
            } catch (_) { toast("Couldn't copy the notes.", "error"); }
          } }, icon("copy", 17), "Copy notes"),
          el("div", { class: "menu-wrap" }, exportBtn, menu),
          el("span", { class: "spacer" }),
          el("button", { class: "btn ghost danger", type: "button", onclick: () => deleteNote(note.id, note.title) }, icon("trash", 17), "Delete"))),
      audio ? el("div", { class: "audio-card" }, audio) : null,
      el("div", { class: "tabs", role: "tablist" }, tabNotes, tabTranscript),
      notesPanel, transcriptPanel));
    select(state.tab);
  }

  function section(title, count, ...content) {
    return el("section", { class: "sec" }, el("h2", null, title, count ? el("span", { class: "count" }, String(count)) : null), content);
  }
  const pointList = (items, cls) => el("ul", { class: "points " + (cls || "") }, items.map((text) => el("li", null, text)));

  function buildNotesPanel(note, n, seek) {
    const panel = el("div", { role: "tabpanel" });
    if (!note.notes) { panel.append(el("p", { class: "t-empty" }, "No notes were generated for this recording.")); return panel; }

    const facts = [
      [note.duration ? fmtDur(note.duration) : "", "Length"],
      [(note.word_count || 0).toLocaleString(), "Words spoken"],
      [String((n.action_items || []).length), "Action items"],
      [String((n.decisions || []).length), "Decisions"],
      [langName(note.language), "Language"],
    ].filter(([value]) => value);
    panel.append(el("div", { class: "facts" }, facts.map(([value, label]) => el("div", { class: "fact" }, el("b", null, value), el("span", null, label)))));

    if (n.overview) panel.append(el("p", { class: "lead" }, n.overview));
    if ((n.key_points || []).length) panel.append(section("Key points", 0, pointList(n.key_points)));
    if ((n.decisions || []).length) panel.append(section("Decisions", n.decisions.length, pointList(n.decisions, "decisions")));

    if ((n.action_items || []).length) {
      const key = `mymeeting-checks-${note.id}`;
      const checked = new Set(store(key) || []);
      const list = el("ul", { class: "tasks" }, n.action_items.map((item, i) => {
        const box = el("input", { type: "checkbox", id: `task-${i}` });
        box.checked = checked.has(i);
        box.addEventListener("change", () => { box.checked ? checked.add(i) : checked.delete(i); store(key, [...checked]); });
        return el("li", { class: "task" },
          el("label", { for: `task-${i}` }, box, el("span", { class: "box" }, icon("check", 14)),
            el("span", { class: "body" },
              el("span", { class: "what" }, item.task),
              (item.owner || item.due) ? el("span", { class: "tags", style: "display:flex" },
                item.owner ? el("span", { class: "tag owner" }, icon("user", 13), item.owner) : null,
                item.due ? el("span", { class: "tag due" }, icon("calendar", 13), item.due) : null) : null)));
      }));
      panel.append(section("Action items", n.action_items.length, list));
    }

    if ((n.timeline || []).length) {
      panel.append(section("Discussion timeline", n.timeline.length, el("ol", { class: "rail" }, n.timeline.map((part) => {
        const stamp = note.has_audio
          ? el("button", { class: "stamp", type: "button", title: "Play from here", onclick: () => seek(part.start) }, fmtTs(part.start))
          : el("span", { class: "stamp" }, fmtTs(part.start));
        return el("li", { class: "rail-item" }, stamp,
          el("div", { class: "rail-body" },
            el("h3", null, part.title),
            part.summary ? el("p", null, part.summary) : null,
            (part.points || []).length ? pointList(part.points) : null));
      }))));
    }

    if ((n.questions || []).length) panel.append(section("Open questions", n.questions.length, pointList(n.questions, "questions")));
    panel.append(el("p", { class: "gen-note" }, `Written by ${(n.model || "an open-source model").split("/").pop()} from a Whisper ${n.whisper_model || ""} transcript. Check names, numbers and dates against the transcript.`));
    return panel;
  }

  function buildTranscript(note, seek) {
    const segments = note.transcript || [];
    const panel = el("div", { role: "tabpanel", hidden: true });
    const list = el("ol", { class: "transcript" });
    state.rows = segments.map((seg) => {
      const stamp = note.has_audio
        ? el("button", { class: "t-ts", type: "button", title: "Play from here", onclick: () => seek(seg.start) }, fmtTs(seg.start))
        : el("span", { class: "t-ts" }, fmtTs(seg.start));
      const row = el("li", { class: "t-row" }, stamp, el("span", { class: "t-text" }, seg.text));
      list.append(row);
      return { start: seg.start, end: seg.end, node: row, text: seg.text.toLowerCase() };
    });
    const empty = el("p", { class: "t-empty", hidden: true }, "No lines match that search.");
    const field = el("input", { type: "search", placeholder: "Search the transcript", "aria-label": "Search the transcript", autocomplete: "off" });
    field.addEventListener("input", () => {
      const q = field.value.trim().toLowerCase();
      let shown = 0;
      state.rows.forEach((r) => { const hit = !q || r.text.includes(q); r.node.hidden = !hit; if (hit) shown++; });
      empty.hidden = shown > 0;
    });
    panel.append(el("div", { class: "t-tools" }, el("label", { class: "search" }, icon("search", 16), field)), list, empty);
    return panel;
  }

  function highlightRow(time) {
    let active = null;
    for (const row of state.rows) { if (time >= row.start && time < row.end) { active = row; break; } }
    for (const row of state.rows) row.node.classList.toggle("active", row === active);
  }

  /* ---------- Rename and delete ---------- */
  async function renameNote(id, current) {
    const title = await openDialog({ title: "Rename note", input: current, ok: "Save" });
    if (!title || title === current) return;
    try {
      const note = await api(`/api/notes/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
      if (state.currentId === id && state.current) {
        state.current.title = note.title;
        const keepTab = state.tab;
        renderNote(state.current);
        state.tab = keepTab;
      }
      await refreshList();
      toast("Note renamed");
    } catch (err) { toast(err.message, "error"); }
  }

  async function deleteNote(id, title) {
    const ok = await openDialog({ title: "Delete this note?", message: `"${title}" and its recording will be removed from this computer. This can't be undone.`, ok: "Delete", danger: true });
    if (!ok) return;
    try {
      await api(`/api/notes/${id}`, { method: "DELETE" });
      store(`mymeeting-checks-${id}`, []);
      delete state.statusSeen[id];
      if (state.currentId === id) location.hash = "#/";
      await refreshList();
      toast("Note deleted");
    } catch (err) { toast(err.message, "error"); }
  }

  /* ======================================================================
     Theme and mobile sidebar
     ====================================================================== */
  $("#theme-btn").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("mymeeting-theme", next); } catch (_) { /* ignore */ }
  });

  function closeSidebar() { body.classList.remove("sb-open"); }
  $("#menu-btn").addEventListener("click", () => body.classList.add("sb-open"));
  $("#sb-close").addEventListener("click", closeSidebar);
  $("#scrim").addEventListener("click", closeSidebar);
  $("#new-btn").addEventListener("click", () => {
    // Already on the new-note page: the hash will not change, so reset it by hand.
    if (!location.hash || location.hash === "#/") { state.file = null; showNew(); closeSidebar(); }
  });

  /* ======================================================================
     Start
     ====================================================================== */
  refreshList().catch(() => {}).finally(route);
})();
