// Client owner: create, review, and approve the offer letter template and compensation setup.
import { api } from "../api.js";
import { h, clear, card, pageHeader, field, button, toast, errorMessage, confirmBox, can, modal, table } from "../ui.js";
import { placeholderSummary, templateEditorButton, uploadSampleButton, statusBadge, previewGeneratedOffer } from "./offer.js";

const CALCS = [["pct_ctc", "% of CTC"], ["pct_basic", "% of Basic"], ["fixed", "Fixed amount"], ["balance", "Balance of the CTC"]];
const TYPICAL = [
  { key: "basic", label: "Basic Salary", kind: "earning", calc: "pct_ctc", value: "40", period: "monthly" },
  { key: "hra", label: "House Rent Allowance (HRA)", kind: "earning", calc: "pct_basic", value: "50", period: "monthly" },
  { key: "special", label: "Special Allowance", kind: "earning", calc: "balance", value: "", period: "annual" },
  { key: "employer_pf", label: "Employer Provident Fund (PF)", kind: "employer", calc: "pct_basic", value: "12", period: "monthly" },
  { key: "gratuity", label: "Gratuity Provision", kind: "employer", calc: "pct_basic", value: "4.81", period: "monthly" },
];

const slug = (label) => {
  const s = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30);
  return /^[a-z]/.test(s) ? s : "c_" + s.slice(0, 28);
};
const blank = (kind = "earning") => ({ key: "", label: "", kind, calc: "pct_ctc", value: "", period: "monthly", auto: true });
const toDraft = (list) => list.map((c) => ({ key: c.key, label: c.label, kind: c.kind, calc: c.calc, value: c.value === null ? "" : String(c.value), period: c.period || "monthly", auto: false }));
const withStandardParticulars = (components) => {
  const rows = [...components];
  const standards = TYPICAL.map((c) => c.key === "special" && rows.some((row) => row.calc === "balance")
    ? { ...c, calc: "fixed", value: "0" } : c);
  for (const standard of standards) {
    const existing = rows.find((c) => c.key === standard.key);
    if (existing) {
      existing.kind = standard.kind;
      continue;
    }
    rows.push({ ...standard, auto: false });
  }
  return rows;
};
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
  let queue = manage ? await api.get("/offer-letters/approval-queue").catch(() => ({ pending: [], approved: [] })) : { pending: [], approved: [] };
  let tagMappings = { ...(st.current?.tag_mappings || {}) };
  const editableState = (state) => manage && (!state.current || ["draft", "changes_requested", "in_review"].includes(state.current.status));
  const draftFromState = (state) => {
    const components = toDraft(state.current?.components || []);
    return editableState(state) ? withStandardParticulars(components) : components;
  };
  let draft = draftFromState(st);
  let templateUploading = false;
  let saveDraftButton = null;
  let approveButton = null;
  let approvalError = "";
  const setTemplateUploading = (busy) => {
    templateUploading = busy;
    if (saveDraftButton) saveDraftButton.disabled = busy;
    if (approveButton) approveButton.disabled = busy;
  };

  const reloadQueue = async () => {
    queue = await api.get("/offer-letters/approval-queue").catch(() => ({ pending: [], approved: [] }));
    draw();
  };
  const run = async (fn, okMsg) => {
    if (templateUploading) {
      toast("Wait for the template upload to finish before saving the draft.", "warn");
      return;
    }
    try { st = await fn(); draft = draftFromState(st); tagMappings = { ...(st.current?.tag_mappings || {}) }; if (okMsg) toast(okMsg, "success"); } catch (e) { toast(e.errors?.structure || e.errors?.tag_mappings || errorMessage(e), "error"); }
    draw();
  };
  const save = () => api.put(base, { components: toBody(draft), tag_mappings: tagMappings });

  function editor(editable) {
    const sections = [
      { kind: "earning", title: "Fixed & Allowances (Part of Gross Salary)", total: "Gross Salary (Subtotal)" },
      { kind: "employer", title: "Statutory Provisions (Part of CTC)", total: "Total Annual CTC" },
      { kind: "deduction", title: "Deductions (Outside CTC)", total: null },
    ];
    const sectionBodies = new Map(sections.map((s) => [s.kind, h("tbody")]));
    const paint = () => {
      for (const body of sectionBodies.values()) clear(body);
      draft.forEach((c, i) => {
        const standard = TYPICAL.some((item) => item.key === c.key);
        const key = h("input", { type: "text", value: c.key, maxlength: 30, "aria-label": "Key", disabled: !editable || standard });
        const label = h("input", { type: "text", value: c.label, maxlength: 60, "aria-label": "Particulars", disabled: !editable });
        const calc = options(CALCS, c.calc);
        const value = h("input", { type: "number", step: "any", min: "0", value: c.value, "aria-label": "Value", disabled: !editable || c.calc === "balance" });
        const period = options([["monthly", "per month"], ["annual", "per year"]], c.period);
        period.hidden = c.calc !== "fixed";
        for (const el of [calc, period]) el.disabled = !editable;
        label.addEventListener("input", () => {
          c.label = label.value;
          if (c.auto) { c.key = slug(label.value); key.value = c.key; }
        });
        key.addEventListener("input", () => { c.auto = false; c.key = key.value; });
        calc.addEventListener("change", () => { c.calc = calc.value; value.disabled = c.calc === "balance"; if (c.calc === "balance") { c.value = ""; value.value = ""; } period.hidden = c.calc !== "fixed"; });
        value.addEventListener("input", () => { c.value = value.value; });
        period.addEventListener("change", () => { c.period = period.value; });
        sectionBodies.get(c.kind)?.append(h("tr", null, h("td", null, label), h("td", null, key), h("td", null, calc), h("td", null, value, period),
          h("td", { class: "row-actions" }, editable ? button("Remove", () => { if (standard) { toast("Keep the standard compensation particular in the structure.", "warn"); return; } draft.splice(i, 1); paint(); }) : null)));
      });
      for (const section of sections) {
        const body = sectionBodies.get(section.kind);
        if (!draft.some((c) => c.kind === section.kind)) body.append(h("tr", null, h("td", { colspan: 5, class: "empty" }, "No components yet.")));
      }
    };
    paint();
    return h("div", { class: "stack" },
      ...sections.map((section) => h("section", { class: "stack" },
        h("h3", null, section.title),
        h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", null, h("tr", null, ["Particulars", "key (used in the letter)", "How it is worked out", "Value", ""].map((x) => h("th", null, x)))), sectionBodies.get(section.kind))),
        section.total ? h("p", { class: "muted" }, section.total, " is calculated automatically from the components in this section.") : null,
        editable ? h("div", { class: "card-actions" }, button(`Add ${section.kind === "earning" ? "fixed or allowance" : section.kind === "employer" ? "statutory provision" : "deduction"}`, () => { draft.push(blank(section.kind)); paint(); })) : null)),
      h("p", { class: "muted" }, "In the letter, use {{key_annual}} and {{key_monthly}} for each component, for example ",
        h("code", null, "{{basic_annual}}"), ". Totals are {{ctc_annual}}, {{ctc_monthly}}, {{gross_annual}} and {{gross_monthly}}. The CTC for each letter is entered when it is made."));
  }

  function view() {
    const cur = st.current;
    const status = cur?.status;
    const editable = manage && (!cur || ["draft", "changes_requested", "in_review"].includes(status));
    const feedback = status === "changes_requested" ? cur.events.slice().reverse().find((e) => e.kind === "feedback") : null;
    const out = [];
    if (manage) {
      const pendingRows = (queue.pending || []).map((letter) => h("tr", null,
        h("td", null, h("a", { href: "#/candidate/" + letter.candidate_id }, letter.candidate_id)),
        h("td", null, letter.candidate_name), h("td", null, letter.generated_by || ""),
        h("td", null, letter.created_at), h("td", null, "v" + letter.version),
        h("td", { class: "row-actions" }, button("Preview and approve", () => previewGeneratedOffer(letter.id,
          { canApprove: true, onApproved: reloadQueue }), "primary"))));
      const approvedRows = (queue.approved || []).slice().reverse().slice(0, 50).map((letter) => h("tr", null,
        h("td", null, h("a", { href: "#/candidate/" + letter.candidate_id }, letter.candidate_id)),
        h("td", null, letter.candidate_name), h("td", null, letter.generated_by || ""),
        h("td", null, letter.created_at), h("td", null, "v" + letter.version),
        h("td", { class: "row-actions" }, button("Download PDF", () => api.download(`/offer-letters/${letter.id}/pdf`, letter.filename)
          .catch((e) => toast(errorMessage(e), "error"))))));
      const queueTable = (rows, empty) => rows.length
        ? table(["Candidate ID", "Candidate", "Generated by", "Created", "Setup", ""], rows)
        : h("p", { class: "muted" }, empty);
      out.push(card("Offer letters awaiting your approval",
        h("p", { class: "muted" }, "Review each recruiter-generated PDF before approving it. Approved letters become available for download."),
        queueTable(pendingRows, "No offer letters are waiting for approval.")));
      out.push(card("Approved offer letters", queueTable(approvedRows, "No offer letters have been approved yet.")));
    }
    const editLetterButton = editable ? templateEditorButton(base + "/template/text", () => ({ ...(st.current || {}), components: draft.map((c) => ({ ...c })), template_text: st.current?.template_text || "" }), async (s) => { st = s; draw(); }) : null;
    if (editLetterButton) editLetterButton.id = "offer-letter-editor-button";

    if (feedback) out.push(h("div", { class: "notice warn" }, h("strong", null, "This draft needs changes"), h("small", { class: "muted" }, ` (${feedback.at}${feedback.by ? " · " + feedback.by : ""})`), h("p", null, feedback.note)));
    if (cur && status === "active") out.push(h("div", { class: "notice" }, `Version ${cur.version} is approved and active. Start a new draft to make changes.`));

    out.push(card(cur ? `Version ${cur.version}` : "Not started",
      h("div", null, cur ? statusBadge(cur.status) : h("span", { class: "muted" }, "Nothing has been set up for this company yet.")),
      st.active_version && status !== "active" ? h("small", { class: "muted" }, ` Version ${st.active_version} stays in use until this one is accepted.`) : null,
      cur && editable ? h("div", { class: "card-actions" }, button("Open draft", () => document.getElementById("offer-letter-editor-button")?.click())) : null,
      manage && status === "active" ? h("div", { class: "card-actions" }, button("Start a new draft", () => run(() => api.post(base + "/new-version"), "New draft started."), "primary")) : null));

    const compensationCard = card("Compensation components", editor(editable));
    compensationCard.id = "offer-draft-editor";
    out.push(compensationCard);

    out.push(card("Offer letter sample",
      h("p", { class: "muted" }, "Upload a sample offer letter or create one in the editor. Common compensation names are normalized automatically. Unmapped compensation tags are flagged below and can be mapped to a configured head or added as custom components. Annexure tables with Component/Particulars, Annual, and Monthly columns are populated from the compensation structure."),
      cur?.has_template ? h("div", null, h("strong", null, cur.template_name), " ", h("small", { class: "muted" }, cur.template_kind === "docx" ? "Word template" : "PDF template")) : h("p", { class: "muted" }, "No template created yet."),
        h("div", { class: "card-actions" },
          editable ? uploadSampleButton(base + "/template", async (s) => { st = s; draw(); }, cur?.has_template ? "Upload revised offer letter sample" : "Upload offer letter sample", setTemplateUploading) : null,
          editLetterButton),
      cur?.has_template ? placeholderSummary(cur.placeholders) : null));

    if (cur?.has_template) out.push(card("Review offer letter draft",
      h("p", { class: "muted" }, "Preview the offer letter with placeholder labels. Edit the draft above if the wording or fields need changes."),
      previewTemplate()));

    const pendingCustomTags = (cur?.placeholders?.unmapped_custom_tags || []).filter((tag) => {
      const key = tag.replace(/_(annual|monthly)$/, "");
      return !draft.some((component) => component.key === key);
    });
    if (editable && pendingCustomTags.length) {
      const mappingRows = pendingCustomTags.map((tag) => {
        const target = h("select", { "aria-label": `Map ${tag} to a compensation component` },
          h("option", { value: "" }, "Choose existing compensation head"),
          draft.map((component) => h("option", { value: component.key }, `${component.label} (${component.key})`)));
        target.value = tagMappings[tag] || "";
        target.addEventListener("change", () => {
          if (target.value) tagMappings[tag] = target.value;
          else delete tagMappings[tag];
        });
        return h("tr", null, h("td", null, h("code", null, "{{" + tag + "}}")), h("td", null, target));
      });
      out.push(card("Map custom compensation tags",
        h("p", { class: "notice warn" }, "These tags were saved in the template metadata. Map each one to an existing compensation head or add it as a custom component. Until mapped, the recruiter will be asked for its value."),
        table(["Template tag", "Compensation head"], mappingRows),
        h("div", { class: "card-actions" },
          button("Save mappings", () => run(save, "Custom tag mappings saved."), "primary"),
          button("Add as custom components", () => {
        pendingCustomTags.forEach((tag) => {
          delete tagMappings[tag];
          const key = slug(tag.replace(/_(annual|monthly)$/, ""));
          if (draft.some((component) => component.key === key)) return;
          draft.push({ key, label: key.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" "),
            kind: "earning", calc: "fixed", value: "0", period: "annual", auto: false });
        });
        draw();
        document.getElementById("offer-draft-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }))));
    }

    if (!manage) out.push(h("p", { class: "muted" }, "Only the client company owner can edit or approve this offer setup."));

    if (editable) {
      saveDraftButton = button("Save draft", () => run(save, "Draft saved."), "primary");
      saveDraftButton.disabled = templateUploading;
      out.push(h("div", { class: "card-actions" }, saveDraftButton));
    } else saveDraftButton = null;

    if (editable && cur) {
      out.push(card("Review and approve",
        h("p", { class: "muted" }, "Review the template preview and compensation components above. Approving activates this version for offer generation and downloads."),
        !cur.has_template ? h("p", { class: "notice warn" }, "Upload or create an offer letter template before approval.") : null,
        !cur.components.length ? h("p", { class: "notice warn" }, "Add at least one compensation component before approval.") : null,
        !cur.has_template ? h("div", { class: "card-actions" }, button("Edit offer letter draft", () => document.getElementById("offer-letter-editor-button")?.click())) : null,
        !cur.components.length ? h("div", { class: "card-actions" }, button("Add compensation components", () => document.getElementById("offer-draft-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }))) : null,
        h("p", { class: "muted" }, "To approve: save the offer letter draft, add and save at least one compensation component, then return here and approve the setup."),
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

    return out;
  }

  function draw() {
    clear(holder).append(...view());
  }

  root.append(pageHeader("Offer letter", "Upload or edit your template, configure compensation, review the draft in the page, and approve it here."), holder);
  draw();
}
