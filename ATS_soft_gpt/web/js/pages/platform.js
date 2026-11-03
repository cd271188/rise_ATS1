import { api } from "../api.js";
import { h, clear, card, pageHeader, table, field, modal, button, applyErrors, toast, errorMessage, confirmBox, state, can } from "../ui.js";
import { go } from "../router.js";
import { showSecret } from "./team.js";
import { createVendorDialog } from "./vendors.js";

const PERMS = [
  ["create_companies", "Create client companies"],
  ["manage_companies", "Rename, suspend and reactivate companies"],
  ["manage_client_users", "Add client users, change roles, disable, reset passwords"],
  ["manage_compensation", "Build offer letter compensation structures and send them to companies"],
  ["manage_ai", "Turn AI features on or off for companies"],
  ["create_job_requirements", "Create client job requirements"],
  ["view_audit", "See the Rise activity log (who did what to which company)"],
];
const has = (p) => (state.user.platform_permissions || []).includes(p);
const statusBadge = (on, yes, no) => h("span", { class: "badge " + (on ? "s-active" : "s-inactive") }, on ? yes : no);

function failToForm(form, ex) {
  const orphans = applyErrors(form, ex.errors);
  if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
}

function permissionBoxes(selected) {
  const boxes = PERMS.map(([key, label]) => {
    const input = h("input", { type: "checkbox", dataset: { perm: key } });
    input.checked = selected.includes(key);
    return h("label", { class: "check" }, input, " " + label);
  });
  return { node: h("div", { class: "stack" }, h("strong", null, "What this Rise admin may do"), boxes, h("p", { class: "muted" }, "Every Rise admin can see the list of companies. Rise admins cannot create admins, or reset or disable owners and admins; only the creator can. Every action is recorded in the Rise activity log.")),
    value: () => boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.dataset.perm) };
}

function createCompanyDialog(onDone) {
  const company = h("input", { type: "text", dataset: { name: "company" } });
  const ownerName = h("input", { type: "text", dataset: { name: "owner_name" } });
  const ownerEmail = h("input", { type: "email", dataset: { name: "owner_email" } });
  const save = h("button", { class: "btn primary", type: "submit" }, "Create company");
  const form = h("form", { class: "stack", novalidate: true },
    field("Company name", company), field("Owner's name", ownerName), field("Owner's work email", ownerEmail),
    h("p", { class: "muted" }, "The owner gets a temporary password and then invites their own team."),
    h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
  const m = modal("New client company", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const c = await api.post("/platform/companies", { company: company.value, owner_name: ownerName.value, owner_email: ownerEmail.value });
      m.close();
      await onDone();
      showSecret("Company created", `Give ${c.owner_email} this temporary password to sign in to ${c.name}:`, c.temporary_password);
    } catch (ex) {
      failToForm(form, ex);
      save.disabled = false;
    }
  });
}

function renameDialog(c, onDone) {
  const name = h("input", { type: "text", value: c.name, dataset: { name: "name" } });
  const save = h("button", { class: "btn primary", type: "submit" }, "Save");
  const form = h("form", { class: "stack", novalidate: true }, field("Company name", name),
    h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
  const m = modal("Rename company", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      await api.patch("/platform/companies/" + c.id, { name: name.value });
      m.close();
      toast("Company renamed.", "success");
      await onDone();
    } catch (ex) {
      failToForm(form, ex);
      save.disabled = false;
    }
  });
}

function addClientUserDialog(c, onDone) {
  const full = h("input", { type: "text", dataset: { name: "full_name" } });
  const email = h("input", { type: "email", dataset: { name: "email" } });
  const role = h("select", { dataset: { name: "role" } }, (can.creator() ? ["admin", "recruiter", "viewer"] : ["recruiter", "viewer"].map((r) => h("option", { value: r }, r))));
  role.value = "recruiter";
  const save = h("button", { class: "btn primary", type: "submit" }, "Create user");
  const form = h("form", { class: "stack", novalidate: true }, field("Full name", full), field("Work email", email), field("Role", role),
    h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
  const m = modal("Add a user at " + c.name, form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const u = await api.post(`/platform/companies/${c.id}/users`, { full_name: full.value, email: email.value, role: role.value });
      m.close();
      await onDone();
      showSecret("User created", `Give ${u.email} this temporary password:`, u.temporary_password);
    } catch (ex) {
      failToForm(form, ex);
      save.disabled = false;
    }
  });
}

async function usersDialog(c, onChange) {
  const holder = h("div");
  const manage = has("manage_client_users");
  const m = modal("Users at " + c.name, h("div", { class: "stack" }, holder,
    h("div", { class: "actions" }, manage ? button("Add user", () => addClientUserDialog(c, draw)) : null, button("Close", () => { m.close(); onChange(); }, "primary"))), { wide: true });
  async function draw() {
    const users = await api.get(`/platform/companies/${c.id}/users`);
    const act = async (fn, okMsg) => { try { await fn(); toast(okMsg, "success"); } catch (e) { toast(errorMessage(e), "error"); } await draw(); };
    clear(holder).append(table(["Name", "Email", "Role", "Status", ""], users.map((u) => {
      const mayTouch = manage && (can.creator() || !["owner", "admin"].includes(u.role));
      let roleCell = u.role;
      if (mayTouch && u.role !== "owner") {
        const sel = h("select", { "aria-label": "Role for " + u.full_name }, (can.creator() ? ["admin", "recruiter", "viewer"] : ["recruiter", "viewer"]).map((r) => h("option", { value: r }, r)));
        sel.value = u.role;
        sel.addEventListener("change", () => act(() => api.patch(`/platform/companies/${c.id}/users/${u.id}`, { role: sel.value }), "Role updated."));
        roleCell = sel;
      }
      return h("tr", { class: u.is_active ? "" : "inactive" },
        h("td", null, u.full_name), h("td", null, u.email), h("td", null, roleCell), h("td", null, statusBadge(u.is_active, "Active", "Disabled")),
        h("td", { class: "row-actions" }, mayTouch ? [
          button(u.is_active ? "Disable" : "Enable", async () => {
            if (u.is_active && !(await confirmBox("Disable user", `${u.full_name} will be signed out and unable to sign in.`, "Disable", true))) return;
            act(() => api.patch(`/platform/companies/${c.id}/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? "User disabled." : "User enabled.");
          }),
          button("Reset password", async () => {
            if (!(await confirmBox("Reset password", `Create a new temporary password for ${u.full_name}? Their sessions end immediately.`, "Reset"))) return;
            try {
              const r = await api.post(`/platform/companies/${c.id}/users/${u.id}/reset-password`);
              showSecret("Password reset", `New temporary password for ${u.email}:`, r.temporary_password);
            } catch (e) { toast(errorMessage(e), "error"); }
          }),
        ] : null));
    })));
  }
  try { await draw(); } catch (e) { toast(errorMessage(e), "error"); }
}

export async function companiesPage(root) {
  const holder = h("div");
  const person = (u) => h("li", { class: u.is_active ? "" : "off" }, h("div", { class: "node" },
    u.full_name, h("small", null, `${u.email} · ${u.role}`), u.is_active ? null : statusBadge(false, "", "Disabled")));
  async function draw() {
    const list = await api.get("/platform/companies");
    const act = async (fn, okMsg) => { try { await fn(); toast(okMsg, "success"); } catch (e) { toast(errorMessage(e), "error"); } await draw(); };
    clear(holder).append(...(list.length ? list.map((c) => h("div", { class: "company-block" + (c.is_active ? "" : " inactive") },
      h("div", { class: "company-head" },
        h("div", null, h("strong", null, c.name), " ", statusBadge(c.is_active, "Active", "Suspended"), " ", statusBadge(c.ai_enabled, "AI on", "AI off"),
          h("div", { class: "muted" }, `${c.owner_name ? c.owner_name + " (" + c.owner_email + ") . " : ""}${c.users} users · created ${c.created_at}`)),
      h("div", { class: "row-actions" },
        has("manage_client_users") ? button("Manage users", () => usersDialog(c, draw)) : null,
        has("manage_compensation") ? button("Offer letter", () => go("/company/" + c.id + "/compensation")) : null,
        can.creator() ? button("Add vendor", () => createVendorDialog(draw, `/platform/companies/${c.id}/vendors`, c.name)) : null,
        has("manage_ai") ? button(c.ai_enabled ? "Turn AI off" : "Turn AI on", async () => {
          if (c.is_active && !(await confirmBox("Turn AI on", `${c.name}'s CV text and job descriptions will be sent to ${state.meta?.ai_where || "the AI service"}. Only do this with the company's agreement.`, "Turn on"))) return;
          act(() => api.patch("/platform/companies/" + c.id, { ai_enabled: !c.ai_enabled }), c.ai_enabled ? "AI turned off." : "AI turned on.");
        }) : null,
        has("manage_companies") ? button("Rename", () => renameDialog(c, draw)) : null,
        has("manage_companies") ? button(c.is_active ? "Suspend": "Reactivate", async () => {
          if (c.is_active && !(await confirmBox("Suspend company", `Everyone at ${c.name} (and its vendor) wil be signed out and unable to sign in until you reactivate it. Their data is kept.`, "Suspend", true))) return;
          act(() => api.patch("/platform/companies/" + c.id, { is_active: !c.is_active }), c.is_active ? "Company suspended." : "Company reactivated.");
        }) : null)),
      h("ul", { class: "tree" },
        c.people.map(person),
        c.vendors.map((v) => h("li", { class: v.is_active ? "" : "off" },
          h("div", { class: "node org" }, v.name, h("small", null, "vendor"), v.is_active ? null : statusBadge(false, "", "Suspended")),
          h("ul", null, v.people.map(person))))))) : [h("p", { class: "muted" }, "No companies yet.")]));
  }
  root.append(
    pageHeader("Client companies", "Each company with its people, and the vendors it works with and their people. Their candidate data is not visible here.",
      has("create_companies") ? button("New company", () => createCompanyDialog(draw), "primary") : null),
    card(null, holder));
  await draw();
}

const ACTION_LABELS = {
  "company.create": "Created company", "company.update" : "Changed company", "vendor.create": "Added vendor",
  "company.user_create": "Added user", "company.user_update": "Changed user", "company.reset_password": "Reset password",
  "company.admin_account_change": "Changed an owner/admin account", "platform.view_users": "Viewed users",
  "platform.view_compensation": "Viewed offer structure", "platform.download_template": "Download offer template",
};

export async function activityPage(root) {
  const PAGE = 100;
  const holder = h("div");
  const filter = h("select", { "aria-label": "Company" }, h("option", { value: "" }, "All companies"));
  const more = h("div", { class: "actions" });
  let offset = 0;
  let body = null;

  async function load(reset) {
    if (reset) { offset = 0; body = null; clear(holder); }
    const q = new URLSearchParams({ limit: PAGE, offset });
    if (filter.value) q.set("company_id", filter.value);
    const r = await api.get(`/platform/audit?` + q);
    const rows = r.items.map((i) => {
      const { company, company_id, by, ...rest } = i.diff || {};
      const detail = Object.entries(rest).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join("->") : v}`).join("; ");
      return h("tr", null, h("td", null, i.at), h("td", null, i.user ? `${i.user} (${i.email})` : "-"),
        h("td", null, ACTION_LABELS[i.action] || i.action), h("td", null, i.company || "-"), h("td", { class: "wrap" }, detail), h("td", null, i.ip || ""));
    });
    if (!body) {
      body = h("tbody");
      holder.append(h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", null, h("tr", null, h("tr", null, ["When", "Who", "What", "Company", "Details", "From"].map((t) => h("th", null, t))))), body)));
    }
    body.append(...rows);
    offset += r.items.length;
    clear(more);
    if (offset < r.total) more.append(button("Load more", () => load(false)));
    if (!r.total) holder.append(h("p", { class: "muted" }, "Nothing recorded yet."));
  }

  filter.addEventListener("change", () => load(true).catch((e) => toast(errormessage(e), "error")));
  root.append(pageHeader("Rise activity", "Everything Rise staff did to client companies, by name. Clients see only that Rise Consulting acted, not who"),
    card(null, h("div", { class: "stack" }, field("Company", filter), holder, more)));
  try {
    for (const c of await api.get("/platform/companies")) filter.append(h("option", { value: c.id }, c.name));
    await load(true);
  } catch (e) { toast(errorMessage(e), "error"); }
}

export async function staffPage(root) {
  const holder = h("div");
  const label = (p) => (PERMS.find(([k]) => k === p) || [p, p])[1];

  function accessDialog(u) {
    const boxes = permissionBoxes(u.permissions);
    const save = h("button", { class: "btn primary", type: "submit" }, "Save access");
    const form = h("form", { class: "stack", novalidate: true }, boxes.node, h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
    const m = modal("Access for " + u.full_name, form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await api.patch("/platform/staff/" + u.id, { permissions: boxes.value() });
        m.close();
        toast("Access updated.", "success");
        await draw();
      } catch (ex) { failToForm(form, ex); save.disabled = false; }
    });
  }

  async function draw() {
    const staff = await api.get("/platform/staff");
    const act = async (fn, okMsg) => { try { await fn(); toast(okMsg, "success"); } catch (e) { toast(errorMessage(e), "error"); } await draw(); };
    clear(holder).append(table(["Name", "Email", "Role", "Can do", "Status", "Last sign-in", ""], staff.map((u) => {
      const manage = u.platform_role !== "creator" && u.id !== state.user.id;
      return h("tr", { class: u.is_active ? "" : "inactive" },
        h("td", null, u.full_name), h("td", null, u.email), h("td", null, u.platform_role === "creator" ? "Creator" : "Rise admin"),
        h("td", { class: "wrap" }, u.platform_role === "creator" ? "Everything" : u.permissions.length ? u.permissions.map(label).join("; ") : "View companies only"),
        h("td", null, statusBadge(u.is_active, "Active", "Disabled")),
        h("td", null, u.last_login_at || "never"),
        h("td", { class: "row-actions" }, manage ? [
          button("Edit access", () => accessDialog(u)),
          button(u.is_active ? "Disable" : "Enable", async () => {
            if (u.is_active && !(await confirmBox("Disable account", `${u.full_name} will be signed out and unable to sign in.`, "Disable", true))) return;
            act(() => api.patch("/platform/staff/" + u.id, { is_active: !u.is_active }), u.is_active ? "Account disabled." : "Account enabled.");
          }),
          button("Reset password", async () => {
            if (!(await confirmBox("Reset password", `Create a new temporary password for ${u.full_name}?`, "Reset"))) return;
            try { const r = await api.post(`/platform/staff/${u.id}/reset-password`); showSecret("Password reset", `New temporary password for ${u.email}:`, r.temporary_password); } catch (e) { toast(errorMessage(e), "error"); }
          }),
        ] : null));
    })));
  }

  function inviteDialog() {
    const full = h("input", { type: "text", dataset: { name: "full_name" } });
    const email = h("input", { type: "email", dataset: { name: "email" } });
    const boxes = permissionBoxes([]);
    const save = h("button", { class: "btn primary", type: "submit" }, "Create account");
    const form = h("form", { class: "stack", novalidate: true }, field("Full name", full), field("Work email", email), boxes.node,
      h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
    const m = modal("Add a Rise admin", form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        const u = await api.post("/platform/staff", { full_name: full.value, email: email.value, permissions: boxes.value() });
        m.close();
        await draw();
        showSecret("Account created", `Give ${u.email} this temporary password:`, u.temporary_password);
      } catch (ex) { failToForm(form, ex); save.disabled = false; }
    });
  }

  root.append(pageHeader("Rise team", "People at Rise Consulting. You decide what each Rise admin is allowed to do.", can.creator() ? button("Add Rise admin", inviteDialog, "primary") : null),
    card(null, holder));
  await draw();
}
