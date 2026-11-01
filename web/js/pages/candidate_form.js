import { api, qs } from "../api.js";
import { h, clear, card, pageHeader, field, select, optionsFor, applyErrors, toast, errorMessage, button, can, state, statusBadge, confirmBox, debounce } from "../ui.js";
import { go } from "../router.js";
import { openInterviewForm } from "./interview_form.js";
import { offerLettersCard } from "./offer.js";

const SECTIONS = [
  ["Basics", ["date_added", "recruiter", "full_name", "current_company", "current_location", "primary_skill_role"]],
  ["Compensation and availability", ["total_experience_years", "current_ctc_lakhs", "expected_ctc_lakhs", "official_notice_period", "earliest_joining_date", "how_soon_can_join", "existing_offer", "offer_details"]],
  ["Contact", ["email", "phone", "date_of_birth"]],
  ["Client", ["client", "job_req_id", "profile_submitted_to_client", "client_submission_date"]],
  ["Notes", ["recruiter_notes"]],
];

function control(f, value) {
  const common = { dataset: { name: f.key } };
  if (f.type === "select") return select(optionsFor(f.list), value ?? "", common);
  if (f.type === "textarea") return h("textarea", { ...common, rows: 3, value: value ?? "" });
  const type = { number: "number", date: "date", email: "email" }[f.type] || "text";
  return h("input", { ...common, type, value: value ?? "", step: f.type === "number" ? "any" : null, min: f.type === "number" ? "0" : null });
}

export async function candidateFormPage(root, params) {
  const editing = Boolean(params.ref);
  const fields = new Map(state.meta.fields.map((f) => [f.key, f]));
  let record = editing ? await api.get(`/candidates/${params.ref}`) : null;
  const writable = can.write();
  const controls = {};
  const dupBox = h("div", { class: "notice warn", hidden: true, role: "status" });
  const save = h("button", { class: "btn primary", type: "submit", disabled: !writable }, editing ? "Save changes" : "Add candidate");

  const sections = SECTIONS.map(([title, keys]) => card(title, h("div", { class: "form-grid" }, keys.filter((k) => fields.has(k)).map((k) => {
    const f = fields.get(k);
    controls[k] = control(f, record ? record[k] : k === "date_added" ? state.meta.today : "");
    if (!writable) controls[k].disabled = true;
    return h("div", { class: k === "recruiter_notes" || k === "offer_details" ? "span-2" : "" }, field(f.label, controls[k], { hint: f.hint, flag: f.flag }));
  }))));
  const form = h("form", { class: "auth-form", novalidate: true }, sections, dupBox, h("div", { class: "actions sticky" },
    editing ? button("Back", () => history.back()) : button("Clear", () => go("/candidate/new?x=" + Date.now())), save));

  const checkDup = debounce(async () => {
    const v = (k) => controls[k]?.value || "";
    if (!v("full_name") && !v("email") && !v("phone")) { dupBox.hidden = true; return; }
    const hits = await api.get("/candidates/duplicates" + qs({ name: v("full_name"), email: v("email"), phone: v("phone"), exclude: record?.candidate_id || "" })).catch(() => []);
    clear(dupBox);
    dupBox.hidden = hits.length === 0;
    if (hits.length) {
      dupBox.append(h("strong", null, "Possible duplicate: "), ...hits.map((m) => m.other_source
        ? h("span", { class: "dup-hit" }, 'A matching candidate (same ${m.match.join(" + ")}) already exists in the client pipeline.')
        : h("span", { class: "dup-hit" },
          h("a", { href: "#/candidate/" + m.candidate_id }, `${m.candidate_id} ${m.full_name}`), ` (same ${m.match.join(" + ")}${m.recruiter ? ", " + m.recruiter : ""})`)),
        h("span", { class: "muted" }, "You can still save - this is only a warning."));
    }
  }, 400);
  ["full_name", "email", "phone"].forEach((k) => controls[k]?.addEventListener("input", checkDup));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    const body = {};
    for (const [k, el] of Object.entries(controls)) body[k] = el.value;
    try {
      if (editing) {
        record = await api.patch(`/candidates/${record.candidate_id}`, { ...body, version: record.version });
        toast("Changes saved.", "success");
      } else {
        const created = await api.post("/candidates", body);
        toast(`${created.candidate_id} added.` + (created.duplicate_matches.length ? " It looks like a possible duplicate." : ""), created.duplicate_matches.length ? "warn" : "success");
        go(`/candidate/${created.candidate_id}`);
        return;
      }
      applyErrors(form, {});
    } catch (ex) {
      if (ex.status === 409) {
        record = ex.current;
        toast("Someone else changed this candidate. The latest values are shown - review and save again.", "warn", 8000);
        for (const [k, el] of Object.entries(controls)) el.value = record[k] ?? "";
      } else {
        const orphans = applyErrors(form, ex.errors);
        if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
      }
    }
    save.disabled = !writable;
  });

  const badge = editing ? h("span", null, statusBadge(record.current_status)) : null;
  let letters = null;
  root.append(pageHeader(editing ? `${record.candidate_id} - ${record.full_name}` : "Add candidate",
    editing ? "Edit details, then review the interview history below." : "Fill in what you know. Required fields are marked with *.",
    badge,
    editing && writable ? button ("Generate offer letter", () => letters?.generate()) : null,
    editing && can.admin() ? button("Delete", async () => {
      if (!await confirmBox("Delete candidate", `Delete ${record.full_name}? They disappear from every list; the record is kept for audit.`, "Delete", true)) return;
      try { await api.del(`/candidates/${record.candidate_id}`); toast("Candidate deleted.", "success"); go("/candidates"); } catch (e) { toast(errorMessage(e), "error"); }
    }, "danger") : null));
  root.append(form);

  if (editing) {
    const history_ = h("div");
    const drawHistory = async () => {
      const rows = await api.get("/interviews" + qs({ candidate_id: record.candidate_id }));
      clear(history_).append(rows.length ? h("ol", { class: "timeline" }, rows.slice().reverse().map((r) => h("li", null,
        h("div", null, statusBadge(r.status), h("strong", null, `${r.interview_stage || "Interview"}`), h("small", { class: "muted" }, ` ${r.interview_date || r.created_at}`)),
        r.feedback ? h("p", null, r.feedback) : null,
        r.next_action ? h("p", { class: "muted" }, `Next: ${r.next_action}${r.next_followup_date ? " by " + r.next_followup_date : ""}`) : null))) 
        : h("p", { class: "muted" }, "No interviews recorded yet."));
    };
    await drawHistory();
    root.append(card("Interview history", writable ? h("div", { class: "card-actions" }, button("Add interview entry", () => openInterviewForm({
      candidate_id: record.candidate_id,
      onSaved: async () => { record = await api.get(`/candidates/${record.candidate_id}`); clear(badge).append(statusBadge(record.current_status)); await drawHistory(); toast(`Status is now ${record.current_status}.`, "info"); },
    }), "primary")) : null, history_));
    if (writable) {
      letters = offerLettersCard(record);
      root.append(letters.node);
    }
  }
  setTimeout(() => (editing ? controls.full_name : controls.full_name)?.focus(), 0);
}
