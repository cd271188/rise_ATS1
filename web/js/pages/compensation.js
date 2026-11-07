// Client owner: create, review, and approve the offer letter template and compensation setup.
import { api, qs } from "../api.js";
import { h, clear, card, pageHeader, field, button, toast, errorMessage, confirmBox, can, modal } from "../ui.js";
import { breakup, placeholderSummary, eventsList, templateEditorButton, uploadSampleButton, statusBadge } from "./offer.js";

const KINDS = [["earning", "Earning (paid to the employee)"], ["employer", "Employer cost (part of CTC)"], ["deduction", "Deduction (outside CTC)"]];
const CALCS = [["pct_ctc", "% of CTC"], ["pct_basic", "% of Basic"], ["fixed", "Fixed amount"], ["balance", "Balance of the CTC"]];
const TYPICAL = [
  { key: "basic", label: "Basic", kind: "earning", calc: "pct_ctc", value: "40", period: "monthly" },
  { key: "hra", label: "House rent allowance", kind: "earning", calc: "pct_basic", value: "50", period: "monthly" },
  { key: "employer_pf", label: "Employer PF", kind: "employer", calc: "pct_basic", value: "12", period: "monthly" },
  { key: "special", label: "Special allowance", kind: "earning", calc: "balance", value: "", period: "monthly" },
];

const slug = (label) => {
  const s = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30);
  return /^[a-z]/.test(s) ? s : "c_" + s.slice(0, 28);
};
const blank = () => ({ key: "", label: "", kind: "earning", calc: "pct_ctc", value: "", period: "monthly", auto: true });
const toDraft = (list) => list.map((c) => ({ key: c.key, label: c.label, kind: c.kind, calc: c.calc, value: c.value === null ? "" : String(c.value), period: c.period || "monthly", auto: false }));
const toBody = (draft) => draft.map((c) => ({ key: c.key.trim(), label: c.label, kind: c.kind, calc: c.calc,
  value: c.calc === "balance" ? null : c.value === "" ? "" : Number(c.value), period: c.calc === "fixed" ? c.period : null }));

function previewTemplate() {
  return button("Preview draft", async () => {
    try {
      const url = URL.createObjectURL(await api.getBlob("/offer-structure/template/preview"));
      const frame = h("iframe", { title: "Offer letter template preview", class: "offer-template-frame", src: url });
      let m;
      m = modal("Offer letter draft preview", h("div", null, frame,
        h("div", { class: "actions" }, button("Close", () => { m.close(); URL.revokeObjectURL(url); })) ), { wide: true });
    } catch (e) { toast(errorMessage(e), "error"); }
  });
}

function options(list, value) {
  const s = h("select", null, list.map(([v, t]) => h("option", { value: v }, t)));
  s.value = value;
  return s;
}

export async function compensationPage(root) {
  const base = "/offer-structure";
  const manage = can.owner() && !can.vendor();
  const holder = h("div", { class: "stack" });
  let st = await api.get(base);
  let draft = toDraft(st.current?.components || []);
  let ctc = "";
  let templateUploading = false;
  let saveDraftButton = null;
  let approveButton = null;
  let approvalError = "";
  const setTemplateUploading = (busy) => {
    templateUploading = busy;
    if (saveDraftButton) saveDraftButton.disabled = busy;
    if (approveButton) approveButton.disabled = busy;
  };

  const reload = async (fromServer = false) => {
    st = await api.get(base + qs({ ctc }));
    if (fromServer) draft = toDraft(st.current?.components || []);
    draw();
  };
  const run = async (fn, okMsg) => {
    if (templateUploading) {
      toast("Wait for the template upload to finish before saving the draft.", "warn");
      return;
    }
    try { st = await fn(); draft = toDraft(st.current?.components || []); if (okMsg) toast(okMsg, "success"); } catch (e) { toast(e.errors?.structure || errorMessage(e), "error"); }
    draw();
  };
  const save = () => api.put(base, { components: toBody(draft) });

  function editor(editable) {
    const body = h("tbody");
    const paint = () => {
      clear(body);
      draft.forEach((c, i) => {
        const key = h("input", { type: "text", value: c.key, maxlength: 30, "aria-label": "Key", disabled: !editable });
        const label = h("input", { type: "text", value: c.label, maxlength: 60, "aria-label": "Name", disabled: !editable });
        const kind = options(KINDS, c.kind);
        const calc = options(CALCS, c.calc);
        const value = h("input", { type: "number", step: "any", min: "0", value: c.value, "aria-label": "Value", disabled: !editable || c.calc === "balance" });
        const period = options([["monthly", "per month"], ["annual", "per year"]], c.period);
        period.hidden = c.calc !== "fixed";
        for (const el of [kind, calc, period]) el.disabled = !editable;
        label.addEventListener("input", () => { if (c.auto) { c.key = slug(label.value); key.value = c.key; } });
        key.addEventListener("input", () => { c.auto = false; c.key = key.value; });
        kind.addEventListener("change", () => { c.kind = kind.value; });
        calc.addEventListener("change", () => { c.calc = calc.value; value.disabled = c.calc === "balance"; if (c.calc === "balance") { c.value = ""; value.value = ""; } period.hidden = c.calc !== "fixed"; });
        value.addEventListener("input", () => { c.value = value.value; });
        period.addEventListener("change", () => { c.period = period.value; });
        body.append(h("tr", null, h("td", null, label), h("td", null, key), h("td", null, kind), h("td", null, calc), h("td", null, value, period),
          h("td", { class: "row-actions" }, editable ? button("Remove", () => { draft.splice(i, 1); paint(); }) : null)));
      });
      if (!draft.length) body.append(h("tr", null, h("td", { colspan: 6, class: "empty" }, "No components yet.")));
    };
    paint();
    return h("div", { class: "stack" },
      h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", null, h("tr", null, ["Name", "key (used in the letter)", "Type", "How it is worked out", "Value", ""].map((x) => h("th", null, x)))), body)),
      editable ? h("div", { class: "card-actions" },
        button("Add component", () => { draft.push(blank()); paint(); }),
        draft.length ? null : button("Start from a typical structure", () => { draft = TYPICAL.map((c) => ({ ...c, auto: false })); paint(); })) : null,
      h("p", { class: "muted" }, "In the letter, use {{key_annual}} and {{key_monthly}} for each component, for example ",
        h("code", null, "{{basic_annual}}"), ". Totals are {{ctc_annual}}, {{ctc_monthly}}, {{gross_annual}} and {{gross_monthly}}. The CTC for each letter is entered when it is made."));
  }

  function view() {
    const cur = st.current;
    const status = cur?.status;
    const editable = manage && (!cur || ["draft", "changes_requested", "in_review"].includes(status));
    const feedback = status === "changes_requested" ? cur.events.slice().reverse().find((e) => e.kind === "feedback") : null;
    const out = [];

    if (feedback) out.push(h("div", { class: "notice warn" }, h("strong", null, "This draft needs changes"), h("small", { class: "muted" }, ` (${feedback.at}${feedback.by ? " · " + feedback.by : ""})`), h("p", null, feedback.note)));
    if (cur && status === "active") out.push(h("div", { class: "notice" }, `Version ${cur.version} is approved and active. Start a new draft to make changes.`));

    out.push(card(cur ? `Version ${cur.version}` : "Not started",
      h("div", null, cur ? statusBadge(cur.status) : h("span", { class: "muted" }, "Nothing has been set up for this company yet.")),
      st.active_version && status !== "active" ? h("small", { class: "muted" }, ` Version ${st.active_version} stays in use until this one is accepted.`) : null,
      cur && editable ? h("div", { class: "card-actions" }, button("Open draft", () => document.getElementById("offer-draft-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }))) : null,
      manage && status === "active" ? h("div", { class: "card-actions" }, button("Start a new draft", () => run(() => api.post(base + "/new-version"), "New draft started."), "primary")) : null));

    out.push(card("Offer letter template",
      h("p", { class: "muted" }, "Upload your sample or create the template in the editor. Replace sample-specific details with placeholders such as {{candidate_name}}, {{designation}}, {{offer_date}} and compensation fields such as {{basic_annual}}."),
      cur?.has_template ? h("div", null, h("strong", null, cur.template_name), " ", h("small", { class: "muted" }, cur.template_kind === "docx" ? "Word template" : "PDF template")) : h("p", { class: "muted" }, "No template created yet."),
        h("div", { class: "card-actions" },
          editable ? uploadSampleButton(base + "/template", async (s) => { st = s; draft = toDraft(s.current?.components || []); draw(); }, cur?.has_template ? "Upload revised template" : "Upload offer letter sample", setTemplateUploading) : null,
          editable ? templateEditorButton(base + "/template/text", cur, async (s) => { st = s; draft = toDraft(s.current?.components || []); draw(); }) : null),
      cur?.has_template ? placeholderSummary(cur.placeholders) : null));

    if (cur?.has_template) out.push(card("Review template",
      h("p", { class: "muted" }, "Preview the offer letter with placeholder labels. Edit the draft above if the wording or fields need changes."),
      previewTemplate()));
    
    const compensationCard = card("Compensation components", editor(editable));
    compensationCard.id = "offer-draft-editor";
    out.push(compensationCard);
    if (editable) {
      saveDraftButton = button("Save draft", () => run(save, "Draft saved."), "primary");
      saveDraftButton.disabled = templateUploading;
      out.push(h("div", { class: "card-actions" }, saveDraftButton));
    } else saveDraftButton = null;
    if (!manage) out.push(h("p", { class: "muted" }, "Only the client company owner can edit or approve this offer setup."));

    if (cur?.components.length) {
      const sample = h("input", { type: "text", inputmode: "numeric", placeholder: "e.g. 1200000", value: ctc, "aria-label": "Annual CTC to try" });
      out.push(card("Example breakup (saved components)",
        h("div", { class: "card-actions" }, field("Try an annual CTC (INR)", sample), button("Show", () => { ctc = sample.value.trim(); reload(); })),
        cur.preview ? breakup(cur.preview) : h("p", { class: "notice warn" }, cur.preview_error || "")));
    }

    if (editable && cur) {
      out.push(card("Review and approve",
        h("p", { class: "muted" }, "Review the template preview and compensation breakup above. Approving activates this version for offer generation and downloads."),
        !cur.has_template ? h("p", { class: "notice warn" }, "Upload or create an offer letter template before approval.") : null,
        !cur.components.length ? h("p", { class: "notice warn" }, "Add at least one compensation component before approval.") : null,
        approvalError ? h("p", { class: "notice warn" }, approvalError) : null,
        h("div", { class: "card-actions" }, approveButton = button("Approve offer letter setup", async () => {
          if (!(await confirmBox("Approve offer letter setup", "This template and compensation structure will become active. Offer letters can then be generated for eligible candidates.", "Approve"))) return;
          approvalError = "";
          try {
            st = await save();
            st = await api.post(base + "/accept");
            draft = toDraft(st.current?.components || []);
            toast("Offer setup approved.", "success");
          } catch (e) { approvalError = e.errors?.structure || errorMessage(e); toast(approvalError, "error"); }
          draw();
        }, "primary"))));
    approveButton.disabled = templateUploading || !cur.has_template || !cur.components.length;
    } else approveButton = null;

    if (cur) out.push(card("History", eventsList(cur.events)));
    return out;
  }

  function draw() {
    clear(holder).append(...view());
  }

  root.append(pageHeader("Offer letter", "Upload or edit your template, configure compensation, review the draft in the page, and approve it here."), holder);
  draw();
}
