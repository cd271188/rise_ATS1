// Offer letters: the company owner's review page, the "generate a letter" dialog and the list of letters on a candidate.
import { api, qs } from "../api.js";
import { h, clear, card, pageHeader, table, field, modal, button, applyErrors, toast, errorMessage, confirmBox, can } from "../ui.js";
import { go } from "../router.js";

export const STATUS = { draft: "Draft", in_review: "In review", changes_requested: "Changes requested", active: "Accepted", superseded: "Replaced" };
const EVENT = { created: "Started", saved: "Compensation saved", template: "Template saved", sent: "Sent for review", accepted: "Accepted", feedback: "Feedback", note: "Note" };
const KIND = { earning: "Earning", employer: "Employer cost", deduction: "Deduction" };
const GROUPS = [
  ["automatic", "Filled in automatically from the portal"],
  ["compensation", "Filled in from the compensation structure"],
  ["asked", "Asked for each time a letter is made"]
];

export const statusBadge = (status) => h("span", { class: "badge s-" + (status === "active" ? "active" : status === "superseded" ? "inactive" : "pending") }, STATUS[status] || status);

export function describe(c) {
  if (c.calc === "pct_ctc") return `${c.value}% of CTC`;
  if (c.calc === "pct_basic") return `${c.value}% of Basic`;
  if (c.calc === "fixed") return `Fixed, INR ${c.value} per ${c.period === "annual" ? "year" : "month"}`;
  return "Balance of the CTC";
}

export function componentTable(components) {
  return table(["Component", "Type", "How it is worked out"], components.map((c) =>
    h("tr", null, h("td", null, c.label), h("td", null, h("code", null, c.key)), h("td", null, KIND[c.kind] || c.kind), h("td", null, describe(c)))));
}

export function breakup(p) {
  const rows = p.rows.map((r) => h("tr", null, h("td", null, r.label), h("td", null, KIND[r.kind] || r.kind), h("td", { class: "num" }, r.annual_text), h("td", { class: "num" }, r.monthly_text)));
  rows.push(h("tr", null, h("td", null, h("strong", null, "Gross (earnings)")), h("td", null, ""), h("td", { class: "num" }, h("strong", null, p.gross_text)), h("td", { class: "num" }, h("strong", null, p.gross_monthly_text))));
  rows.push(h("tr", null, h("td", null, h("strong", null, "Annual CTC")), h("td", null, ""), h("td", { class: "num" }, h("strong", null, p.ctc_text)), h("td", { class: "num" }, h("strong", null, p.ctc_monthly))));
  return h("div", null, table(["Component", "Type", "Per year (INR)", "Per month (INR)"], rows),
    p.unallocated ? h("p", { class: "notice warn" }, `INR ${p.unallocated_text} of the CTC is not allocated to any component.`) : null);
}

const names = (list) => list.map((n, i) => [i ? ", " : null, h("code", null, `{{ ${n} }}`)]);

export function placeholderSummary(ph) {
  if (ph.error) return h("p", { class: "notice warn" }, ph.error);
  const any = GROUPS.some(([k]) => ph[k].length);
  return h("div", { class: "stack" },
    any ? GROUPS.filter(([k]) => ph[k].length).map(([k, title]) => h("div", null, h("strong", null, title), h("div", null, names(ph[k])))) : h("p", { class: "muted" }, "No {{placeholders}} found in this file"),
    ph.unknown.length ? h("p", { class: "notice warn" }, "No compensation component matches: ", names(ph.unknown), ". Add that component, or fix the name in the letter.") : null,
    ph.malformed.length ? h("p", { class: "notice warn" }, "A {{ }} is broken near: ", ph.malformed.map((m) => h("em", null, `${m}`))) : null);
}

export function eventsList(events) {
  if (!events.length) return h("p", { class: "muted" }, "Nothing yet.");
  return h("ol", { class: "timeline" }, events.slice().reverse().map((e) => h("li", null,
    h("div", null, h("strong", null, EVENT[e.kind] || e.kind), h("small", { class: "muted" }, ` ${e.at}${e.by ? " · " + e.by : ""}`)),
    e.note && e.kind !== "saved" ? h("p", null, e.note) : null)));
}


export function uploadSampleButton(path, onDone, label = "Upload offer letter sample") {
  const input = h("input", { type: "file", accept: ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document", hidden: true });
  const upload = button(label, () => input.click());
  const status = h("small", { class: "muted", role: "status" });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) { input.value = ""; status.textContent = "No file selected."; return; }
    status.textContent = `Selected ${file.name}. Uploading…`;
    if (file.size > MAX_TEMPLATE) { input.value = ""; status.textContent = "Upload failed: sample must be smaller than 2 MB."; toast(status.textContent, "error"); return; }
    upload.disabled = true;
    upload.textContent = "Uploading…";
    let updated;
    try {
      const bytes = await file.arrayBuffer();
      updated = await api.putFile(path + "?filename=" + encodeURIComponent(file.name), bytes);
    } catch (e) {
      status.textContent = "Upload failed: " + (e.errors?.template || errorMessage(e));
      toast(status.textContent, "error");
    }
    finally {
      input.value = "";
      upload.disabled = false;
      upload.textContent = label;
    }
    if (!updated) return;
    status.textContent = `Uploaded ${file.name}.`;
    toast(label === "Upload revised template" ? "Revised template saved." : "Offer letter sample saved for review.", "success");
    try { await onDone(updated); }
    catch (e) {
      status.textContent = "Uploaded, but the page could not refresh: " + errorMessage(e);
      toast(status.textContent, "warn", 8000);
    }
  });
  return h("span", { class: "upload-sample-control" }, upload, input, status);
}

export function templateEditorButton(path, current, onDone) {
  return button(current?.has_template ? "Edit letter template" : "Create letter template", () => {
    const name = h("input", { type: "text", maxlength: 120, value: current?.template_name?.replace(/\.(pdf|docx)$/i, "") || "offer-letter", placeholder: "Offer letter name" });
    const content = h("textarea", { rows: 18, maxlength: 30000, placeholder: "Write the offer letter. Use {{candidate_name}}, {{candidate_id}}, {{company_name}}, {{offer_date}}, {{ctc_annual}}, and compensation keys such as {{basic_annual}}.", value: current?.template_text || "" });
    const save = h("button", { class: "btn primary", type: "button" }, "Save template");
    const body = h("div", { class: "stack" },
      current?.template_kind === "pdf" && !current.template_text ? h("p", { class: "notice warn" }, "This older PDF template cannot be loaded into the editor. Enter its content here to replace it with an editable template.") : null,
      field("Template name", name), field("Offer letter content", content),
      h("p", { class: "muted" }, "Use {{field_name}} for values filled automatically or requested when an offer is generated. Use one paragraph per line."),
      h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
    const m = modal("Offer letter template editor", body, { wide: true });
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        const state = await api.put(path, { filename: name.value, content: content.value });
        m.close();
        toast("Offer letter template saved.", "success");
        await onDone(state);
      } catch (e) {
        const why = e.errors?.content || errorMessage(e);
        toast(why, "error");
        save.disabled = false;
      }
    });
  });
}

export const withExt = (name, kind) => (name.toLowerCase().endsWith("." + kind) ? name : name + "." + kind);
export const offerReady = (candidate) => candidate?.process === "HR Discussion" && candidate?.current_status === "Yet to Offer";

// ---------------------------------------------------------------- the owner's page
export async function offerPage(root) {
  const holder = h("div", { class: "stack" });
  const owner = can.owner();
  let ctc = "";

  const act = async (fn, okMsg) => {
    try { await fn(); if (okMsg) toast(okMsg, "success"); } catch (e) { toast(errorMessage(e), "error"); }
    await draw();
  };

  function feedbackDialog(active) {
    const note = h("textarea", { rows: 5, dataset: { name: "note" }, placeholder: "What should Rise Consulting change?" });
    const send = h("button", { class: "btn primary", type: "submit" }, active ? "Send note" : "Send feedback");
    const form = h("form", { class: "stack", novalidate: true }, field("Your message", note),
      h("div", { class: "actions" }, button("Cancel", () => m.close()), send));
    const m = modal(active ? "Leave a note for Rise Consulting" : "Give feedback", form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      send.disabled = true;
      try {
        await api.post("/offer-structure/feedback", { note: note.value });
        m.close();
        toast("Sent to Rise Consulting.", "success");
        await draw();
      } catch (ex) {
        const orphans = applyErrors(form, ex.errors);
        if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
        send.disabled = false;
      }
    });
  }

  function statusText(cur, st) {
    const other = st.active_version && cur.status !== "active" ? ` Version ${st.active_version} stays in use until this one is accepted.` : "";
    switch (cur.status) {
      case "draft": return "Rise Consulting is preparing this. You will be asked to review it when it is ready." + other;
      case "in_review": return (owner ? "Please read the letter and the compensation below, then accept it or send your feedback." : "Waiting for the company owner to accept it.") + other;
      case "changes_requested": return "The feedback has gone to Rise Consulting, who will send a corrected version." + other;
      default: return "Accepted. The company owner can generate offer letters from a candidate's page. Recruiters and vendor users can download generated letters. Only Rise Consulting can change this set-up; leave a note if something needs to change.";
    }
  }

  function view(st) {
    const cur = st.current;
    const canUpload = owner && (!cur || ["draft", "changes_requested"].includes(cur.status));
    if (!cur) {
      return [card("Offer letter",
        h("p", null, "Upload a sample offer letter or create a template in the editor. Replace sample-specific candidate details with placeholders such as {{candidate_name}}, {{designation}}, and {{ctc_annual}}. Rise Consulting will set up compensation fields and send the draft back for your review and approval."),
        owner ? h("div", { class: "card-actions" }, uploadSampleButton("/offer-structure/template", draw), templateEditorButton("/offer-structure/template/text", cur, draw)) : h("p", { class: "muted" }, "The company owner has not provided an offer letter sample yet."))];
    }
    const out = [card(`Offer letter set-up · version ${cur.version}`,
      h("div", null, statusBadge(cur.status)),
      h("p", null, statusText(cur, st)),
      h("div", { class: "card-actions" },
        owner && cur.status === "in_review" ? [
          button("Accept", async () => {
            if (!(await confirmBox("Accept this set-up", "Offer letters will be made from this template and compensation structure. After this only Rise Consulting can change it.", "Accept"))) return;
            act(() => api.post("/offer-structure/accept"), "Accepted. Offer letters can now be made.");
          }, "primary"),
          button("Give feedback", () => feedbackDialog(false))] : null,
        owner && cur.status !== "in_review" ? button("Leave a note for Rise", () => feedbackDialog(true)) : null))];

    out.push(card("Letter template",
      cur.has_template ? h("div", null, h("strong", null, cur.template_name), " ", h("small", { class: "muted" }, cur.template_kind === "docx" ? "Word template" : "PDF template"),
        h("div", { class: "card-actions" }, button("Download draft for review", () => api.download("/offer-structure/template", withExt(cur.template_name, cur.template_kind)).catch((e) => toast(errorMessage(e), "error"))),
          canUpload ? uploadSampleButton("/offer-structure/template", draw) : null,
          canUpload ? templateEditorButton("/offer-structure/template/text", cur, draw) : null)) :
        h("div", null, h("p", { class: "muted" }, "No template yet."), canUpload ? h("div", { class: "card-actions" }, uploadSampleButton("/offer-structure/template", draw), templateEditorButton("/offer-structure/template/text", cur, draw)) : null),
      cur.has_template ? placeholderSummary(cur.placeholders) : null));

    const sample = h("input", { type: "text", inputmode: "numeric", placeholder: "e.g. 1200000", value: ctc, "aria-label": "Annual CTC to try" });
    out.push(card("Compensation structure",
      cur.components.length ? [componentTable(cur.components),
        h("h4", null, "Example breakup"),
        h("div", { class: "card-actions" }, field("Try an annual CTC (INR)", sample), button("Show", () => { ctc = sample.value.trim(); draw(); })),
        cur.preview ? breakup(cur.preview) : h("p", { class: "notice warn" }, cur.preview_error || "")] :
        h("p", { class: "muted" }, "Rise Consulting has not defined the compensation components yet.")));

    out.push(card("History", eventsList(cur.events)));
    return out;
  }

  async function draw() {
    const st = await api.get("/offer-structure" + qs({ ctc }));
    clear(holder).append(...view(st));
  }

  root.append(pageHeader("Offer letter", "Create your letter template, then review the compensation structure Rise Consulting prepares for it."), holder);
  await draw();
}

// ---------------------------------------------------------------- making a letter for a candidate
export async function generateOfferDialog(record, onDone) {
  const ref = record.candidate_id;
  let setup;
  try { setup = await api.get(`/candidates/${ref}/offer-letters/form`); } catch (e) {
    const message = errorMessage(e);
    const notReady = Object.values(e.errors || {}).some((value) => /offer letters are not set up yet|owner has to accept/i.test(value));
    if (notReady) {
      const owner = can.admin() && !can.vendor();
      const body = h("div", { class: "stack" },
        h("p", { class: "notice warn" }, "Offer letters are not ready for this company yet."),
        h("p", null, can.vendor()
          ? "The client company owner must have an offer template and compensation setup accepted before a vendor recruiter can generate a letter. Ask the client owner to finish the setup, then try again."
          : "An offer template and compensation setup must be accepted by the company owner before a letter can be generated."),
        h("p", { class: "muted" }, message),
        h("div", { class: "actions" }, button("Close", () => m.close()), owner ? button("Open Offer letter setup", () => { m.close(); go("/offer"); }, "primary") : null));
      const m = modal("Offer letter setup required", body);
    } else toast(message, "error");
    return;
  }

  const ctc = h("input", { type: "text", inputmode: "numeric", dataset: { name: "ctc" }, placeholder: "e.g. 1200000" });
  const preview = h("div");
  const inputs = setup.inputs.map((i) => [i, h("input", { type: "text", dataset: { name: i.name }, maxlength: 200 })]);
  const make = h("button", { class: "btn primary", type: "submit" }, "Generate PDF");

  const form = h("form", { class: "stack", novalidate: true },
    h("p", { class: "muted" }, `Uses the accepted set-up (version ${setup.version}). The letter is dated today.`),
    setup.automatic.length ? h("div", null, h("strong", null, "From the portal"),
      h("ul", { class: "plain" }, setup.automatic.map((a) => h("li", null, `${a.label}: `, a.value ? h("strong", null, a.value) : h("em", { class: "muted" }, "(empty - fill it in on the candidate first)"))))) : null,
    setup.needs_ctc ? [field("Annual CTC (INR)", ctc, { hint: "Whole rupees per year. The breakup below is worked out from the accepted structure." }),
      h("div", { class: "card-actions" }, button("Show breakup", async () => {
        try { clear(preview).append(breakup(await api.post(`/candidates/${ref}/offer-letters/preview`, { ctc: ctc.value }))); applyErrors(form, {}); } catch (ex) {
          const orphans = applyErrors(form, ex.errors);
          if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
        }
      })), preview] : null,
    inputs.map(([i, el]) => field(i.label, el)),
    h("div", { class: "actions" }, button("Cancel", () => m.close()), make));

  const m = modal(`Offer letter for ${record.full_name}`, form, { wide: true });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    make.disabled = true;
    try {
      const letter = await api.post(`/candidates/${ref}/offer-letters`, { ctc: ctc.value, inputs: Object.fromEntries(inputs.map(([i, el]) => [i.name, el.value])) });
      m.close();
      toast("Offer letter ready.", "success");
      await api.download(`/offer-letters/${letter.id}/pdf`, letter.filename).catch((ex) => toast(errorMessage(ex), "error"));
      if (onDone) await onDone();
    } catch (ex) {
      const orphans = applyErrors(form, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
      make.disabled = false;
    }
  });
}

// The "Offer letters" card on a candidate. Returns { node, generate } so the page header can open the same dialog.
export function offerLettersCard(record) {
  const list = h("div");
  const downloads = [];
  const make = button("Generate offer letter", () => generate(), "primary");
  const refreshAvailability = () => {
    const ready = offerReady(record);
    make.disabled = !ready;
    make.title = ready ? "Generate offer letter" : "Available when Process is HR Discussion and Interview Status is Yet to Offer";
    downloads.forEach((download) => { download.disabled = !ready; download.title = make.title; });
  };
  const draw = async () => {
    try {
      const rows = await api.get(`/candidates/${record.candidate_id}/offer-letters`);
      downloads.length = 0;
      const rowsEl = rows.map((r) => {
        const download = button("Download PDF", () => api.download(`/offer-letters/${r.id}/pdf`, r.filename).catch((e) => toast(errorMessage(e), "error")));
        downloads.push(download);
        return h("tr", null, h("td", null, r.created_at), h("td", null, r.generated_by || ""), h("td", null, "v" + r.version),
          h("td", { class: "row-actions" }, download));
      });
      clear(list).append(table(["Made on", "Made by", "Set-up version", ""], rowsEl));
      refreshAvailability();
    } catch (e) { clear(list).append(h("p", { class: "muted" }, errorMessage(e))); }
  };
  const generate = () => generateOfferDialog(record, draw);
  refreshAvailability();
  const node = card("Offer letters", can.owner() && !can.vendor() ? h("div", { class: "card-actions" }, make) : null, list);
  draw();
  return { node, generate, refreshAvailability };
}
