import { api } from "../api.js";
import { h, clear, card, pageHeader, table, field, modal, button, applyErrors, toast, errorMessage, confirmBox } from "../ui.js";
import { showSecret } from "./team.js";

const statusBadge = (on, yes, no) => h("span", { class: "badge " + (on ? "s-active" : "s-inactive") }, on ? yes : no);

function failToForm(form, ex) {
  const orphans = applyErrors(form, ex.errors);
  if (orphans.length || !Object.keys(ex.errors || {}).length) toast(orphans.join("; ") || errorMessage(ex), "error");
}

export function createVendorDialog(onDone) {
  const company = h("input", { type: "text", dataset: { name: "company" } });
  const ownerName = h("input", { type: "text", dataset: { name: "owner_name" } });
  const ownerEmail = h("input", { type: "email", dataset: { name: "owner_email" } });
  const save = h("button", { class: "btn primary", type: "submit" }, "Add vendor");
  const form = h("form", { class: "stack", novalidate: true },
    field("Vendor company name", company), field("Vendor owner's name", ownerName), field("Vendor owner's work email", ownerEmail),
    h("p", { class: "muted" }, "The owner gets a temporary password and then adds their own recruiters. Their candidates join your pipeline; they only see the candidates they submitted."),
    h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
  const m = modal("Add a vendor", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const v = await api.post("/vendors", { company: company.value, owner_name: ownerName.value, owner_email: ownerEmail.value });
      m.close();
      await onDone();
      showSecret("Vendor added", `Give ${v.owner_email} this temporary password to sign in for ${v.name}:`, v.temporary_password);
    } catch (ex) {
      failToForm(form, ex);
      save.disabled = false;
    }
  });
}

function renameDialog(v, onDone) {
  const name = h("input", { type: "text", value: v.name, dataset: { name: "name" } });
  const save = h("button", { class: "btn primary", type: "submit" }, "Save");
  const form = h("form", { class: "stack", novalidate: true }, field("Vendor name", name),
    h("div", { class: "actions" }, button("Cancel", () => m.close()), save));
  const m = modal("Rename vendor", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      await api.patch("/vendors/" + v.id, { name: name.value });
      m.close();
      toast("Vendor renamed.", "success");
      await onDone();
    } catch (ex) {
      failToForm(form, ex);
      save.disabled = false;
    }
  });
}

async function usersDialog(v) {
  const holder = h("div");
  const m = modal("People at " + v.name, h("div", { class: "stack" }, holder,
    h("p", { class: "muted" }, "The vendor's owner adds and removes recruiters from their own Team page. Use this only to hand out a new temporary password."),
    h("div", { class: "actions" }, button("Close", () => m.close(), "primary"))), { wide: true });
  try {
    const users = await api.get(`/vendors/${v.id}/users`);
    clear(holder).append(table(["Name", "Email", "Role", "Status", ""], users.map((u) => h("tr", { class: u.is_active ? "" : "inactive" },
      h("td", null, u.full_name), h("td", null, u.email), h("td", null, u.role), h("td", null, statusBadge(u.is_active, "Active", "Disabled")),
      h("td", { class: "row-actions" }, button("Reset password", async () => {
        if (!(await confirmBox("Reset password", `Create a new temporary password for ${u.full_name}? Their sessions end immediately.`, "Reset"))) return;
        try {
          const r = await api.post(`/vendors/${v.id}/users/${u.id}/reset-password`);
          showSecret("Password reset", `New temporary password for ${u.email}:`, r.temporary_password);
        } catch (e) { toast(errorMessage(e), "error"); }
      }))))));
  } catch (e) { toast(errorMessage(e), "error"); }
}

export async function vendorsPage(root) {
  const holder = h("div");
  async function draw() {
    const list = await api.get("/vendors");
    const act = async (fn, okMsg) => { try { await fn(); toast(okMsg, "success"); } catch (e) { toast(errorMessage(e), "error"); } await draw(); };
    clear(holder).append(list.length ? table(["Vendor", "Owner", "Users", "Candidates", "Added", "Status", ""], list.map((v) => h("tr", { class: v.is_active ? "" : "inactive" },
      h("td", null, v.name),
      h("td", null, v.owner_name ? `${v.owner_name} (${v.owner_email})` : ""),
      h("td", null, String(v.users)), h("td", null, String(v.candidates)), h("td", null, v.created_at),
      h("td", null, statusBadge(v.is_active, "Active", "Suspended")),
      h("td", { class: "row-actions" },
        button("People", () => usersDialog(v)),
        button("Rename", () => renameDialog(v, draw)),
        button(v.is_active ? "Suspend" : "Reactivate", async () => {
          if (v.is_active && !(await confirmBox("Suspend vendor", `Everyone at ${v.name} will be signed out and unable to sign in until you reactivate it. Their candidates stay in your pipeline.`, "Suspend"))) return;
          act(() => api.patch("/vendors/" + v.id, { is_active: !v.is_active }), v.is_active ? "Vendor suspended." : "Vendor reactivated.");
        }))))) : h("p", { class: "muted" }, "No vendors yet. Add one to let another company submit candidates into your pipeline."));
  }
  root.append(
    pageHeader("Vendors", "Companies you hire to source candidates. Their submissions appear in your pipeline tagged with the vendor's name.",
      button("Add vendor", () => createDialog(draw), "primary")),
    card(null, holder));
  await draw();
}