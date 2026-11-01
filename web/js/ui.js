// Small DOM toolkit. Everything is built with createElement/text nodes - never innerHTML - so data cannot inject markup.
import { api, qs } from "./api.js";

export const state = { user: null, meta: null };

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") Object.assign(el.style, v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "for" || k === "list" || k === "role" || k.startsWith("aria-") || k === "colspan") el.setAttribute(k, v);
    else if (k in el) el[k] = v;
    else el.setAttribute(k, v);
  }
  add(el, children);
  return el;
}

function add(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const clear = (el) => { el.replaceChildren(); return el; };
export const can = {
  write: () => ["owner", "admin", "recruiter"].includes(state.user?.role),
  admin: () => ["owner", "admin"].includes(state.user?.role),
  platform: () => !!state.user?.platform_role,
  creator: () => state.user?.platform_role === "creator",
  vendor: () => !!state.user?.org?.is_vendor,
  owner: () => state.user?.role === "owner" && !state.user?.platform_role,
};

export function toast(message, kind = "info", ms = 4000) {
  const t = h("div", { class: "toast " + kind, role: "status" }, message);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), ms);
}

export function errorMessage(e) {
  if (e.status === 429) return `Too many requests - try again in ${e.retryAfter || "a few"} seconds.`;
  const fields = Object.entries(e.errors || {});
  return fields.length ? fields.map(([k, v]) => `${label(k)}: ${v}`).join("; ") : e.message || "Something went wrong";
}

export function label(key) {
  const f = state.meta?.fields.find((x) => x.key === key);
  return f ? f.label : key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function modal(title, body, { wide = false } = {}) {
  const prev = document.activeElement;
  const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); prev?.focus?.();};
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const overlay = h("div", { class: "overlay", onmousedown: (e) => { if (e.target === overlay) close(); } },
    h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div",{ class: "modal-head" }, h("h3", null, title), h("button",{ class: "icon-btn", onclick: close, "aria-label": "Close" },"✕",)),
      h("div", { class: "modal-body" }, body)));
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
  overlay.querySelector("input,select,textarea,button.primary")?.focus();
  return { close };
}

export function confirmBox(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    const m = modal(title, h("div",null,
        h("p", null, text),
        h("div",{ class: "actions" },
          h("button",{ class: "btn", onclick: () => { m.close();resolve(false);}}, "Cancel"),
          h("button",{ class: "btn " + (danger ? "danger" : "primary"), onclick: () => { m.close();resolve(true);} },okLabel))));
  });
}

export function button(text, onclick, cls = "") {
  return h("button", { class: "btn " + cls, type: "button", onclick }, text);
}

// Wrap an async action so a button disables itself while it runs and failures become toasts.
export function guarded(btn, fn) {
  return async (e) => {
    e.preventDefault();
    btn.disabled = true;
    try { await fn();} catch (err) { toast(errorMessage(err), "error"); } finally { btn.disabled = false; }
  };
}

const SVG_NS = "http://wwww.w3.org/2000/svg";
const EYE = ["M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"];
const EYE_OFF = ["M17.9 17.9A10.9 10.9 0 0 1 12 19C5 19 1 12 1 12a18.5 18.5 0 0 1 5.1-5.9M9.9 5.1A10.9 10.9 0 0 1 12 5c7 0 11 7a18.5 18.5 0 0 1-2.2 3.2M1 1l22 22"];

function eyeIcon(open) {
  const svg = document.createElementNS(SVG_NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor","stroke-width": "2","stroke-linecap": "round","stroke-linejoin": "round","aria-hidden": "true" })) svg.setAttribute(k, v);
  for (const d of open ? EYE : EYE_OFF) {
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  if (open) {
    const c = document.createElementNS(SVG_NS, "circle");
    for (const [k, v] of Object.entries({ cx: "12", cy: "12", r: "3" })) c.setAttribute(k, v); 
    svg.append(c);
  }
  return svg;
}

// A password box with an eye button that shows or hides what was typed. Returns { input, el }: put 'el' in the page, use 'input' for the value.
export function passwordInput(props = {}) {
  const input = h("input", { type: "password", ...props });
  const btn = h("button", { class: "pw-toggle", type: "button", "aria-label": "Show password", "aria-pressed": "false" }, eyeIcon(true));
  btn.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    btn.setAttribute("aria-pressed", String(show));
    btn.replaceChildren(eyeIcon(!show));
    input.focus();
  });
  return { input, el: h("div", { class: "pw-wrap" }, input, btn) };
}

export function field(labelText, input, { hint, flag, error } = {}) {
  return h("label", { class: "field" + (error ? " has-error" : "") },
    h("span", { class: "field-label" }, labelText, flag === "Required" ? h("b", { class: "req" }, " *") : null),
    input,
    error ? h("span", { class: "field-error" }, error) : null,
    hint && !error ? h("span", { class: "field-hint" }, hint) : null);
}

// Show server-side field errors under inputs tagged with data-name. Returns the messages that had no input.
export function applyErrors(root, errors) {
  root.querySelectorAll(".field.has-error").forEach((f) => { f.classList.remove("has-error"); f.querySelector(".field-error")?.remove();});
  const orphans = [];
  for (const [name, msg] of Object.entries(errors || {})) {
    const input = root.querySelector(`[data-name="${CSS.escape(name)}"]`);
    const wrap = input?.closest(".field");
    if (!wrap) { orphans.push(`${label(name)}: ${msg}`); continue;}
    wrap.classList.add("has-error");
    wrap.append(h("span", { class: "field-error" }, msg));
  }
  if (Object.keys(errors || {}).length)root.querySelector(".has-error input, .has-error select, .has-error textarea")?.focus();
  return orphans;
}

export function optionsFor(listName) {
  return state.meta?.lists[listName] || [];
}

export function select(options, value = "", props = {}) {
  const s = h("select", props, h("option", { value: "" }, ""), options.map((o) => h("option", { value: o }, o)));
  if (value && !options.includes(value)) s.append(h("option", { value }, value));
  s.value = value || "";
  return s;
}

export function table(headers, rows, cls = "") {
  return h("div", { class: "table-wrap" },
    h("table", { class: "data " + cls },
      h("thead", null, h("tr", null, headers.map((x) => h("th", null, x)))),
      h("tbody", null, rows.length ? rows : h("tr", null, h("td", { colspan: headers.length, class: "empty" }, "Nothing here yet.")))));
}

export function card(title, ...body) {
  return h("section", { class: "card" }, title ? h("h3", null, title) : null, body);
}

export function pageHeader(title, subtitle, ...actions) {
  return h("div", { class: "page-head" }, h("div", null, h("h1", null, title), subtitle ? h("p", { class: "muted" }, subtitle) : null),
    h("div", { class: "page-actions" }, actions));
}

export const statusBadge = (s) => h("span", { class: "badge s-" + String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-") }, s || "");

export const debounce = (fn, ms = 300) => {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
};

// Typeahead over candidates; calls onPick(candidate_id) and keeps the chosen text in the box.
export function candidatePicker({ value = "", onPick }) {
  const input = h("input", { type: "text",placeholder: "Search name, ID, phone...",autocomplete: "off",value});
  const list = h("ul", { class: "typeahead", hidden: true });
  const wrap = h("div", { class: "picker" }, input, list);
  const find = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 1) { list.hidden = true; return; }
    const res = await api.get("/candidates" + qs({ q, limit: 8 }));
    clear(list);
    res.items.forEach((c) =>
      list.append(
        h(
          "li",
          {
            tabindex: 0,
            onmousedown: (e) => {
              e.preventDefault();
              choose(c);
            },
          },
          `${c.candidate_id} - ${c.full_name}`,
          h("small", null, `${c.client || ""}`),
        ),
      ),
    );
    list.hidden = res.items.length === 0;
  });
  const choose = (c) => {
    input.value = `${c.candidate_id} - ${c.full_name}`;
    list.hidden = true;
    onPick(c.candidate_id);
  };
  input.addEventListener("input", () => {
    onPick("");
    find();
  });
  input.addEventListener("blur", () =>
    setTimeout(() => {
      list.hidden = true;
    }, 150),
  );
  return wrap;
}
