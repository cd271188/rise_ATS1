import { api, qs } from "../api.js";
import { h, card, pageHeader, table, statusBadge, toast } from "../ui.js";

export function hbar(items) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return h("div", { class: "hbar" }, items.map((i) => h("div", { class: "hbar-row" },
    h("span", { class: "hbar-label" }, i.label),
    h("span", { class: "hbar-track" }, h("span", { class: "hbar-fill", style: { width: (i.value / max) * 100 + "%" } })),
    h("span", { class: "hbar-value" }, i.value))));
}

export function periodTable(rows) {
  return table(["Recruiter", "Selected range"], rows.map((r) =>
    h("tr", { class: r.recruiter === "Total" ? "total" : "" }, h("td", null, r.recruiter), h("td", { class: "num" }, r.selected))));
}

export function requirementTable(rows) {
  return table(["Client company", "Requirements", "Open", "Closed"], rows.map((r) =>
    h("tr", null, h("td", null, r.company), h("td", { class: "num" }, r.total), h("td", { class: "num" }, r.open), h("td", { class: "num" }, r.closed))));
}

const kpi = (label, value, tone = "") => h("div", { class: "kpi " + tone }, h("span", { class: "kpi-value" }, value), h("span", { class: "kpi-label" }, label));

export async function dashboardPage(root) {
  const [d, due] = await Promise.all([api.get("/dashboard"), api.get("/followups/due")]);
  let requestId = 0;
  const [initialFrom, initialTo] = d.selected_range || d.periods.week;
  const from = h("input", { type: "date", value: initialFrom, "aria-label": "From date" });
  const to = h("input", { type: "date", value: initialTo, "aria-label": "To date" });
  const rangeToolbar = h("div", { class: "toolbar dashboard-range" },
    h("label", { class: "inline" }, "From", from),
    h("label", { class: "inline" }, "To", to),
    h("button", { class: "btn", type: "button", onclick: async () => {
      if (!from.value || !to.value) return toast("Choose both a from and to date.", "error");
      if (from.value > to.value) return toast("From date must be on or before to date.", "error");
      const id = ++requestId;
      try {
        const updated = await api.get("/dashboard" + qs({ from_date: from.value, to_date: to.value }));
        if (id === requestId) renderDashboard(root, updated, due, from.value, to.value, rangeToolbar);
      } catch (e) { toast(e.message || "Could not load dashboard for this date range.", "error"); }
    } }, "Apply dates"));
  renderDashboard(root, d, due, initialFrom, initialTo, rangeToolbar);
}

function renderDashboard(root, d, due, from, to, rangeToolbar) {
  const k = d.kpis;
  root.replaceChildren(
    pageHeader("Dashboard", `Candidates added ${from} to ${to}`),
    rangeToolbar,
    h("div", { class: "kpis" },
      kpi("Candidates", k.total_candidates), kpi("Submitted to client", k.submitted_to_client),
      kpi("In interview", k.in_interview), kpi("Offers", k.offers, "good"),
      kpi("Yet to join", k.yet_to_join), kpi("Drops", k.drops, "bad"), kpi("Follow-ups due", due.length, due.length ? "warn" : "")),
    h("div", { class: "grid-2" },
      card("Pipeline", hbar(d.pipeline.map((p) => ({ label: p.status, value: p.count })))),
      card("Follow-ups due", due.length
        ? h("ul", { class: "followups" }, due.slice(0, 8).map((f) => h("li", null,
          h("a", { href: "#/candidate/" + f.candidate_id }, `${f.candidate_id} ${f.full_name}`), statusBadge(f.status),
          h("small", { class: f.overdue_days > 0 ? "late" : "" }, f.overdue_days > 0 ? `${f.overdue_days}d overdue` : "due today"),
          f.next_action ? h("div", { class: "muted" }, f.next_action) : null)))
        : h("p", { class: "muted" }, "Nothing is waiting on a follow-up.")),
      card("Candidates added", periodTable(d.recruiter_submissions)),
      card("Profiles submitted to clients", periodTable(d.client_submissions))),
    card("Job requirements by client company", d.requirements_by_company?.length
      ? requirementTable(d.requirements_by_company)
      : h("p", { class: "muted" }, "No job requirements have been added yet.")));
}
