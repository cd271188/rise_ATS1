import { api, qs } from "../api.js";
import { h, clear, card, pageHeader, table, field, modal, button, applyErrors, toast, errorMessage, confirmBox, state, can } from "../ui.js";

const ROLE_HELP = {
  admin: "Admin: everything except owner-level changes.",
  recruiter: "Recruiter: add and edit candidates and interviews.",
  viewer: "Viewer: read-only access.",
};

export function showSecret(title, intro, secret) {
  const box = h("code", { class: "secret" }, secret);
  const copy = button("Copy", async () => {
    try { await navigator.clipboard.writeText(secret); toast("Copied.", "success"); } catch { toast("Select the text and copy it manually.", "info"); }
  });
  const m = modal(title, h("div", { class: "stack" },
    h("p", null, intro), box,
    h("p", { class: "muted" }, "This is shown only once. Ask the person to change it from My account after signing in."),
    h("div", { class: "actions" }, copy, button("Done", () => m.close(), "primary"))));
}

function inviteDialog(onDone) {
  const full = h("input", { type: "text", dataset: { name: "full_name" } });
  const email = h("input", { type: "email", dataset: { name: "email" } });
  const roles = state.user.role === "owner" ? ["recruiter", "viewer", "admin"] : ["recruiter", "viewer"];
  const role = h("select", { dataset: { name: "role" } }, roles.map((r) => h("option", { value: r }, r)));
  const help = h("p", { class: "muted" }, ROLE_HELP.recruiter);
  role.addEventListener("change", () => { help.textContent = ROLE_HELP[role.value]; });
  const save = h("button", { class: "btn primary", type: "submit" }, "Create user");
  const form = h("form", { class: "stack", novalidate: true },
    field("Full name", full), field("Work email", email), field("Role", role), help,
    h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
  const m = modal("Invite a team member", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const u = await api.post("/admin/users", { full_name: full.value, email: email.value, role: role.value });
      m.close();
      await onDone();
      showSecret("User created", `Give ${u.email} this temporary password:`, u.temporary_password);
    } catch (ex) {
      const orphans = applyErrors(form, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
      save.disabled = false;
    }
  });
}

export async function teamPage(root) {
  const holder = h("div");
  const me = state.user;

  async function draw() {
    const users = await api.get("/admin/users");
    const canManage = (u) => u.id !== me.id && u.role !== "owner" && (me.role === "owner" || u.role !== "admin");
    const roles = me.role === "owner" ? ["admin", "recruiter", "viewer"] : ["recruiter", "viewer"];
    clear(holder).append(table(["Name", "Email", "Role", "Status", "Last sign-in", ""], users.map((u) => {
      const act = async (fn, okMsg) => { try { await fn(); toast(okMsg, "success"); } catch (e) { toast(errorMessage(e), "error"); } await draw(); };
      let roleCell = u.role;
      if (canManage(u)) {
        const sel = h("select", { "aria-label": "Role for " + u.full_name }, roles.map((r) => h("option", { value: r }, r)));
        sel.value = u.role;
        sel.addEventListener("change", () => act(() => api.patch(`/admin/users/${u.id}`, { role: sel.value }), "Role updated."));
        roleCell = sel;
      }
      return h("tr", { class: u.is_active ? "" : "inactive" },
        h("td", null, u.full_name), h("td", null, u.email), h("td", null, roleCell),
        h("td", null, h("span", { class: "badge" + (u.is_active ? "s-active" : "s-inactive") }, u.is_active ? "Active" : "Disabled")),
        h("td", null, u.last_login_at || "never"),
        h("td", { class: "row-actions" }, canManage(u) ? [
          button(u.is_active ? "Disable" : "Enable", async () => {
            if (u.is_active && !(await confirmBox("Disable user", `${u.full_name} will be signed out and unable to sign in.`, "Disable", true))) return;
            act(() => api.patch(`/admin/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? "User disabled." : "User enabled.");
          }),
          button("Reset password", async () => {
            if (!(await confirmBox("Reset password", `Create a new temporary password for ${u.full_name}? Their sessions end immediately.`, "Reset"))) return;
            try { const r = await api.post(`/admin/users/${u.id}/reset-password`); showSecret("Password reset", `New temporary password for ${u.email}:`, r.temporary_password); } catch (e) { toast(errorMessage(e), "error"); }
          }),
        ] : null));
    })));
  }

  root.append(
    pageHeader("Team", "Who can sign in to " + me.org.name, can.admin() ? button("Invite user", () => inviteDialog(draw), "primary") : null),
    card(null, holder));
  await draw();
}

export async function auditPage(root) {
  const limit = 100;
  let offset = 0;
  const holder = h("div");
  const info = h("span", { class: "muted" });
  const prev = button("< Newer", () => { offset = Math.max(0, offset - limit); draw(); });
  const next = button("Older >", () => { offset += limit; draw(); });

  const detail = (d) => (d == null ? "" : typeof d === "string" ? d : JSON.stringify(d));

  async function draw() {
    const res = await api.get("/admin/audit" + qs({ limit, offset }));
    clear(holder).append(table(["When", "User", "Action", "Record", "Details", "IP"], res.items.map((a) => h("tr", null,
      h("td", { class: "nowrap" }, a.at), h("td", null, a.user || ""), h("td", null, a.action),
      h("td", null, [a.entity, a.entity_id].filter((x) => x != null && x !== "").join(" ")), h("td", { class: "wrap mono" }, detail(a.diff)), h("td", null, a.ip || "" )))));
    info.textContent = res.total ? `${offset + 1}-${offset + res.items.length} of ${res.total}` : "No activity yet";
    prev.disabled = offset === 0;
    next.disabled = offset + limit >= res.total;
  }

  root.append(pageHeader("Audit log", "Who did what, newest first. Entries cannot be edited."),
    card(null, holder, h("div", { class: "toolbar" }, info, h("span", { class: "spacer" }), prev, next)));
  await draw();
}