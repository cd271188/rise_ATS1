"""Hybrid candidate/requirement scoring. Pure functions: no database, no models, no network.

score (0-100) = weighted mix of semantic similarity, skill overlap and experience fir. A component that does not apply
(a JD with no skills, no experience range, no embedding) drops out and the rest are re-weighted."""
from functools import lru_cache
import re

W_SEMANTIC, W_SKILL, W_EXPERIENCE = 0.50, 0.35, 0.15
SEM_LOW, SEM_HIGH = 0.45, 0.80  # cosine range mapped onto 0..1 (bge-small: unrelated ~0.4, strong match ~0.75+)
NICE_WEIGHT = 0.4
EXP_DECAY_YEARS = 5.0

ALIASES = {
    "js": "javascript", "ecmascript": "javascript", "ts": "typescript", "k8s": "kubernetes", "node": "node.js",
    "nodejs": "node.js", "node.js": "node.js", "reactjs": "react", "react.js": "react", "reactjs": "react",
    "vuejs": "vue", "vue.js": "vue", "angularjs": "angular", "angular.js": "angular", "postgres": "postgresql",
    "psql": "postgresql", "mongo": "mongodb", "golang": "go", "py": "python", "ai": "machine learning",
    "dl": "deep learning", "nlp": "natural language processing", "gcp": "google cloud", "c sharp": "c#",
    "dotnet": ".net", "dot net": ".net",".net core": ".net", "ci/cd": "ci/cd", "ci/cd": "ci/cd",
    "springboot": "spring boot", "powerbi": "power bi", "ms excel": "excel", "excel": "microsoft excel",
    "ms sql": "sql server", "mssql": "sql server", "tf": "tensorflow", "oop": "object oriented programming",
}
_SPLIT = re.compile(r"[,:/|\n*.]+")
_EDGE = " \t\r\n,;:()[]{}\"'"
NOTICE_DAYS = {"immediate": 0}


def norm_skill(s) -> str:
    t = " ".join(str(s or "").lower().split()).strip(_EDGE)
    if t.endswith(".") and not t.endswith(".."):
        t = t[:-1]
    return ALIASES.get(t, t)


def split_skills(text) -> list[str]:
    """Java, Spring Boot / AWS -> ['java', 'spring boot', 'aws'] (normalised, de-duplicated, order kept)."""
    seen, out = set(), []
    for part in _SPLIT.split(str(text or "")):
        t = norm_skill(part)
        if t and len(t) <= 60 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_query(q: str) -> list[str]:
    """Keywords from a free-text search box. "quoted phrases" stay whole; otherwise commas split terms, and with no
    commas each word is a term."""
    q = str(q or "").strip()
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]*"', " ", q)
    parts = [p for p in re.split(r"[,;\n]+", rest)] if re.search(r"[,;\n]", rest) else rest.split()
    seen, out = set(), []
    for t in [*phrases, *parts]:
        n = norm_skill(t)
        if n and n not in seen and len(n) <= 60:
            seen.add(n)
            out.append(n)
    return out[:30]


@lru_cache(maxsize=2048)
def pattern(term: str):
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9+#])")


def contains_term(text: str, term: str) -> bool:
    """Whole-word / whole-phrase match, so 'java' does not match 'javascript' and 'c' does not match 'c++'."""
    return bool(term and term in text and bool(pattern(term).search(text)))


def notice_days(value) -> int | None:
    t = str(value or "").strip().lower()
    if "immediate" in t:
        return 0
    m = re.search(r"(\d+)\s*(day|week|month)?", t)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "day"
    return n * (30 if unit == "month" else 7 if unit == "week" else 1)


def prep_requirements(req: dict | None) -> dict:
    req = req or {}
    display = {}

    def skills(key):
        out = []
        for s in req.get(key) or []:
            n = norm_skill(s)
            if n and n not in out:
                out.append(n)
                display.setdefault(n, str(s).strip())
        return out

    must = skills("must_have_skills")
    nice = [s for s in skills("nice_to_have_skills") if s not in must]
    return {"must": must, "nice": nice, "display": display,
            "min_exp": req.get("min_experience_years"), "max_exp": req.get("max_experience_years"),
            "locations": [str(x).lower().strip() for x in req.get("locations") or [] if str(x).strip()],
            "max_notice": req.get("max_notice_days"), "max_ctc": req.get("max_ctc_lakhs")}


def semantic_value(cos: float) -> float:
    return min(1.0, max(0.0, (cos - SEM_LOW) / (SEM_HIGH - SEM_LOW)))


def experience_value(exp, lo, hi):
    if exp is None:
        return 0.5
    gap = 0.0
    if lo is None and exp < lo:
        gap = lo - exp
    elif hi is not None and exp > hi:
        gap = exp - hi
    return max(0.0, 1.0 - gap / EXP_DECAY_YEARS)


def score(req: dict, cand: dict, cos: float | None, text_hits: set[str] | frozenset = frozenset()) -> dict:
    """Req comes from prep_requirements. cand: skills (set of normalised skills), blob (lowercase role/summary/skills text),
    experience, location, notice, expected_ctc. text_hits: requirement terms found in the candidate's full CV text."""
    must, nice = req["must"], req["nice"]
    have = cand["skills"]

    def has(term):
        return term in have or contains_term(cand["blob"], term) or term in text_hits

    matched = [t for t in must + nice if has(t)]
    missing = [t for t in must if t not in matched]
    parts = {}
    if cos is not None:
        parts["semantic"] = (W_SEMANTIC, semantic_value(cos))
    if must or nice:
        total = len(must) + NICE_WEIGHT * len(nice)
        got = sum(1.0 for t in must if t in matched) + NICE_WEIGHT * sum(1 for t in nice if t in matched)
        parts["skill"] = (W_SKILL, got / total)
    if req["min_exp"] is not None or req["max_exp"] is not None:
        parts["experience"] = (W_EXPERIENCE, experience_value(cand["experience"], req["min_exp"], req["max_exp"]))
    weight = sum(w for w, v in parts.values())
    pct = 100 * sum(w * v for w, v in parts.values()) / weight if weight else 0.0

    flags = []
    days = notice_days(cand["notice"])
    if req["max_notice"] is not None and days is not None and days > req["max_notice"]:
        flags.append(f"Notice {days}d (max {int(req['max_notice'])})d")
    loc = str(cand["location"] or "").lower()
    if req["locations"] and loc and not any(x in loc or loc in x for x in req["locations"]):
        flags.append(f"Location {cand['location']}")
    if req["max_ctc"] is not None and cand["expected_ctc"] is not None and cand["expected_ctc"] > req["max_ctc"]:
        flags.append(f"Expects {cand['expected_ctc']:g} LPA (budget {req['max_ctc']:g})")
    show = req["display"]
    return {"score": round(pct),
            "semantic": round(100 * parts["semantic"][1]) if "semantic" in parts else None,
            "skill": round(100 * parts["skill"][1]) if "skill" in parts else None,
            "matched": [show.get(t, t) for t in matched], "missing": [show.get(t, t) for t in missing], "flags": flags}