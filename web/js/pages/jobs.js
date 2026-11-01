import { api, qs } from "../api.js";
import { h, clear, card, pageHeader, field, modal, button, guarded, table, can, state, statusBadge, toast, errorMessage, applyErrors, confirmBox } from "../ui.js";
import { go } from "../router.js";

const chips = (items, cls) => (items.length ? h("div", { class: "chips" }, items.map((s) => h("span", { class: "chip " + cls }, s))) : h("span", { class: "muted" }, "-"));

function scorebar(score) {
  const level = score >= 70 ? "good" : score >= 40 ? "mid" : "low";
  const fill = h("div", { class: `score-fill ${level}` });
  fill.style.width = score + "%";
  return h("div", { class: "score" }, h("div", { class: "score-bar", role: "img", "aria-label": `Match ${score} percent` }, fill), h("strong", null, score + "%"));
}

function matchResults(res, { keywords = false } = {}) {
  const notes = [];
  if (res.pending_index > 0) notes.push(`${res.pending_index} candidate(s) are still being indexed and are ranked without the similarity score. Search again in a moment to include`);
  if (res.total > res.items.length) notes.push(`Showing the top ${res.items.length} of ${res.total} matches.`);
  const head = ["Candidate", "Match", keywords ? "Found" : "Matched skills", ...(keywords ? [] : ["Missing"]), "Flags", "Profile"];
  const rows = res.items.map((m) => h("tr", null,
    h("td", null, h("a", { href: "#/candidate/" + m.candidate_id }, `${m.candidate_id} ${m.full_name}`), h("div", null, statusBadge(m.current_status))),
    h("td", null, scorebar(m.score)),
    h("td", null, chips(keywords ? m.matched : m.matched, "good")),
    keywords ? null : h("td", null, chips(m.missing, "bad")),
    h("td", null, m.flags.length ? m.flags.map((f) => h("span", { class: "badge warn-badge" }, f)) : h("span", { class: "muted" }, "-")),
    h("td", null, h("small", null, [m.primary_skill_role, m.current_company, m.current_location,
      m.total_experience_years != null ? m.total_experience_years + " yrs" : null, m.official_notice_period].filter(Boolean).join(" . ")))));
  return h("div", null, notes.map((n) => h("p", { class: "notice warn" }, n)),
    table(head, rows, "matches"),
    res.items.length ? null : h("p", { class: "muted" }, keywords ? "No Candidates mention these terms." : "No candidates match yet"));
}

const JD_TYPES = ".docx, .pdf, application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const MAX_JD = 5 * 1024 * 1024;
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

function newJobDialog({ companyId = null } = {}) {
  const aiOn = !!state.meta?.ai_enabled;
  const inp = (name, props = {}) => h("input", { type: "text", dataset: { name }, ...props });
  const f = {
    client: inp("client", { maxlength: 200, list: "job-clients", autocomplete: "off", required: true }), client_ref: inp("client_ref", { maxlength: 100, autocomplete: "off", required: true }),
    title: inp("title", { maxlength: 200, required: true }), received_on: inp("received_on", { type: "date", value: today() }),
    primary_skill: inp("primary_skill", { maxlength: 60, required: true }), loc: inp("locations", { required: true }),
    min: inp("min_experience_years", { type: "number", min: 0, step: "any", required: true }), max: inp("max_experience_years", { type: "number", min: 0, step: "any", required: true }),
    ctc: inp("max_ctc_lakhs", { type: "number", min: 0, step: "any", required: true }), notice: inp("max_notice_days", { type: "number", min: 0, required: true }),
  };
    const jd = h("textarea", { rows: 8, dataset: { name: "jd_text" }, placeholder: "Paste the job description here, or upload the file below" });
    const file = h("input", { type: "file", accept: JD_TYPES, "aria-label": "Job description file" });
    const create = button("Create job", null, "primary");
    const body = h("form", { class: "stack" },
      h("datalist", { id: "job-clients" }, (state.meta?.lists?.clients || []).map((c) => h("option", { value: c }))),
      h("div", { class: "form-grid" },
        field("Client *", f.client, { hint: "Add client names in Settings > Clients, or type a new name here." }),
        field("ATS Job ID", h("input", { type: "text", value: "Assigned automatically after saving", disabled: true }), { hint: "The ATS assigns a unique ID when you create this requirement." }),
        field("Client-provided Job ID *", f.client_ref, { hint: "Enter the job number or role ID given by the client." }),
        field("Role *", f.title), field("Request received on", f.received_on),
        field("Primary skill *", f.primary_skill, { hint: "The main skill. Candidates are always checked against it." }), field("Location *", f.loc, { hint: "Separate several with commas" }),
        field("Experience from (years) *", f.min), field("Experience up to (years) *", f.max),
        field("Budget (LPA) *", f.ctc, { hint: "Candidates expecting more are flagged." }), field("Needs to join within (days) *", f.notice, { hint: "How soon the candidate must be able to join." })),
      field("Job description", jd, { hint: aiOn ? "AI reads it once to fill any requirement you left blank. What you type above is kept as you typed it." : "AI is not set up, so enter the requirements above by hand." }),
      field("Or upload the job description file", file, { hint: "Word (.docx) or text-based PDF, up to 5 MB." }),
      h("div", { class: "actions" }, button("Cancel", () => m.close()), create));
    const m = modal("New job", body, { wide: true });
    create.type = "submit"; 
    body.addEventListener("submit", guarded(create, async () => {
      const picked = file.files[0];
      if (picked && picked.size > MAX_JD) { toast("The job description file must be smaller than 5 MB.", "error"); return; }
      let j;
      try {
        j = await api.post("/jobs", {
          ...(companyId ? { company_id: companyId } : {}),
          title: f.title.value, client: f.client.value, client_ref: f.client_ref.value, received_on: f.received_on.value, jd_text: jd.value,
          requirements: { primary_skill: f.primary_skill.value, locations: f.loc.value, min_experience_years: f.min.value, max_experience_years: f.max.value,
            max_ctc_lakhs: f.ctc.value, max_notice_days: f.notice.value },
        });
      } catch (e) {
        const orphans = applyErrors(body, e.errors);
        toast(orphans.join("; ") || errorMessage(e), "error");
        return;
      }
      m.close();
      let note = j.warning;
      if (picked && !companyId) {
        try {
          const up = await api.upload(`/jobs/${j.job_id}/jd?filename=${encodeURIComponent(picked.name)}`, await picked.arrayBuffer());
          note = note || up.warning;
        } catch (e) { note = `${j.job_id} was created but the file was not attached: ${e.errors?.file || errorMessage(e)}`; }
      }
      if (note) toast(`${j.job_id} · ${note}`, "warn", 8000);
      else toast(`ATS Job ID ${j.job_id} created.`, "success");
      if (!companyId) go("/jobs/" + j.job_id);
    }));
  return m;
}

function searchCard() {
  const q = h("textarea", { rows: 3, "aria-label": "Keywords or job description", placeholder: "Keywords, e.g. python, machine learning, kubernetes ... or paste a whole job description" });
  const minScore = h("select", { "aria-label": "Minimum match" }, [["0", "Any match"], ["30", "At least 30%"], ["50", "At least 50%"], ["70", "At least 70%"]].map(([v, t]) => h("option", { value: v }, t)));
  const noFlags = h("input", { type: "checkbox" });
  const out = h("div");
  const go_ = button("Search CVs", null, "primary");
  const runSearch = async () => {
    if (!q.value.trim()) { toast("Enter keywords or a job description to search CVs.", "error"); q.focus(); return; }
    clear(out).append(h("p", { class: "muted" }, "Searching candidates…"));
    try {
      const res = await api.post("/match", { q: q.value.trim(), min_score: Number(minScore.value), exclude_flagged: noFlags.checked });
      clear(out);
      if (res.mode === "jd") out.append(h("p", { class: "muted" }, "Read as a job description. Must-have: ", (res.requirements.must_have_skills || []).join(", ") || "none found", "."));
      out.append(matchResults(res, { keywords: res.mode === "keywords" }));
    } catch (e) {
      clear(out).append(h("p", { class: "notice error" }, errorMessage(e)));
      toast(errorMessage(e), "error");
    }
  };
  go_.onclick = guarded(go_, runSearch);
  return card("Find candidates",
    h("p", { class: "muted" }, "Short searches look for the words in each candidate's skills and dull CV text (nothing is sent to AI). Put a phrase in the quotes to match it exactly. A pasted job description is read once by AI."),
    q, h("div", { class: "toolbar" }, minScore, h("label", { class: "inline" }, noFlags, "Hide candidates with Flags"), h("span", { class: "spacer" }), go_), out);
}

export async function jobsPage(root, params = {}) {
  const platform = can.platform();
  const writable = can.write();
  const platformCanCreate = can.creator() || (state.user.platform_permissions || []).includes("create_job_requirements");
  let companyId = Number(params.company_id || 0) || null;
  let companies = [];
  if (platform && platformCanCreate) companies = await api.get("/platform/companies");
  const companySelect = platform ? h("select", { "aria-label": "Client company" }, [h("option", { value: "" }, "Choose a client company"), ...companies.map((c) => h("option", { value: c.id }, c.name))]) : null;
  if (companySelect && companyId) companySelect.value = String(companyId);
  const status = h("select", { "aria-label": "Status" }, [["", "All jobs"], ["Open", "Open"], ["Closed", "Closed"]].map(([v,t]) => h("option", { value: v }, t)));
  const list = h("div");
  const draw = async () => {
    if (platform && !companyId) { clear(list).append(h("p", { class: "muted" }, "Choose a client company to view its requirements.")); return; }
    const { items } = await api.get("/jobs" + qs({ status: status.value, company_id: platform ? companyId : null }));
    clear(list).append(table(["ATS Job ID", "Client", "Client-provided Job ID", "Role", "Received", "Status", "Updated"], items.map((j) => h("tr", null,
      h("td", null, platform ? h("span", null, j.job_id) : h("a", { href: "#/jobs/" + j.job_id }, j.job_id)), h("td", null, j.client || ""), h("td", null, j.client_ref || ""), h("td", null, j.title),
      h("td", null, j.received_on || ""), h("td", null, statusBadge(j.status)), h("td", null, j.last_updated)))));
  };
  status.addEventListener("change", draw);
  companySelect?.addEventListener("change", () => { companyId = Number(companySelect.value) || null; draw(); });
  const create = platform ? platformCanCreate : writable;
  root.append(...[
    pageHeader("Client Requirements", platform ? "Choose a client company to add its job requirements." : "Add a client job request, enter its requirements, then find matching candidates. Manage client names in Settings > Clients.",
      create && (!platform || companyId) ? button("New job", () => newJobDialog({ companyId }), "primary") : null),
    platform ? companySelect : null,
    platform ? null : searchCard(),
    card("Jobs", h("div", { class: "toolbar" }, status), list),
  ].filter(Boolean));
  await draw();
}

const csv = (a) => (a || []).join(", ");

export async function jobPage(root, params) {
  if (can.platform()) { root.append(h("p", { class: "muted" }, "Rise staff can create requirements for a selected client company. Open the Client Requirements page to choose a company.")); return; }
  let job = await api.get("/jobs/" + params.ref);
  const writable = can.write();
  const head = h("div");
  const reqBox = h("div");
  const fileBox = h("div");
  const matchBox = h("div");

  const minScore = h("select", { "aria-label": "Minimum match" }, [["0", "Any match"], ["30", "At least 30%"], ["50", "At least 50%"], ["70", "At least 70%"]].map(([v, t]) => h("option", { value: v }, t)));
  const noFlags = h("input", { type: "checkbox" });
  const find = button("Find matches", null, "primary");
  find.onclick = guarded(find, async () => {
    clear(matchBox).append(h("p", { class: "muted" }, "Ranking candidates..."));
    const res = await api.get(`/jobs/${job.job_id}/matches` + qs({ min_score: minScore.value, exclude_flagged: noFlags.checked }));
    clear(matchBox).append(h("p", { class: "muted" }, `${res.total} of ${res.candidates_searched} candidates shown, best first.`), matchResults(res));
  })

  function drawRequirements() {
    const r = job.requirements;
    const inp = (key, value, props = {}) => { const el = h("input", { type: "text", value: value ?? "", dataset: { name: key }, disabled: !writable, ...props }); return el; };
    const area = (key, value) => h("textarea", { rows: 2, value: value ?? "", dataset: { name: key }, disabled: !writable });
    const f = {
      title: inp("title", job.title, { maxlength: 200, required: true }), client: inp("client", job.client, { maxlength: 200, required: true }),
      client_ref: inp("client_ref", job.client_ref, { maxlength: 100, required: true }), received: inp("received_on", job.received_on, { type: "date" }),
      primary: inp("primary_skill", r.primary_skill, { maxlength: 60, required: true }),
      must: area("must_have_skills", csv(r.must_have_skills)) , nice: area("nice_to_have_skills", csv(r.nice_to_have_skills)),
      min: inp("min_experience_years", r.min_experience_years, { type: "number", min: 0, step: "any", required: true }),
      max: inp("max_experience_years", r.max_experience_years, { type: "number", min: 0, step: "any", required: true }),
      loc: inp("locations", csv(r.locations), { required: true }), notice: inp("max_notice_days", r.max_notice_days, { type: "number", min: 0, required: true }),
      ctc: inp("max_ctc_lakhs", r.max_ctc_lakhs, { type: "number", min: 0, step: "any", required: true }),
      summary: area("summary", r.summary),
    };
    const save = button("Save requirements", null, "primary");
    const form = h("form", { class: "stack" },
      h("div", { class: "form-grid" },
        field("Role *", f.title), field("Client *", f.client),
        field("ATS Job ID", h("input", { type: "text", value: job.job_id, disabled: true })),
        field("Client-provided Job ID *", f.client_ref, { hint: "The job number or role ID given by the client." }), field("Request received on", f.received),
        h("div", { class: "span-2" }, field("Primary skill *", f.primary, { hint: "The main skill. It always counts as a must-have." })),
        h("div", { class: "span-2"}, field("Other must-have skills", f.must, { hint: "Separate with commas. A candidate missing one is shown as missing." })),
        h("div", { class: "span-2"}, field("Nice-to-have skills", f.nice, { hint: "Count for less than must-haves." })),
        field("Experience from (years) *", f.min), field("Experience up to (years) *", f.max),
        field("Locations *", f.loc, { hint: "Separate with commas." }), field("Needs to join within (days) *", f.notice, { hint: "How soon the candidate must be able to join." }),
        field("Budget (LPA) *", f.ctc, { hint: "Candidates expecting more are flagged." }),
        h("div", { class: "span-2" }, field("Summary", f.summary))),
      r.summary ? h("p", { class: "muted" }, r.summary) : null,
      writable && !can.platform() ? h("div", { class: "actions" },
        state.meta.ai_enabled && job.jd_text ? button("Re-read job description with AI", guardedReread, "") : null, save) : null);
    function guardedReread(e) {
      return guarded(e.currentTarget, async () => {
        const j = await api.patch("/jobs/" + job.job_id, { version: job.version, reextract: true });
        job = j;
        if (j.warning) toast(j.warning, "warn", 8000); else toast("Requirements updated fromt the job description.", "success");
        drawAll();
      })(e);
    }
    form.addEventListener("submit", guarded(save, async () => {
      try {
        job = await api.patch(`/jobs/` + job.job_id, {
          version: job.version, title: f.title.value, client: f.client.value, client_ref: f.client_ref.value, received_on: f.received.value,
          requirements: { primary_skill: f.primary.value, must_have_skills: f.must.value, nice_to_have_skills: f.nice.value, min_experience_years: f.min.value, max_experience_years: f.max.value,
            locations: f.loc.value, max_notice_days: f.notice.value, max_ctc_lakhs: f.ctc.value, summary: f.summary.value }
        });
        toast("Saved.", "success");
        drawAll();
      } catch (e) {
        if (e.status === 409) { job = e.current; toast("Someone else changed this job. The latest version is shown - review and save again.", "warn", 8000); drawAll(); return; }
        const orphans = applyErrors(form, e.errors);
        if (orphans.length || Object.keys(e.errors || {}).length) toast(orphans.join("; ") || errorMessage(e), "error");
      }
    }));
    clear(reqBox).append(card("Requirements", form, 
      job.jd_text ? h("details", null, h("summary", null, "Job description"), h("pre", { class: "jd" }, job.jd_text)) : null));
  }

  function drawFile() {
    const f = job.jd_file;
    const input = h("input", { type: "file", accept: JD_TYPES, hidden: true });
    input.addEventListener("change", async () => {
      const picked = input.files[0];
      input.value = "";
      if (!picked) return;
      if (picked.size > MAX_JD) { toast("The job description file must be smaller than 5 MB.", "error"); return; }
      try {
      const up = await api.upload(`/jobs/${job.job_id}/jd?filename=` + encodeURIComponent(picked.name), await picked.arrayBuffer());
        job = up;
        if (up.warning) toast(up.warning, "warn", 8000); else toast("Job description uploaded.", "success");
        drawAll();
      } catch (e) { toast(e.errors?.file || errorMessage(e), "error"); }
    });
    clear(fileBox).append(card("Job description file",
      f ? h("p", null, h("strong", null, f.filename), " ", h("small", { class: "muted" }, `${f.mime.includes("pdf") ? "PDF" : "Word"} . ${Math.max(1, Math.round(f.size / 1024))} KB`))
        : h("p", { class: "muted" }, "No file attached. You can upload the client's job description as a Word (.docx) or text-based PDF file."),
      h("div", { class: "card-actions"},
        f ? button("Download", () => api.download(`/jobs/${job.job_id}/jd`, f.filename).catch((e) => toast(errorMessage(e), "error"))) : null,
        writable ? h("span", null, button(f ? "Replace file" : "Upload file", () => input.click()), input) : null)));
  }

  function drawHead() {
    const toggle = job.status === "Open" ? "Close job" : "Reopen job";
      clear(head).append(pageHeader(`ATS Job ID ${job.job_id} · ${job.title}`, [job.client, job.client_ref ? "Client-provided Job ID " + job.client_ref : "", job.received_on ?  "Received " + job.received_on : ""].filter(Boolean).join(" · "), statusBadge(job.status),
      writable ? button(toggle, async () => {
        try { job = await api.patch("/jobs/" + job.job_id, { version: job.version, status: job.status === "Open" ? "Closed" : "Open" }); drawAll(); } catch (e) { toast(errorMessage(e), "error"); }
      }) : null,
      can.admin() ? button("Delete", async () => {
        if (!(await confirmBox("Delete job", `Delete ${job.job_id}? It disappears from the list; the record is kept for audit.`, "Delete", true))) return;
        try { await api.del("/jobs/" + job.job_id); toast("Job deleted.", "success"); go("/jobs"); } catch (e) { toast(errorMessage(e), "error"); }
      }, "danger") : null,
      button("All jobs", () => go("/jobs"))));
  }

  function drawAll() { drawHead(); drawRequirements(); drawFile(); }
  drawAll();
  root.append(head, reqBox, fileBox, card("Matching candidates",
    h("div", { class: "toolbar" }, minScore, h("label", { class: "inline" }, noFlags, "Hide candidates with Flags"), h("span", { class: "spacer" }), find), matchBox));
  find.click();
}
