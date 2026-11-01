// Rise Consulting: build a company's offer letter set-up (template + compensation components) and send it to the owner.
import { api, qs } from "../api.js";
import { h, clear, card, pageHeader, field, button, toast, errorMessage, confirmBox, state } from "../ui.js";
import { go } from "../router.js";
import { breakup, placeholderSummary, eventsList, uploadButton, withExt } from "./offer.js";

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

function options(list, value) {
  const s = h("select", null, list.map(([v, t]) => h("option", { value: v }, t)));
  s.value = value;
  return s;
}

export async function compensationPage(root, { id }) {
  const base = `/platform/companies/${id}/offer-structure`;
  const manage = (state.user.platform_permissions || []).includes("manage_compensation");
  const holder = h("div", { class: "stack" });
  let st = await api.get(base);
  let draft = toDraft(st.current?.components || []);
  let ctc = "";

  const reload = async (fromServer = false) => {
    st = await api.get(base + qs({ ctc }));
    if (fromServer) draft = toDraft(st.current?.components || []);
    draw();
  };
  const run = async (fn, okMsg) => {
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
    const editable = manage && (!cur || status === "draft" || status === "changes_requested");
    const feedback = status === "changes_requested" ? cur.events.slice().reverse().find((e) => e.kind === "feedback") : null;
    const out = [];

    if (feedback) out.push(h("div", { class: "notice warn" }, h("strong", null, "The owner asked for changes"), h("small", { class: "muted" }, ` (${feedback.at}${feedback.by ? " · " + feedback.by : ""})`), h("p", null, feedback.note)));
    if (cur && status === "active") out.push(h("div", { class: "notice" }, 'Version ${cur.version} is accepted and in use. ' + (manage ? "To change anything, start a new version; this one stays in use until the owner accepts the new one.": "")));
    if (cur && status === "in_review") out.push(h("div", { class: "notice" }, "This version is with the company owner for review and cannot be changed until they respond."));

    out.push(card(cur ? `Version ${cur.version}` : "Not started",
      h("div", null, cur ? statusBadge(cur.status) : h("span", { class: "muted" }, "Nothing has been set up for this company yet.")),
      st.active_version && status !== "active" ? h("small", { class: "muted" }, ` Version ${st.active_version} stays in use until this one is accepted.`) : null,
      manage && status === "active" ? h("div", { class: "card-actions" }, button("Start a new version", () => run(() => api.post(base + "/new-version"), "New version started."), "primary")) : null));

    out.push(card("Offer letter template",
      h("p", { class: "muted" }, "A Word (.docx) or text-based PDF file, up to 2 MB. The company owner can also upload it. Anything written as {{name}} becomes a field. Automatic fields: candidate_name, candidate_email, candidate_phone, candidate_id, designation, client, job_req_id, company_name, offer_date. Any other name is asked for when a letter is made."),
      cur?.has_template ? h("div", null, h("strong", null, cur.template_name), " ", h("small", { class: "muted" }, cur.template_kind === "pdf" ? "PDF" : "Word")) : h("p", { class: "muted" }, "No template uploaded yet."),
        h("div", { class: "card-actions" },
          cur?.has_template ? button("Download", () => api.download(base + "/template", withExt(cur.template_name, cur.template_kind)).catch((e) => toast(errorMessage(e), "error"))) : null,
          editable ? uploadButton(base + "/template", cur?.has_template ? "Replace template" : "Upload template" , async (s) => { st = s; draw(); }) : null),
      cur?.has_template ? placeholderSummary(cur.placeholders) : null));

    out.push(card("Compensation components", editor(editable)));
    if (editable) out.push(h("div", { class: "card-actions" }, button("Save", () => run(save, "Saved."), "primary")));
    if (!manage) out.push(h("p", { class: "muted" }, "You can look at this but not change it. Ask the creator for the compensation permission."));

    if (cur?.components.length) {
      const sample = h("input", { type: "text", inputmode: "numeric", placeholder: "e.g. 1200000", value: ctc, "aria-label": "Annual CTC to try" });
      out.push(card("Example breakup (saved components)",
        h("div", { class: "card-actions" }, field("Try an annual CTC (INR)", sample), button("Show", () => { ctc = sample.value.trim(); reload(); })),
        cur.preview ? breakup(cur.preview) : h("p", { class: "notice warn" }, cur.preview_error || "")));
    }

    if (editable && cur) {
      out.push(card("Send to the company owner",
        h("p", { class: "muted" }, "This saves your changes and locks the set-up while the owner reviews it. They can accept it or send feedback."),
        h("div", { class: "card-actions" }, button("Send for review", async () => {
          if (!await confirmBox("Send for review", `${st.company.name}'s owner will be asked to review and accept this set-up. You cannot change it until they respond.`, "Send")) return;
          try { await save(); } catch (e) { toast(e.errors?.structure || errorMessage(e), "error"); return; }
          run(() => api.post(base + "/send"), "Sent to the company owner.");
        }, "primary"))));
    }

    if (cur) out.push(card("History", eventsList(cur.events)));
    return out;
  }

  function draw() {
    clear(holder).append(...view());
  }

  root.append(pageHeader("Offer letter set-up: " + st.company.name, "The letter template and the compensation structure behind its pay fields.", button("Back to companies", () => go("/platform"))), holder);
  draw();
}