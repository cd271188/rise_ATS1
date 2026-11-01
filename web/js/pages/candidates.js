import { api, qs } from "../api.js";
import { h, modal, pageHeader, button, guarded, can, state, toast, errorMessage, confirmBox, debounce } from "../ui.js";
import { go } from "../router.js";
import { createGrid } from "../grid.js";
import { openInterviewForm } from "./interview_form.js";

const WIDTHS = { candidate_id: 100, full_name: 190, textarea: 260, date: 130, number: 120, select: 150, email: 210 };

function buildColumns() {
  const fields = state.meta.fields;
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const order = ["full_name", ...fields.map((f) => f.key).filter((k) => k !== "full_name")];
  return [
    { key: "candidate_id", label: "ID", type: "text", readonly: true, width: WIDTHS.candidate_id },
    ...order.map((k) => {
      const f = byKey.get(k);
      return { key: k, label: f.label, type: f.type, list: f.list, width: WIDTHS[k] || WIDTHS[f.type] || 160 };
    }),
    { key: "current_status", label: "Status", type: "text", readonly: true, width: 150 },
    ...((state.meta.vendors || []).length ? [{ key: "vendor", label: "Vendor", type: "text", readonly: true, sortable: false, filter: "none", width: 160 }] : []),
    { key: "duplicate_check", label: "Duplicate?", type: "text", readonly: true, sortable: false, filter: "none", width: 130 },
    { key: "last_updated", label: "Last updated", type: "text", readonly: true, filter: "none", width: 150 },
  ];
}

function importSummary(s) {
  const line = (label, n) => h("li", null, h("strong", null, n), " " + label);
  const body = h("div", null,
    h("ul", { class: "plain" }, line("added", s.added), line("skipped as duplicates", s.skipped_duplicate), line("added with a same-name flag", s.added_with_name_flag), 
      line("blank rows skipped", s.skipped_blank), line("interview entries added", s.interviews_added), line("rows with errors", s.invalid.length)),
    s.invalid.length ? h("div", { class: "notice warn" }, h("strong", null, "Rows not imported"), h("ul", null, s.invalid.slice(0, 10).map((x) =>
      h("li", null, `Row ${x.row}: ` + Object.entries(x.errors).map(([k, v]) => `${k} ${v}`).join("; "))))): null,
    h("div", { class: "actions" }, button("Close", () => m.close(), "primary")));
  const m = modal("Import finished", body);
}

export async function candidatesPage(root, params) {
  const writable = can.write();
  const q = h("input", { type: "search", placeholder: "Search name, company, phone, ID...", value: params.q || "", "aria-label": "Search" });
  const dup = h("select", { "aria-label": "Duplicates" }, h("option", { value: "" }, "All candidates"), h("option", { value: "yes" }, "Possible duplicates only"));
  const vendors = state.meta.vendors || [];
  const vendor = vendors.length ? h("select", { "aria-label": "Source" }, h("option", { value: "" }, "All sources"), h("option", { value: "0" }, "Our own team"),
    vendors.map((v) => h("option", { value: String(v.id) }, v.name))) : null;
  const from = h("input", { type: "date", "aria-label": "Added from" });
  const to = h("input", { type: "date", "aria-label": "Added to" });
  const fileInput = h("input", { type: "file", accept: ".xlsx", hidden: true });

  const grid = createGrid({
    columns: buildColumns(),
    load: (g) => api.get("/candidates" + qs({ q: q.value.trim(), duplicate: dup.value, vendor_id: vendor ? vendor.value: "", date_from: from.value, date_to: to.value, ...g })),
    canEdit: (row, col) => writable && !col.readonly && (can.admin() || state.user.org.team_edit || row.created_by === state.user.id),
    save: (row, key, value) => api.patch(`/candidates/${row.candidate_id}`, { [key]: value, version: row.version }),
    rowActions: (row) => [
      h("a", { class: "icon-link", href: "#/candidate/" + row.candidate_id, title: "Open " + row.candidate_id, "aria-label": "Open " + row.candidate_id }, "↗"),
      writable ? h("button", { class: "icon-link", type: "button", title: "Add interview entry", "aria-label": "Add interview entry",
        onclick: () => openInterviewForm({ candidateId: row.candidate_id, onSaved: () => grid.reload() }) }, "📅") : null,
      can.admin() ? h("button", { class: "icon-link danger-text", type: "button", title: "Delete", "aria-label": "Delete " + row.candidate_id,
        onclick: async () => {
          if (!await confirmBox("Delete candidate", `Delete ${row.full_name}? They disappear from every list; the record is kept for audit.`, "Delete", true)) return;
          try { await api.del(`/candidates/${row.candidate_id}`); toast("Candidate deleted.", "success"); grid.reload(); } catch (e) { toast(errorMessage(e), "error"); }
      }}, "X") : null,
    ],
  });

  const refresh = debounce(() => grid.reload(true), 300);
  q.addEventListener("input", refresh);
  [dup, vendor, from, to].filter(Boolean).forEach((x) => x.addEventListener("change", () => grid.reload(true)));

  const exportBtn = button("Export Excel", null);
  exportBtn.onclick = guarded(exportBtn, async () => { await api.download("/export.xlsx", "ats_export.xlsx"); });
  const importBtn = button("Import Excel", () => fileInput.click());
  fileInput.addEventListener("change", guarded(importBtn, async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    if (file.size > 14 * 1024 * 1024) { toast("That file is larger than 14 MB.", "error"); return; }
    const summary = await api.upload("/import", await file.arrayBuffer());
    importSummary(summary);
    grid.reload(true);
  }));

  root.append(
    pageHeader("Candidates", writable ? "Double-click or press Enter on a cell to edit it. Changes save automatically." 
      : "Read-only access: you can sort, filter, search, copy cells and export.",
      writable ? button("Add candidate", () => go("/candidate/new"), "primary") : null),
    h("div", { class: "toolbar" }, q, dup, vendor, h("label", { class: "inline" }, "Added from", from), h("label", { class: "inline" }, "to", to),
      h("span", { class: "spacer" }), exportBtn, writable ? importBtn : null, fileInput),
    grid.el);
  await grid.reload(true);
  return () => grid.destroy();
}