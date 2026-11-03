import { api } from "../api.js";
import { h, card, pageHeader, table, button, guarded, toast, statusBadge } from "../ui.js";
import { periodTable, hbar } from "./dashboard.js";

export async function reportsPage(root) {
  const [rep, d] = await Promise.all([api.get("/reports/recruiters"), api.get("/dashboard")]);
  const exportBtn = button("Download Excel report", null, "primary");
  exportBtn.onclick = guarded(exportBtn, async () => { await api.download("/export.xlsx", "ats_export.xlsx"); toast("Export downloaded.", "success"); });
  const num = (v) => h("td", { class: "num" }, v);
  root.append(
    pageHeader("Reports", "Recruiter activity, candidate pipeline, and client requirements", exportBtn),
    card("Recruiter activity", table(["Recruiter", "Candidates", "Vendor submissions", "Submissions", "Offers", "Yet to join", "Drops"], rep.map((r) =>
      h("tr", null, h("td", null, r.recruiter), num(r.candidates_added), num(r.vendor_submissions || 0), num(r.client_submissions), num(r.offers), num(r.yet_to_join), num(r.drops))))),
    card("Candidate status pipeline", hbar((d.pipeline || []).map((p) => ({ label: p.status, value: p.count })))),
    h("div", { class: "grid-2" },
      card("Candidates added", periodTable(d.recruiter_submissions)),
      card("Profiles submitted to clients", periodTable(d.client_submissions))),
    card("Client requirements", (d.recent_requirements || []).length
      ? table(["ATS Job ID", "Client", "Client job ID", "Role", "Status", "Primary skill", "Location", "Experience", "Budget", "Join within"],
        d.recent_requirements.map((j) => {
          const r = j.requirements || {};
          return h("tr", null,
            h("td", null, h("a", { href: "#/jobs/" + j.job_id }, j.job_id)),
            h("td", null, j.client || ""), h("td", null, j.client_ref || "—"), h("td", null, j.title || ""),
            h("td", null, statusBadge(j.status)), h("td", null, r.primary_skill || "—"),
            h("td", null, (r.locations || []).join(", ") || "—"),
            h("td", null, r.min_experience_years != null || r.max_experience_years != null
              ? `${r.min_experience_years ?? "Any"}–${r.max_experience_years ?? "Any"} years` : "—"),
            h("td", null, r.max_ctc_lakhs != null ? `${r.max_ctc_lakhs} LPA` : "—"),
            h("td", null, r.max_notice_days != null ? `${r.max_notice_days} days` : "—"));
        }))
      : h("p", { class: "muted" }, "No client requirements are available.")));
}
