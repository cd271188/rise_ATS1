// Editable, server-paginated data grid. Cells save one at a time through opts.save(row, key, value) (PATCH + version).
import { ApiError } from "./api.js";
import { h, clear, toast, errorMessage, select, optionsFor, statusBadge, debounce } from "./ui.js";

const ACTION_W = 104;
const MIN_W = 60;

/*
 * columns: [{ key, label, type, list, readonly, width, sortable, filter }] (columns[0] is the frozen identifier column)
 * load({ sort, direction, offset, limit, f }) -> { items, total }
 * canEdit(row, col) -> boolean       save(row, key, value) -> updated row (throws ApiError)
 * rowActions(row) -> nodes for the left action cell
 */
export function createGrid({ columns, load, canEdit, save, rowActions, onChange, pageSize = 50 }) {
  const st = { sort: "candidate_id", dir: "asc", filters: {}, offset: 0, limit: pageSize, rows: [], total: 0 };
  const widths = columns.map((c) => c.width || 140);
  let cells = [];
  let anchor = null;
  let focus = null;
  let editing = null;
  let dragging = false;
  let seq = 0;
  let queue = Promise.resolve();

  const text = (row, col) => String(row[col.key] ?? "");
  const msg = h("span", { class: "grid-msg", role: "status" });
  const info = h("span", { class: "muted" });
  const prev = h("button", { class: "btn small", type: "button", onclick: () => page(-1) }, "◀ Prev");
  const next = h("button", { class: "btn small", type: "button", onclick: () => page(1) }, "Next ▶");
  const sizer = h("select", { "aria-label": "Rows per page", onchange: () => { st.limit = Number(sizer.value); reload(true); } },
    [25, 50, 100, 200].map((n) => h("option", { value: String(n) }, n + " / page")));
  sizer.value = String(st.limit);

  const colEls = [h("col", { style: { width: ACTION_W + "px" } }), ...columns.map((c, i) => h("col", { style: { width: widths[i] + "px" } }))];
  const table = h("table", { class: "grid" }, h("colgroup", null, colEls));
  const body = h("tbody");
  const arrows = [];

  function setWidth(i, w) {
    widths[i] = Math.max(MIN_W, Math.round(w));
    colEls[i + 1].style.width = widths[i] + "px";
    table.style.width = ACTION_W + widths.reduce((a, b) => a + b, 0) + "px";
  }
  table.style.width = ACTION_W + widths.reduce((a, b) => a + b, 0) + "px";

  const headRow = h("tr", null, h("th", { class: "c-actions" }, ""), columns.map((c, i) => {
    const arrow = h("span", { class: "sort-arrow", "aria-hidden": "true" });
    arrows.push(arrow);
    const handle = h("span", { class: "resize", role: "separator", "aria-label": "Resize column " + c.label });
    handle.addEventListener("pointerdown", (e) => e.stopPropagation());
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handle.setPointerCapture(e.pointerId);
      const x0 = e.clientX;
      const w0 = widths[i];
      const move = (ev) => setWidth(i, w0 + ev.clientX - x0);
      const up = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
    const th = h("th", { class: (i === 0 ? "sticky-id " : "") + (c.sortable === false ? "" : "sortable"), "aria-sort": "none" }, h("span", { class: "th-label" }, c.label), arrow, handle);
    if (c.sortable !== false) th.addEventListener("click", () => {
        st.dir = st.sort === c.key && st.dir === "asc" ? "desc" : "asc";
        st.sort = c.key;
        reload(true);
      });
    return th;
  }));

  const applyFilter = (key, value) => {
    if (value) st.filters[key] = value; else delete st.filters[key];
    reload(true);
  };
  const filterRow = h("tr", { class: "filters" }, h("th", { class: "c-actions" }, ""), columns.map((c, i) => {
    let input = null;
    if (c.filter !== "none") {
      if (c.type === "select" || c.key === "current_status") {
        input = select(optionsFor(c.key === "current_status" ? "status" : c.list), "", { "aria-label": "Filter " + c.label });
        input.addEventListener("change", () => applyFilter(c.key, input.value));
      } else {
        input = h("input", { type: "text", placeholder: c.type === "number" ? "min" : "filter", "aria-label": "Filter " + c.label });
        input.addEventListener("input", debounce(() => applyFilter(c.key, input.value.trim()), 350));
      }
    }
    return h("th", { class: i === 0 ? "sticky-id" : "" }, input);
  }));
  table.append(h("thead", null, headRow, filterRow), body);

  const wrap = h("div", { class: "grid-wrap", tabindex: "0", role: "grid", "aria-label": "Candidates" }, table);
  const bar = h("div", { class: "grid-bar" }, msg, h("span", { class: "spacer" }), info, sizer, prev, next);
  const el = h("div", { class: "grid-card" }, wrap, bar);

  function setMsg(t, bad = false) {
    msg.textContent = t;
    msg.classList.toggle("bad", bad);
  }

  function page(dir) {
    st.offset = Math.max(0, st.offset + dir * st.limit);
    reload();
  }

  async function reload(resetPage = false) {
    if (resetPage) st.offset = 0;
    const mine = ++seq;
    setMsg("Loading...");
    try {
      const res = await load({ sort: st.sort, direction: st.dir, offset: st.offset, limit: st.limit, f: Object.entries(st.filters).map(([k, v]) => `${k}:${v}`) });
      if (mine != seq) return;
      st.total = res.total;
      if (st.offset > 0 && res.items.length === 0 && res.total > 0) {
        st.offset = (Math.ceil(res.total / st.limit) - 1) * st.limit;
        await reload();
        return;
      }
      st.rows = res.items;
      draw();
      setMsg("");
    } catch (e) {
      if (mine === seq) { setMsg(errorMessage(e), true); toast(errorMessage(e), "error"); }
    }
  }

  const rowClass = (row) => (row.duplicate_check && row.duplicate_check !== "OK" ? "dup" : "");
  const cellClass = (c, i) => [i === 0 ? "sticky-id" : "", c.type === "number" ? "num" : "", c.readonly ? "readonly" : ""].filter(Boolean).join(" ");

  function paint(td, row, col) {
    clear(td);
    const t = text(row, col);
    if (col.key === "current_status") td.append(statusBadge(t));
    else td.textContent = t;
    td.title = t;
  }

  function draw() {
    editing = null;
    clear(body);
    cells = [];
    if (!st.rows.length) {
      body.append(h("tr", null, h("td", { colspan: columns.length + 1, class: "empty" }, Object.keys(st.filters).length ? "No candidates match these filters." : "No candidates yet.")));
    }
    st.rows.forEach((row, r) => {
      const tds = columns.map((c, i) => {
        const td = h("td", { class: cellClass(c, i), dataset: { r: String(r), c: String(i) } });
        paint(td, row, c);
        return td;
      });
      cells.push(tds);
      body.append(h("tr", { class: rowClass(row) }, h("td", { class: "c-actions" }, rowActions ? rowActions(row) : null), tds));
    });
    if (focus && (focus.r >= cells.length)) { focus = anchor = null; }
    columns.forEach((c, i) => {
      const active = st.sort === c.key;
      arrows[i].textContent = active ? (st.dir === "asc" ? " ▲" : " ▼") : "";
      arrows[i].parentElement.setAttribute("aria-sort", active ? (st.dir === "asc" ? "ascending" : "descending") : "none");
    });
    const from = st.rows.length ? st.offset + 1 : 0;
    info.textContent = st.total ? '${from}-${st.offset + st.rows.length} if ${st.total}' : "0 rows";
    prev.disabled = st.offset === 0;
    next.disabled = st.offset + st.limit >= st.total;
    paintSel();
  }

  function repaintRow(row) {
    const r = st.rows.indexOf(row);
    if (r < 0) return;
    columns.forEach((c, i) => {
      if (editing && editing.r === r && editing.c === i) return;
      cells[r][i].classList.remove("cell-error");
      paint(cells[r][i], row, c);
    });
    cells[r][0].parentElement.className = rowClass(row);
  }

  // ---- selection
  function range() {
    if (!focus) return null;
    const a = anchor || focus;
    return { r0: Math.min(a.r, focus.r), r1: Math.max(a.r, focus.r), c0: Math.min(a.c, focus.c), c1: Math.max(a.c, focus.c) };
  }

  function paintSel(reveal = false) {
    const rg = range();
    cells.forEach((tds, r) => tds.forEach((td, c) => {
      td.classList.toggle("sel", Boolean(rg) && r >= rg.r0 && r <= rg.r1 && c >= rg.c0 && c <= rg.c1);
      td.classList.toggle("active", Boolean(focus) && focus.r === r && focus.c === c);
    }));
    if (reveal && focus) cells[focus.r]?.[focus.c]?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function moveTo(r, c, extend = false) {
    if (!cells.length) return;
    r = Math.max(0, Math.min(cells.length - 1, r));
    c = Math.max(0, Math.min(columns.length - 1, c));
    if (!extend || !anchor) anchor = { r, c };
    focus = { r, c };
    paintSel(true);
  }

  // ---- editing
  function startEdit(r, c, typed) {
    const row = st.rows[r];
    const col = columns[c];
    if (!row || editing) return;
    if (!canEdit(row, col)) {
      setMsg(col.readonly ? `${col.label} is read-only.` : "You cannot edit this record.");
      return;
    }
    const cur = String(row[col.key] ?? "");
    let input;
    if (col.type === "select") input = select(optionsFor(col.list), cur);
    else {
      input = h("input", {
        type: col.type === "date" ? "date" : col.type === "number" ? "number" : "text",
        step: col.type === "number" ? "any" : null, min:col.type == "number" ? "0" : null,
        value: typed != null && col.type !== "date" ? typed : cur,
      });
    }
    input.classList.add("cell-editor");
    editing = { r, c, el: input, row, col, original: cur };
    const td = cells[r][c];
    clear(td).append(input);
    td.classList.add("editing");
    input.focus();
    if (typed == null && input.select) input.select();
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); finish(true, { dr: e.shiftKey ? -1 : 1, dc: 0 }); }
      else if (e.key === "Tab") { e.preventDefault(); finish(true, { dr: 0, dc: e.shiftKey ? -1 : 1 }); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
    if (col.type === "select") input.addEventListener("change", () => finish(true));
  }

  function finish(commit, move) {
    if (!editing) return;
    const e = editing;
    editing = null;
    const value = e.el.value;
    const td = cells[e.r][e.c];
    td.classList.remove("editing");
    paint(td, e.row, e.col);
    if (commit && value !== e.original) saveCell(e.row, e.col, td, value);
    wrap.focus({ preventScroll: true });
    if (move) moveTo(e.r + move.dr, e.c + move.dc);
  }

  // Saves run one after another so each PATCH carries the version returned by the previous one.
  function saveCell(row, col, td, value) {
    td.classList.add("saving");
    td.classList.remove("cell-error");
    queue = queue.then(async () => {
      try {
        Object.assign(row, await save(row, col.key, value));
        repaintRow(row);
        setMsg("Saved.");
        onChange?.(row);
      } catch (ex) {
        if (ex instanceof ApiError && ex.status === 409 && ex.current) {
          Object.assign(row, ex.current);
          repaintRow(row);
          setMsg("Row refreshed: someone else changed it.", true);
          toast("Someone else changed this row. The latest values are shown - repeat your edit.", "warn", 8000);
        } else {
          const why = (ex.errors && ex.errors[col.key]) || errorMessage(ex);
          td.classList.add("cell-error");
          td.title = why;
          setMsg(`${col.label}: ${why}`, true);
          toast(`${col.label}: ${why}`, "error");
        }
      } finally {
        td.classList.remove("saving");
      }
    });
  }

  // ---- events
  body.addEventListener("mousedown", (e) => {
    const td = e.target.closest("td[data-c]");
    if (!td || e.target.closest(".cell-editor") || e.button !== 0) return;
    e.preventDefault();
    wrap.focus({ preventScroll: true });
    moveTo(Number(td.dataset.r), Number(td.dataset.c), e.shiftKey && Boolean(focus));
    dragging = true;
  });
  body.addEventListener("mouseover", (e) => {
    if (!dragging) return;
    const td = e.target.closest("td[data-c]");
    if (td) moveTo(Number(td.dataset.r), Number(td.dataset.c), true);
  });
  body.addEventListener("dblclick", (e) => {
    const td = e.target.closest("td[data-c]");
    if (td && !e.target.closest(".cell-editor")) startEdit(Number(td.dataset.r), Number(td.dataset.c));
  });
  const stopDrag = () => { dragging = false; };
  document.addEventListener("mouseup", stopDrag);

  wrap.addEventListener("keydown", (e) => {
    if (editing || !cells.length) return;
    const mod = e.ctrlKey || e.metaKey;
    const dirs = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (dirs[e.key]) {
      e.preventDefault();
      const f = focus || { r: 0, c: 0 };
      moveTo(focus ? f.r + dirs[e.key][0] : 0, focus ? f.c + dirs[e.key][1] : 0, e.shiftKey);
    } else if (e.key === "Tab" && focus) {
      const c = focus.c + (e.shiftKey ? -1 : 1);
      const atEdge = (e.shiftKey && focus.r === 0 && focus.c === 0) || (!e.shiftKey && focus.r === cells.length - 1 && focus.c === columns.length - 1);
      if (atEdge) return;
      e.preventDefault();
      if (c < 0) moveTo(focus.r - 1, columns.length - 1);
      else if (c >= columns.length) moveTo(focus.r + 1, 0);
      else moveTo(focus.r, c);
    } else if (e.key === "Home" && focus) { e.preventDefault(); moveTo(mod ? 0 : focus.r, 0, e.shiftKey); }
    else if (e.key === "End" && focus) { e.preventDefault(); moveTo(mod ? cells.length - 1 : focus.r, columns.length - 1, e.shiftKey); }
    else if ((e.key === "Enter" || e.key === "F2") && focus) { e.preventDefault(); startEdit(focus.r, focus.c); }
    else if (e.key === "Escape" && focus) { anchor = focus; paintSel(); }
    else if (focus && e.key.length === 1 && !mod && !e.altKey) { e.preventDefault(); startEdit(focus.r, focus.c, e.key); }
  });

  wrap.addEventListener("copy", (e) => {
    const rg = range();
    if (editing || !rg) return;
    const lines = [];
    for (let r = rg.r0; r <= rg.r1; r++) lines.push(columns.slice(rg.c0, rg.c1 + 1).map((c) => text(st.rows[r], c).replace(/[\t\r\n]+/g, " ")).join("\t"));
    e.clipboardData.setData("text/plain", lines.join("\n"));
    e.preventDefault();
    setMsg(`Copied ${(rg.r1 - rg.r0 + 1) * (rg.c1 - rg.c0 + 1)} cell(s).`);
  });

  return { el, reload, destroy: () => document.removeEventListener("mouseup", stopDrag) };
}