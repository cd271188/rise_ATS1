import { api } from "../api.js";
import { h, card, pageHeader, field, button, applyErrors, toast, errorMessage, state, statusBadge, passwordInput } from "../ui.js";

const EDITABLE_LISTS = [
  ["recruiters", "Recruiters", "One name per line. Shown in the Recruiter dropdown."],
  ["clients", "Clients", "One client company per line. Used by candidate forms and suggested when adding job requirements."],
  ["notice_period", "Notice periods", "One option per line."],
  ["yes_no", "Yes / No options", "Used by the Yes/No fields."],
];

const lines = (v) => v.split("\n").map((x) => x.trim()).filter(Boolean);

export async function settingsPage(root, params) {
  const lists = await api.get("/lists");
  const org = state.user.org;

  const areas = Object.fromEntries(EDITABLE_LISTS.map(([key]) => [key, h("textarea", { rows: 9, dataset: { name: key }, value: (lists[key] || []).join("\n") })]));
  const saveLists = h("button", { class: "btn primary", type: "submit" }, "Save lists");
  const listForm = h("form", { class: "stack", novalidate: true },
    h("div", { class: "grid-2" }, EDITABLE_LISTS.map(([key, title, hint]) => field(title, areas[key], { hint }))),
    h("div", { class: "actions" }, saveLists));
  listForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    saveLists.disabled = true;
    try {
      const body = Object.fromEntries(Object.entries(areas).map(([k, el]) => [k, lines(el.value)]));
      const saved = await api.put("/lists", body);
      for (const [k, el] of Object.entries(areas)) el.value = (saved[k] || []).join("\n");
      applyErrors(listForm, {});
      await params.reloadMeta?.();
      toast("Lists saved.", "success");
    } catch (ex) {
      const orphans = applyErrors(listForm, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
    }
    saveLists.disabled = false;
  });

  const name = h("input", { type: "text", maxLength: 120, dataset: { name: "name" }, value: org.name });
  const tz = h("input", { type: "text", dataset: { name: "timezone" }, value: org.timezone || "UTC", placeholder: "e.g. Asia/Kolkata" });
  const teamEdit = h("input", { type: "checkbox", checked: Boolean(org.team_edit) });
  const saveOrg = h("button", { class: "btn primary", type: "submit" }, "Save company settings");
  const orgForm = h("form", { class: "stack", novalidate: true },
    h("div", { class: "form-grid" },
      field("Company name", name),
      field("Time zone", tz, { hint: "Decides what counts as 'today' on the dashboard and in follow-ups." }),
      h("label", { class: "check span-2" }, teamEdit, h("span", null, "Recruiters may edit candidates added by other recruiters"))),
    h("div", { class: "actions" }, saveOrg));
  orgForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    saveOrg.disabled = true;
    try {
      state.user.org = await api.patch("/admin/org", { name: name.value, timezone: tz.value, team_edit: teamEdit.checked });
      applyErrors(orgForm, {});
      toast("Company settings saved.", "success");
    } catch (ex) {
      const orphans = applyErrors(orgForm, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
    }
    saveOrg.disabled = false;
  });

  root.append(
    pageHeader("Settings", "Dropdown lists and company preferences. Administrators only."),
    card("Company", orgForm),
    card("Dropdown lists", listForm),
    card("Statuses", h("p", { class: "muted" }, "The nine statuses are fixed because reports depend on them. The latest interview entry sets a candidate's status."),
      h("div", { class: "badge-row" }, (lists.status || []).map((s) => statusBadge(s)))));
}

export async function accountPage(root) {
  const u = state.user;
  const cur = passwordInput({ autocomplete: "current-password", dataset: { name: "current_password" } });
  const neu = passwordInput({ autocomplete: "new-password", dataset: { name: "new_password" } });
  const save = h("button", { class: "btn primary", type: "submit" }, "Change password");
  const form = h("form", { class: "stack narrow", novalidate: true },
    field("Current password", cur.el), field("New password", neu.el, { hint: "At least 10 characters." }), h("div", { class: "actions" }, save));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      await api.post("/auth/password", { current_password: current.value, new_password: fresh.value });
      await api.login(u.email, fresh.value);
      current.value = fresh.value = "";
      applyErrors(form, {});
      toast("Password changed.", "success");
    } catch (ex) {
      const orphans = applyErrors(form, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
    }
    save.disabled = false;
  });
  root.append(
    pageHeader("My account", u.email),
    card("Profile", h("dl", { class: "facts" },
      h("dt", null, "Name"), h("dd", null, u.full_name), h("dt", null, "Email"), h("dd", null, u.email),
      h("dt", null, "Role"), h("dd", null, u.platform_role === "creator" ? "Creator" : u.platform_role ? "Rise admin" : u.role), h("dt", null, "company"), h("dd", null, u.org.name))),
    card("Change password", form));
}
