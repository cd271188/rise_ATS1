// Hash router: "#/candidate/CND-0001?x=1" -> route "/candidate/:ref" with params {ref, x}.
export function parseHash() {
  const raw = location.hash.slice(1) || "/dashboard";
  const [path, query] = raw.split("?");
  return { path, query: Object.fromEntries(new URLSearchParams(query || "")) };
}

export function match(routes, path) {
  const parts = path.split("/").filter(Boolean);
  for (const r of routes) {
    const pat = r.path.split("/").filter(Boolean);
    if (pat.length !== parts.length) continue;
    const params = {};
    if (pat.every((p, i) => (p.startsWith(":") ? ((params[p.slice(1)] = decodeURIComponent(parts[i])), true) : p === parts[i]))) {
      return { route: r, params };
    }
  }
  return null;
}

export const go = (path) => { location.hash = path; };