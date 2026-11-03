import { api, refreshSession, setExpiredHandler } from "./api.js";
import { h, clear, can, state, toast, errorMessage, button } from "./ui.js";
import { go, match, parseHash } from "./router.js";
import { loginScreen, forcePasswordScreen } from "./pages/auth.js";
import { dashboardPage } from "./pages/dashboard.js";
import { candidateFormPage } from "./pages/candidate_form.js";
import { candidatesPage } from "./pages/candidates.js";
import { interviewsPage } from "./pages/interviews.js";
import { reportsPage } from "./pages/reports.js";
import { settingsPage, accountPage } from "./pages/settings.js";
import { teamPage, auditPage } from "./pages/team.js";
import { companiesPage, staffPage, activityPage } from "./pages/platform.js";
import { vendorsPage } from "./pages/vendors.js";
import { offerPage } from "./pages/offer.js";
import { compensationPage } from "./pages/compensation.js";
import { jobsPage, jobPage } from "./pages/jobs.js";

const app = document.getElementById("app");

const ROUTES = [
  { path: "/platform", title: "Client Companies", nav: "Companies", icon: "🏢", platform: true, render: companiesPage },
  { path: "/platform/jobs", title: "Client Requirements", nav: "Client Requirements", icon: "📋", platform: true, platformJobs: true, render: jobsPage },
  { path: "/rise-team", title: "Rise team", nav: "Rise team", icon: "🛡️", platform: true, creator: true, render: staffPage },
  { path: "/rise-activity", title: "Rise activity", nav: "Rise activity", icon: "", platform: true, perm: "view_audit", render: activityPage },
  { path: "/company/:id/compensation", title: "Offer letter set-up", platform: true, render: compensationPage },
  { path: "/dashboard", title: "Dashboard", nav: "Dashboard", icon: "📊", render: dashboardPage },
  { path: "/candidate/new", title: "Add candidate", nav: "Add Candidate", icon: "➕", write: true, render: candidateFormPage },
  { path: "/candidate/:ref", title: "Candidate", render: candidateFormPage },
  { path: "/candidates", title: "Candidates", nav: "Candidates", icon: "≡", render: candidatesPage },
  { path: "/jobs", title: "Client Requirements", nav: "Client Requirements", icon: "📋", render: jobsPage },
  { path: "/jobs/:ref", title: "Job", render: jobPage },
  { path: "/interviews", title: "Interviews", nav: "Interviews", icon: "📅", render: interviewsPage },
  { path: "/reports", title: "Reports", nav: "Reports", icon: "目", render: reportsPage },
  { path: "/settings", title: "Settings", nav: "Settings", icon: "⚙️", admin: true, render: settingsPage },
  { path: "/vendors", title: "Vendors", nav: "Vendors", icon: "🏭", admin: true, client: true, render: vendorsPage },
  { path: "/offer", title: "Offer letter", nav: "Offer letter", icon: "", admin: true, client: true, render: offerPage },
  { path: "/team", title: "Team", nav: "Team", icon: "👥", admin: true, render: teamPage },
  { path: "/audit", title: "Audit log", nav: "Audit", icon: "✎", admin: true, render: auditPage },
  { path: "/account", title: "My account", render: accountPage },
];

let cleanup = null;
let content = null;
let navLinks = [];

async function loadMeta() {
  state.meta = await api.get("/meta");
}

const home = () => (can.platform() ? "/platform" : "/dashboard");

function allowed(route) {
  if (can.platform()) { 
  if (!route.platform) return route.path === "/account";
  if (route.platformJobs) return can.creator() || (state.user.platform_permissions || []).includes("create_job_requirements");
  if (route.prem) return can.create() || (state.user.platform_permissions || []).includes(route.perm);
  return !route.creator || can.creator();
}
if (route.platform) return false;
if (can.vendor() && (route.client || route.path === "/settings")) return false;
return (!route.admin || can.admin()) && (!route.write || can.write());
}

let navId = 0;

async function show() {
  if (!state.user) return;
  const mine = ++navId;
  const { path, query } = parseHash();
  const found = match(ROUTES, path);
  if (cleanup) { try { cleanup(); } catch {/* page teardown must never block navigation */ } cleanup = null; }
  clear(content);
  if (!found || !allowed(found.route)) { go(home()); return; }
  navLinks.forEach((a) => a.classList.toggle("active", a.dataset.path === found.route.path || (found.route.path === "/candidate/:ref" && a.dataset.path === "/candidates") || (found.route.path === "/jobs/:ref" && a.dataset.path === "/jobs")));
  document.title = found.route.title + " - ATS Platform - Rise Consulting";
  document.getElementById("page-title").textContent = found.route.title;
  // Each navigation renders into its own holder, so a slower earlier render that finishes late cannot add a second copy of a page.
  const holder = h("div", { class: "page" });
  content.append(holder);
  try {
    const result = (await found.route.render(holder, { ...found.params, ...query, reloadMeta: loadMeta })) || null;
    if (mine !== navId) { try { result?.(); } catch {/* stale page teardown */ } return; }
    cleanup = result;
  } catch (e) {
    if (mine !== navId) return;
    holder.append(h("div", { class: "card error-card" }, h("h3", null, "Could not load this page"), h("p", null, errorMessage(e)), button("Retry", show)));
  }
}

function shell() {
  const user = state.user;
  const items = ROUTES.filter((r) => r.nav && allowed(r));
  navLinks = items.map((r) => h("a", { href: "#" + r.path, class: "nav-link", dataset: { path: r.path } }, h("span", { class: "nav-icon" }, r.icon), r.nav));
  const search = h("input", { type: "search", placeholder: "Search candidates...", "aria-label": "Search candidates" });
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && search.value.trim()) { go("/candidates?q=" + encodeURIComponent(search.value.trim())); search.value = ""; }
  });
  content = h("main", { class: "content" });
  clear(app).append(h("div", { class: "shell" },
    h("aside", { class: "sidebar" },
      h("div", { class: "brand" }, h("span", { class: "logo" }, "A"), "ATS Platform"),
      h("nav", null, navLinks),
      h("div", { class: "sidebar-foot muted" }, user.org.name, user.org.is_vendor ? h("small", null, "Vendor of " + user.org.client_name) : null, h("small", { class: "powered" }, "ATS Platform by Rise Consulting"))),
    h("div", { class: "main" },
      h("header", { class: "topbar" },
        h("h2", { id: "page-title" }),
        h("div", { class: "topbar-right" }, can.platform() ? null : search,
          h("a", { href: "#/account", class: "user-chip" }, h("span", { class: "avatar" }, user.full_name[0].toUpperCase()), h("span", null, user.full_name, h("small", null, user.platform_role === "creator" ? "creator" : user.platform_role === "rise_admin" ? " Rise admin" : user.role))),
          button("Sign out", signOut))),
      content)));
}

async function signOut() {
  await api.logout().catch(() => {});
  state.user = state.meta = null;
  showLogin();
}

function showLogin() {
  history.replaceState(null, "", location.pathname);
  loginScreen(app, async (user) => { await start(user); });
}

async function start(user) {
  if (user.must_change_password) {
    state.user = null;
    forcePasswordScreen(app, user, start, signOut);
    return;
  }
  state.user = user;
  state.meta = null;
  try {
    await loadMeta();
  } catch (e) {
    clear(app).append(h("div", { class: "auth-page" }, h("section", { class: "card error-card" },
      h("h3", null, "Could not load app setup"), h("p", null, errorMessage(e)),
      button("Retry", () => start(user), "primary"))));
    return;
  }
  shell();
  if (!location.hash) location.hash = home();
  show();
}

window.addEventListener("hashchange", show);
setExpiredHandler(() => { if (state.user) { state.user = null; showLogin(); toast("Your session expired. Please sign in again.", "info"); } });

(async () => {
  const user = await refreshSession();
  if (user) await start(user);
  else showLogin();
})();
