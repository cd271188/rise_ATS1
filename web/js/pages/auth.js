import { api } from "../api.js";
import { h, clear, errorMessage, field , passwordInput, applyErrors } from "../ui.js";

// Shown instead of the app when the sccount still has a temporary password: nothing else works until it is replaced.
export function forcePasswordScreen(root, user, onDone, onCancel) {
  const current = passwordInput({ autocomplete: "current-password", dataset: { name: "current_password"} });
  const fresh = passwordInput({ autocomplete: "new-password", dataset: { name: "new-password"} });
  const err = h("div", { class: "form-error", role: "alert", hidden: true });
  const submit = h("button", { class: "btn primary block", type: "submit" }, "Set new password");
  const form = h("form", { class: "auth-form", novalidate: true },
    field("Temparary password", current.el),
    field("New password", fresh.el, { hint: "At least 10 characters, and different from the temporary one."}),
    err, submit);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    submit.disabled = true;
    try {
      await api.post("/auth/password", { current_password: current.input.value, new_password: fresh.input.value });
      await onDone(await api.login(user.email, fresh.input.value));
    } catch (ex) {
      const orphans = applyErrors(form, ex.errors);
      if (orphans.length || !Object.keys(ex.errors || {}).length) { err.textContent = orphans.join("; ") || errorMessage(ex); err.hidden = false; }
      submit.disabled = false;
    }
  });
  clear(root).append(h("div", { class: "auth-page" },
    h("div", { class: "auth-card" },
      h("div", { class: "brand big" }, h("span", { class: "logo" }, "A"), "ATS PLATFORM"),
      h("h1", null, "Choose a new password"),
      h("p", { class: "muted center" }, 'You signed in with a one-time temporary password (${user.email}). Set your own password to continue.'),
      form,
      h("p", { class: "muted center" }, h("a", { href: "#", onClick: (e) => { e.preventDefault(); onCancel(); } }, "Sign out"))),
    h("p", { class: "powered" }, "A product of ", h("strong", null, "Rise Consulting"))));
  current.input.focus(); 
}

export async function loginScreen(root, onSignedIn) {
  let cfg = { signup_open: true, first_run: false };
  try { cfg = await fetch("/api/v1/auth/config").then((r) => r.json()); } catch {/* offline: show login only */}
  let mode = cfg.first_run ? "signup" : "login";

  const render = () => {
    const err = h("div", { class: "form-error", role: "alert", hidden: true });
    const pw = passwordInput({ autocomplete: mode === "login" ? "current-password" : "new-password", required: true});
    const inputs = {
      company: h("input", { type: "text", autocomplete: "organization", required: true }),
      full_name: h("input", { type: "text", autocomplete: "name", required: true }),
      email: h("input", { type: "email", autocomplete: "username", required: true }),
      password: pw.input,
    };
    const submit = h("button", { class: "btn primary block", type: "submit" }, mode === "login" ? "Sign in" : "Create company account");
    const form = h("form", { class: "auth-form", novalidate: true },
      mode === "signup" ? field("Company name", inputs.company) : null,
      mode === "signup" ? field("Your name", inputs.full_name) : null,
      field("Work email", inputs.email),
      field("Password", pw.el, { hint: mode === "signup" ? "At least 10 characters." : null }),
      err, submit);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.hidden = true;
      submit.disabled = true;
      try {
        const user = mode === "login"
          ? await api.login(inputs.email.value, inputs.password.value)
          : await api.signup({ company: inputs.company.value, full_name: inputs.full_name.value, email: inputs.email.value, password: inputs.password.value });
        await onSignedIn(user);
      } catch (ex) {
        err.textContent = errorMessage(ex);
        err.hidden = false;
        submit.disabled = false;
      }
    });
    const toggle = cfg.signup_open
      ? h("p", { class: "muted center" }, mode === "login" ? "New company? " : "Already have an account? ",
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); mode = mode === "login" ? "signup" : "login"; render(); } },
          mode === "login" ? "Create an account" : "Sign in"))
      : h("p", { class: "muted center" }, "Need access? Ask your company administrator, or contact Rise Consulting.");
    clear(root).append(h("div", { class: "auth-page" },
      h("div", { class: "auth-card" },
        h("div", { class: "brand big" }, h("span", { class: "logo" }, "A"), "ATS Platform"),
        h("h1", null, cfg.first_run ? "Set up your company" : mode === "login" ? "Welcome back" : "Create your account"),
        h("p", { class: "muted center" }, cfg.first_run ? "The first account becomes the owner." : "Track candidates, interviews and submissions in one place."),
        form, toggle),
      h("p", { class: "powered" }, "A product of ", h("strong", null, "Rise Consulting"))));
    inputs[mode === "login" ? "email" : "company"].focus();
  };
  render();
}