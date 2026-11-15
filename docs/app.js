(() => {
  const API = (window.ASK_CONFIG && window.ASK_CONFIG.backendUrl || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const chat = $("chat"), empty = $("empty"), statusText = $("status-text"), dot = $("status-dot");
  const modelSel = $("model"), modelDesc = $("model-desc"), question = $("question"), send = $("send");
  const form = $("ask-form"), gate = $("gate"), gateForm = $("gate-form"), gateCode = $("gate-code");
  const gateErr = $("gate-error"), lockBtn = $("lock");

  let history = [];        // [{role, content}] sent to the server
  let busy = false;
  let models = [];

  // localStorage remembers the model; sessionStorage holds the access session (cleared when the tab closes)
  const store = (s) => ({
    get(k) { try { return s.getItem(k); } catch { return null; } },
    set(k, v) { try { s.setItem(k, v); } catch {} },
    del(k) { try { s.removeItem(k); } catch {} },
  });
  const local = store(window.localStorage), session = store(window.sessionStorage);
  const authHeaders = () => (session.get("token") ? { Authorization: "Bearer " + session.get("token") } : {});

  // ---------- rendering: markdown + KaTeX math ----------
  function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  function renderMath(tex, display) {
    if (!window.katex) return esc(display ? "$$" + tex + "$$" : "$" + tex + "$");
    try { return katex.renderToString(tex, { displayMode: display, throwOnError: false, output: "html" }); }
    catch { return esc(tex); }
  }

  function render(md) {
    if (!window.marked || !window.DOMPurify) return esc(md).replace(/\n/g, "<br>");
    const math = [];
    // keep code untouched; pull math out of everything else so markdown can't mangle it
    const parts = md.split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g);
    const prepped = parts.map((p, i) => {
      if (i % 2 === 1) return p;
      return p
        .replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]/g, (_, a, b) => { math.push([a ?? b, true]); return "@@M" + (math.length - 1) + "@@"; })
        .replace(/\\\(([\s\S]+?)\\\)|(?<![\\$\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?![\w$])/g, (_, a, b) => { math.push([a ?? b, false]); return "@@M" + (math.length - 1) + "@@"; });
    }).join("");
    let html = DOMPurify.sanitize(marked.parse(prepped));
    html = html.replace(/@@M(\d+)@@/g, (_, n) => {
      const [tex, display] = math[+n];
      return display ? '<div class="math-display">' + renderMath(tex, true) + "</div>" : renderMath(tex, false);
    });
    return html;
  }

  // An assistant reply is a list of parts: text and tool runs, shown in order.
  function renderReply(el, parts) {
    el.innerHTML = "";
    for (const p of parts) {
      if (p.type === "text") {
        const d = document.createElement("div"); d.className = "md"; d.innerHTML = render(p.text); el.appendChild(d);
      } else {
        const det = document.createElement("details"); det.className = "tool";
        const kind = {
          lean: ["Lean", "Checked with Lean", "Checking with Lean…", /\[exit code 0\]\s*$/],
          install: ["Install", "📦 Installed package", "Installing a package…", /^Installed:/],
          python: ["Python", "Ran Python", "Running Python…", /\[exit code 0\]\s*$/],
        }[p.lang] || ["Tool", "Used a tool", "Working…", /./];
        const [name, verb, pending, okRe] = kind;
        const failed = p.lang === "install" ? "📦 Couldn't install package" : verb + " (see output)";
        const state = p.output === undefined ? '<span class="spin"></span>' + pending
                                             : (okRe.test(p.output) ? verb + (p.lang === "install" ? "" : " ✓") : failed);
        det.innerHTML = "<summary><span class=\"st\">" + state + "</span></summary>" +
          "<div class=\"lbl\">" + (p.lang === "install" ? "Command" : name + " code") + "</div><pre><code></code></pre>" +
          (p.output !== undefined ? "<div class=\"lbl\">Output</div><pre><code></code></pre>" : "");
        const codes = det.querySelectorAll("code");
        codes[0].textContent = p.code || "";
        if (codes[1]) codes[1].textContent = p.output || "(no output)";
        el.appendChild(det);
      }
    }
  }

  function addBubble(role, label) {
    empty.hidden = true;
    const el = document.createElement("div");
    el.className = "msg " + role;
    if (label) { const t = document.createElement("span"); t.className = "tag"; t.textContent = label; el.appendChild(t); }
    const body = document.createElement("div"); body.className = "body";
    el.appendChild(body);
    chat.appendChild(el);
    chat.scrollTop = chat.scrollHeight;
    return body;
  }

  function setReady(ready) {
    question.disabled = !ready || busy;
    send.disabled = !ready || busy;
    modelSel.disabled = !ready || busy;
  }

  function showDesc() {
    const m = models.find((x) => x.id === modelSel.value);
    modelDesc.textContent = m && m.description ? m.description : "";
  }

  // ---------- access-code session ----------
  function showGate(msg) {
    session.del("token");
    gate.hidden = false;
    gateErr.hidden = !msg; gateErr.textContent = msg || "";
    setTimeout(() => gateCode.focus(), 50);
  }

  gateForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    $("gate-btn").disabled = true; gateErr.hidden = true;
    try {
      const r = await fetch(API + "/api/session", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: gateCode.value }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || "Couldn't check the code.");
      session.set("token", data.token);
      gateCode.value = "";
      gate.hidden = true;
      lockBtn.hidden = false;
      question.focus();
    } catch (err) {
      gateErr.textContent = err.message; gateErr.hidden = false;
    } finally {
      $("gate-btn").disabled = false;
    }
  });

  lockBtn.addEventListener("click", () => { if (!busy) { clearChat(); showGate(); } });

  // ---------- startup ----------
  async function loadModels() {
    if (!API) { statusText.textContent = "Backend URL is not set in config.js."; dot.className = "dot bad"; return; }
    try {
      const r = await fetch(API + "/api/models", { cache: "no-store", headers: authHeaders() });
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      models = data.models;
      modelSel.innerHTML = "";
      const groups = {};
      for (const m of models) {
        if (!groups[m.group]) { groups[m.group] = document.createElement("optgroup"); groups[m.group].label = m.group; modelSel.appendChild(groups[m.group]); }
        const o = document.createElement("option");
        o.value = m.id; o.textContent = m.label;
        groups[m.group].appendChild(o);
      }
      if (!models.length) {
        dot.className = "dot bad";
        statusText.textContent = "The server is up, but no models are switched on yet.";
        modelSel.innerHTML = "<option>No models</option>";
        return;
      }
      const saved = local.get("model");
      if (saved && models.some((m) => m.id === saved)) modelSel.value = saved;
      showDesc();
      dot.className = "dot ok"; dot.title = "Server online";
      statusText.textContent = "Server is online.";
      $("tools-text").hidden = !(data.tools && data.tools.python);
      setReady(true);
      if (data.access_code_required) {
        if (data.session_valid) lockBtn.hidden = false; else showGate();
      } else {
        question.focus();
      }
    } catch (e) {
      dot.className = "dot bad"; dot.title = "Server offline";
      statusText.textContent = "The server is offline right now. Try again later.";
      modelSel.innerHTML = "<option>Unavailable</option>";
      setReady(false);
    }
  }

  // ---------- asking ----------
  async function ask(text) {
    busy = true; setReady(true);
    const label = modelSel.options[modelSel.selectedIndex].textContent;
    addBubble("user").textContent = text;
    history.push({ role: "user", content: text });
    const body = addBubble("assistant", label);
    body.classList.add("typing");
    const parts = [];
    const tools = {};
    const textOnly = () => parts.filter((p) => p.type === "text").map((p) => p.text).join("");
    const addText = (t) => {
      const last = parts[parts.length - 1];
      if (last && last.type === "text") last.text += t; else parts.push({ type: "text", text: t });
    };

    try {
      const r = await fetch(API + "/api/chat", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
        body: JSON.stringify({ model: modelSel.value, messages: history }),
      });
      if (r.status === 401) { const err = new Error("Your session ended. Enter the access code again."); err.gate = true; throw err; }
      if (!r.ok) {
        let msg = "Request failed (" + r.status + ").";
        try { msg = (await r.json()).error || msg; } catch {}
        throw new Error(msg);
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2);
          if (!line.startsWith("data:")) continue;            // ": ping" keep-alives
          const ev = JSON.parse(line.slice(5));
          if (ev.type === "delta") addText(ev.text);
          else if (ev.type === "replace") { parts.length = 0; parts.push({ type: "text", text: ev.text }); }
          else if (ev.type === "tool") { const p = { type: "tool", lang: ev.lang, code: ev.code }; tools[ev.id] = p; parts.push(p); }
          else if (ev.type === "tool_result") { if (tools[ev.id]) tools[ev.id].output = ev.output; }
          else if (ev.type === "error") throw new Error(ev.message);
          renderReply(body, parts);
          chat.scrollTop = chat.scrollHeight;
        }
      }
      const answer = textOnly().trim();
      if (!answer) throw new Error("Empty answer.");
      history.push({ role: "assistant", content: answer });
    } catch (e) {
      history.pop(); // drop the unanswered question so the chat stays valid
      body.parentElement.remove();
      const err = addBubble("error");
      err.textContent = e.message || "Something went wrong.";
      err.parentElement.className = "msg error";
      if (e.gate) showGate("Your session ended. Enter the code again.");
    } finally {
      body.classList.remove("typing");
      busy = false; setReady(true);
      if (gate.hidden) question.focus();
    }
  }

  function clearChat() {
    history = [];
    chat.querySelectorAll(".msg").forEach((m) => m.remove());
    empty.hidden = false;
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = question.value.trim();
    if (!text || busy) return;
    question.value = ""; question.style.height = "";
    ask(text);
  });
  question.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  question.addEventListener("input", () => {
    question.style.height = "auto";
    question.style.height = Math.min(question.scrollHeight, 200) + "px";
  });
  modelSel.addEventListener("change", () => { local.set("model", modelSel.value); showDesc(); });
  $("new-chat").addEventListener("click", () => { if (!busy) { clearChat(); question.focus(); } });

  // scripts are deferred; wait for them so markdown/math are ready
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", loadModels); else loadModels();
})();
