import { api } from "../api.js";
import { h, modal, field, select, optionsFor, candidatePicker, applyErrors, toast, errorMessage, button } from "../ui.js";

// Opens the interview entry modal. `entry` set = edit; otherwise create (optionally for a fixed candidate).
export function openInterviewForm({ entry = null, candidateId = "", onSaved }) {
  let ref = entry?.candidate_id || candidateId;
  const f = {
    interview_stage: h("input", { type: "text", maxLength: 200, dataset: { name: "interview_stage" }, value: entry?.interview_stage || "" }),
    interview_date: h("input", { type: "date", dataset: { name: "interview_date" }, value: entry?.interview_date || "" }),
    interview_time: h("input", { type: "time", dataset: { name: "interview_time" }, value: entry?.interview_time || "" }),
    interviewer_panel: h("input", { type: "text", dataset: { name: "interviewer_panel" }, value: entry?.interviewer_panel || "" }),
    feedback: h("textarea", { rows: 4, dataset: { name: "feedback" }, value: entry?.feedback || "" }),
    status: select(optionsFor("status"), entry?.status || "", { dataset: { name: "status" } }),
    next_action: h("input", { type: "text", dataset: { name: "next_action" }, value: entry?.next_action || "" }),
    next_followup_date: h("input", { type: "date", dataset: { name: "next_followup_date" }, value: entry?.next_followup_date || "" }),
  };
  const picker = candidatePicker({ value: entry ? `${entry.candidate_id} - ${entry.full_name}` : candidateId, onPick: (id) => { ref = id; } });
  picker.querySelector("input").dataset.name = "candidate_id";
  const save = h("button", { class: "btn primary", type: "submit" }, entry ? "Save changes" : "Add entry");
  const form = h("form", { class: "form-grid", novalidate: true },
    h("div", { class: "span-2" }, field("Candidate", picker, { flag: "Required" })),
    field("Stage / round", f.interview_stage), field("Status after this interview", f.status, { flag: "Required", hint: "Also becomes the candidate's current status." }),
    field("Interview date", f.interview_date), field("Time", f.interview_time),
    h("div", { class: "span-2" }, field("Interviewer panel", f.interviewer_panel)),
    h("div", { class: "span-2" }, field("Feedback", f.feedback)),
    field("Next action", f.next_action), field("Follow-up date", f.next_followup_date, { hint: "Appears under Follow-ups due." }),
    h("div", { class: "span-2 actions" }, button("Cancel", () => m.close()), save));
  const m = modal(entry ? "Edit interview entry" : "New interview entry", form, { wide: true });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    const body = { candidate_id: ref };
    for (const [k, el] of Object.entries(f)) body[k] = el.value;
    try {
      const saved = entry ? await api.put("/interviews/" + entry.id, body) : await api.post("/interviews", body);
      m.close();
      toast("Interview entry saved.", "success");
      await onSaved?.(saved);
    } catch (ex) {
      const orphans = applyErrors(form, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
      save.disabled = false;
    }
  });
}