import { api, qs } from "../api.js";
import { h, clear, pageHeader, card, button, can, statusBadge, confirmBox, toast, errorMessage, debounce } from "../ui.js";
import { openInterviewForm } from "./interview_form.js";

export async function interviewsPage(root, params) {
  let rows = await api.get("/interviews" + qs({ candidate_id: params.candidate || "" }));
  let needle = "";
  const body = h("tbody");
  const filter = h("input", { type: "search", placeholder: "Filter entries...", "aria-label": "Filter entries" });
  const count = h("span", { class: "muted" });

  const reload = async () => { rows = await api.get("/interviews" + qs({ candidate_id: params.candidate || "" })); draw(); };

  async function remove(r) {
    if (!(await confirmBox("Delete entry", `Delete this entry for ${r.full_name}? The candidate's status is recalculated.`, "Delete", true))) return;
    try { await api.del("/interviews/" + r.id); toast("Entry deleted.", "success"); await reload(); } catch (e) { toast(errorMessage(e), "error"); }
  }

  function draw() {
    const shown = rows.filter((r) => !needle || Object.values(r).join(" ").toLowerCase().includes(needle)).reverse();
    count.textContent = `${shown.length} of ${rows.length} entries`;
    clear(body);
    if (!shown.length) body.append(h("tr", null, h("td", { colspan: 11, class: "empty" }, "No interview entries yet.")));
    shown.forEach((r) => body.append(h("tr", null,
      h("td", null, h("a", { href: "#/candidate/" + r.candidate_id }, r.candidate_id)), h("td", null, r.full_name), h("td", null, r.client || ""),
      h("td", null, r.interview_stage || ""), h("td", null, r.interview_date || "", r.interview_time ? " " + r.interview_time : ""),
      h("td", null, r.interviewer_panel || ""), h("td", { class: "wrap" }, r.feedback || ""), h("td", null, statusBadge(r.status)),
      h("td", null, r.next_action || ""), h("td", null, r.next_followup_date || ""),
      h("td", { class: "row-actions" }, can.write() ? button("Edit", () => openInterviewForm({ entry: r, onSaved: reload })) : null,
        can.admin() ? button("Delete", () => remove(r), "danger-text") : null))));
  }

  filter.addEventListener("input", debounce(() => { needle = filter.value.trim().toLowerCase(); draw(); }, 150));
  root.append(
    pageHeader("Interviews", params.candidate ? `Entries for ${params.candidate}` : "Every round, newest first. The latest entry sets the candidate's status.",
      can.write() ? button("New entry", () => openInterviewForm({ candidateId: params.candidate || "", onSaved: reload }), "primary") : null),
    card(null, h("div", { class: "toolbar" }, filter, count),
      h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, ["ID", "Candidate", "Client", "Stage", "When", "Panel", "Feedback", "Status", "Next action", "Follow-up", ""].map((x) => h("th", null, x)))),
        body))));
  draw();
}