import { api } from "../api.js";
import { h, card, pageHeader, table, statusBadge } from "../ui.js";

export function hbar(items) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return h("div", { class: "hbar" }, items.map((i) => h("div", { class: "hbar-row" },
    h("span", { class: "hbar-label" }, i.label),
    h("span", { class: "hbar-track" }, h("span", { class: "hbar-fill", style: { width: (i.value / max) * 100 + "%" } })),
    h("span", { class: "hbar-value" }, i.value))));
}

export function periodTable(rows) {
  return table(["Recruiter", "Today", "This week", "This month"], rows.map((r) =>
    h("tr", { class: r.recruiter === "Total" ? "total" : "" }, h("td", null, r.recruiter), h("td", { class: "num" }, r.today), h("td", { class: "num" }, r.week), h("td", { class: "num" }, r.month))));
}

export function requirementTable(rows) {
  return table(["Client company", "Requirements", "Open", "Closed"], rows.map((r) =>
    h("tr", null, h("td", null, r.company), h("td", { class: "num" }, r.total), h("td", { class: "num" }, r.open), h("td", { class: "num" }, r.closed))));
}

const kpi = (label, value, tone = "") => h("div", { class: "kpi " + tone }, h("span", { class: "kpi-value" }, value), h("span", { class: "kpi-label" }, label));

export async function dashboardPage(root) {
  const [d, due] = await Promise.all([api.get("/dashboard"), api.get("/followups/due")]);
  const k = d.kpis;
  root.append(
    pageHeader("Dashboard", `As of ${d.as_of} · week ${d.periods.week[0]} to ${d.periods.week[1]}`),
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
