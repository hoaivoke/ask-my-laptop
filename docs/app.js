(() => {
  const API = (window.ASK_CONFIG && window.ASK_CONFIG.backendUrl || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const chat = $("chat"), empty = $("empty"), statusText = $("status-text"), dot = $("status-dot");
  const modelSel = $("model"), question = $("question"), send = $("send"), form = $("ask-form");
  const codeInput = $("access-code");

  let history = [];       // [{role, content}]
  let busy = false;

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };

  function render(md) {
    if (window.marked && window.DOMPurify) return DOMPurify.sanitize(marked.parse(md));
    const d = document.createElement("div"); d.textContent = md;
    return d.innerHTML.replace(/\n/g, "<br>");
  }

  function addMsg(role, text, label) {
    empty.hidden = true;
    const el = document.createElement("div");
    el.className = "msg " + role;
    if (label) { const t = document.createElement("span"); t.className = "tag"; t.textContent = label; el.appendChild(t); }
    const body = document.createElement("div"); body.className = "body";
    if (role === "assistant") body.innerHTML = render(text); else body.textContent = text;
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

  async function loadModels() {
    if (!API) { statusText.textContent = "Backend URL is not set in config.js."; dot.className = "dot bad"; return; }
    try {
      const r = await fetch(API + "/api/models", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      modelSel.innerHTML = "";
      for (const m of data.models) {
        const o = document.createElement("option");
        o.value = m.id; o.textContent = m.label; o.title = m.description || "";
        modelSel.appendChild(o);
      }
      if (!data.models.length) {
        dot.className = "dot bad"; dot.title = "No models";
        statusText.textContent = "The server is up, but no models are switched on yet.";
        modelSel.innerHTML = "<option>No models</option>";
        return;
      }
      const saved = store.get("model");
      if (saved && data.models.some((m) => m.id === saved)) modelSel.value = saved;
      if (data.access_code_required) { codeInput.hidden = false; codeInput.value = store.get("code") || ""; }
      dot.className = "dot ok"; dot.title = "Server online";
      statusText.textContent = "Server is online.";
      setReady(true);
      question.focus();
    } catch (e) {
      dot.className = "dot bad"; dot.title = "Server offline";
      statusText.textContent = "The server is offline right now. Try again later.";
      modelSel.innerHTML = "<option>Unavailable</option>";
      setReady(false);
    }
  }

  async function ask(text) {
    busy = true; setReady(true);
    const label = modelSel.options[modelSel.selectedIndex].textContent;
    addMsg("user", text);
    history.push({ role: "user", content: text });
    const body = addMsg("assistant", "", label);
    body.classList.add("typing");
    let answer = "";

    try {
      const r = await fetch(API + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelSel.value, messages: history, access_code: codeInput.value }),
      });
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
          if (!line.startsWith("data:")) continue;
          const ev = JSON.parse(line.slice(5));
          if (ev.type === "delta") answer += ev.text;
          else if (ev.type === "replace") answer = ev.text;
          else if (ev.type === "error") throw new Error(ev.message);
          body.innerHTML = render(answer);
          chat.scrollTop = chat.scrollHeight;
        }
      }
      if (!answer) throw new Error("Empty answer.");
      history.push({ role: "assistant", content: answer });
    } catch (e) {
      history.pop(); // drop the unanswered question so the chat stays valid
      body.parentElement.remove();
      const err = addMsg("error", e.message || "Something went wrong.");
      err.parentElement.className = "msg error";
    } finally {
      body.classList.remove("typing");
      busy = false; setReady(true);
      question.focus();
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = question.value.trim();
    if (!text || busy) return;
    if (!codeInput.hidden) store.set("code", codeInput.value);
    question.value = ""; question.style.height = "";
    ask(text);
  });
  question.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  question.addEventListener("input", () => {
    question.style.height = "auto";
    question.style.height = Math.min(question.scrollHeight, 200) + "px";
  });
  modelSel.addEventListener("change", () => store.set("model", modelSel.value));
  $("new-chat").addEventListener("click", () => {
    if (busy) return;
    history = [];
    chat.querySelectorAll(".msg").forEach((m) => m.remove());
    empty.hidden = false;
    question.focus();
  });

  loadModels();
})();
