"""Offer letters: a company's compensation structure (built by Rise, accepted by the owner) and PDF generation for candidates."""
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select

from ..models import Candidate, OfferLetter, OfferStructure, Organization, User, utcnow
from . import audit, offer_docs
from .candidates import get_row, public_id, scope
from .common import Conflict, Ctx, Forbidden, NotFound, ValidationError, org_today
from .platform import BY, _client, _need, _need_platform

log = logging.getLogger("ats")

KINDS = ("earning", "employer", "deduction")
CALCS = ("pct_ctc", "pct_basic", "fixed", "balance")
PERIODS = ("monthly", "annual")
SYSTEM_FIELDS = ("candidate_name", "candidate_email", "candidate_phone", "candidate_id", "designation", "client",
                 "job_req_id", "company_name", "offer_date")
TOTALS = ("ctc_annual", "ctc_monthly", "gross_annual", "gross_monthly")
RESERVED = set(SYSTEM_FIELDS) | {"ctc", "gross"}
WORKING = ("draft", "in_review", "changes_requested")
KEY = re.compile(r"[a-z][a-z0-9_]{0,29}")
MAX_COMPONENTS = 30


# ---------------------------------------------------------------- numbers
def inr(n: int) -> str:
    """12345678 -> '1,23,45,678'"""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if n < 0 else "") + s


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_ctc(v) -> int:
    text = re.sub(r"[,\s]|rs\.?", "", str(v if v is not None else ""), flags=re.I)
    if not re.fullmatch(r"\d{1,11}", text) or int(text) <= 0:
        raise ValidationError({"ctc": "enter the annual CTC in rupees, for example 1200000"})
    return int(text)


# ---------------------------------------------------------------- components and calculation
def _bad(i: int, message: str):
    raise ValidationError({"components": f"component {i}: {message}"})


def clean_components(raw) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_COMPONENTS:
        raise ValidationError({"components": f"give a list of at most {MAX_COMPONENTS} components"})
    out, seen = [], set()
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            _bad(i, "invalid")
        key = str(c.get("key") or "").strip().lower()
        label = "".join(offer_docs._clean(c.get("label"))).split()[:60]
        kind, calc = str(c.get("kind") or "earning"), str(c.get("calc") or "")
        if not KEY.fullmatch(key) or key.endswith(("_annual", "_monthly")):
            _bad(i, "the key must be lower-case letters, digits and underscores, starting with a letter, and not end in _annual or _monthly")
        if key in RESERVED or key in seen:
            _bad(i, f"the key '{key}' is " + ("reserved" if key in RESERVED else "twice"))
        if not label:
            _bad(i, "give it a name")
        if kind not in KINDS:
            _bad(i, "choose earning, employer or deduction")
        if calc not in CALCS:
            _bad(i, "choose how it is calculated")
        value, period = None, None
        if calc != "balance":
            raw_value = c.get("value")
            try:
                if isinstance(raw_value, bool) or raw_value in (None, ""):
                    raise InvalidOperation
                d = Decimal(str(raw_value))
                if not d.is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                _bad(i, "enter a number")
            if calc == "fixed":
                if not 0 <= d <= 10**9:
                    _bad(i, "the amount must be between 0 and 1,000,000,000")
                period = str(c.get("period") or "monthly")
                if period not in PERIODS:
                    _bad(i, "choose monthly or annual")
            elif not 0 < d <= 100:
                _bad(i, "the percentage must be above 0 and at most 100")
            value = int(d) if d == d.to_integral_value() else float(d)
        if kind == "deduction":
            _bad(i, "a deduction cannot be the balancing component")
        seen.add(key)
        out.append({"key": key, "label": label, "kind": kind, "calc": calc, "value": value, "period": period})
    if sum(c["calc"] == "balance" for c in out) > 1:
        raise ValidationError({"components": "only one component can take the balance"})
    basic = next((c for c in out if c["key"] == "basic"), None)
    if any(c["calc"] == "pct_basic" for c in out) and not basic:
        raise ValidationError({"components": "a component is a % of Basic, so add a component with the key 'basic'"})
    if basic and basic["calc"] not in ("pct_ctc", "fixed"):
        raise ValidationError({"components": "'basic' must be a % of CTC or a fixed amount"})
    return out


def compute(components: list[dict], ctc: int) -> dict:
    """Annual and monthly rupee amounts per component for an annual CTC."""
    total = Decimal(ctc)

    def amount(c, basic):
        v = Decimal(str(c["value"]))
        if c["calc"] == "pct_ctc":
            return total * v / 100
        if c["calc"] == "pct_basic":
            return Decimal(basic) * v / 100
        return v * 12 if c["period"] == "monthly" else v

    annual: dict[str, int] = {}
    for c in components:
        if c["key"] == "basic":
            annual["basic"] = _round(amount(c, 0))
    for c in components:
        if c["calc"] != "balance" and c["key"] not in annual:
            annual[c["key"]] = _round(amount(c, annual.get("basic", 0)))
    balance = next((c for c in components if c["calc"] == "balance"), None)
    allocated = sum(annual[c["key"]] for c in components if c["kind"] != "deduction" and c["calc"] != "balance")
    if balance:
        rest = ctc - allocated
        if rest < 0:
            raise ValidationError({"ctc": "the other components add up to more than this CTC"})
        annual[balance["key"]] = rest
        allocated = ctc
    rows = []
    for c in components:
        a = annual[c["key"]]
        m = _round(Decimal(a) / 12)
        rows.append({"key": c["key"], "label": c["label"], "kind": c["kind"], "annual": a, "monthly": m,
                     "annual_text": inr(a), "monthly_text": inr(m)})
    gross = sum(r["annual"] for r in rows if r["kind"] == "earning")
    return {"ctc": ctc, "ctc_text": inr(ctc), "rows": rows, "gross": gross, "gross_text": inr(gross),
            "unallocated": ctc - allocated, "unallocated_text": inr(ctc - allocated)}


def _sample_ctc(components: list[dict]) -> int:
    fixed = sum(c["value"] * (12 if c.get("period") == "monthly" else 1) for c in components if c["calc"] == "fixed")
    return int(max(1_200_000, 2 * fixed))


def compensation_values(calc: dict) -> dict:
    out = {"ctc": inr(calc["ctc"]), "ctc_annual": inr(calc["ctc"]), "ctc_monthly": inr(_round(Decimal(calc["ctc"]) / 12)),
           "gross_annual": inr(calc["gross"]), "gross_monthly": inr(_round(Decimal(calc["gross"]) / 12))}
    for r in calc["rows"]:
        out[r["key"] + "_annual"], out[r["key"] + "_monthly"] = r["annual_text"], r["monthly_text"]
    return out


# ---------------------------------------------------------------- placeholders
def classify(names: list[str], components: list[dict]) -> dict:
    comp = set(TOTALS) | {"ctc"}
    for c in components:
        comp |= {c["key"] + "_annual", c["key"] + "_monthly"}
    out = {"automatic": [], "compensation": [], "asked": [], "unknown": []}
    for n in names:
        if n in SYSTEM_FIELDS:
            out["automatic"].append(n)
        elif n in comp:
            out["compensation"].append(n)
        elif n.endswith(("_annual", "_monthly")):
            out["unknown"].append(n)
        else:
            out["asked"].append(n)
    return out


def _label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _analysis(s: OfferStructure) -> dict:
    empty = {"automatic": [], "compensation": [], "asked": [], "unknown": [], "malformed": [], "error": None}
    if not s.template_file:
        return empty
    try:
        info = offer_docs.placeholders(s.template_kind, s.template_file)
    except ValueError as e:
        return {**empty, "error": str(e)}
    return {**classify(info["names"], s.components or []), "malformed": info["malformed"], "error": None}


# ---------------------------------------------------------------- structure lookup and views
def _versions(db, org_id: int) -> list[OfferStructure]:
    return list(db.scalars(select(OfferStructure).where(OfferStructure.org_id == org_id).order_by(OfferStructure.version)))


def _working(db, org_id: int) -> OfferStructure | None:
    return db.scalar(select(OfferStructure).where(OfferStructure.org_id == org_id, OfferStructure.status.in_(WORKING)))


def _active(db, org_id: int) -> OfferStructure | None:
    return db.scalar(select(OfferStructure).where(OfferStructure.org_id == org_id, OfferStructure.status == "active"))


def _view(s: OfferStructure, ctc: int | None = None) -> dict:
    comps = s.components or []
    preview, preview_error = None, None
    if comps:
        try:
            preview = compute(comps, ctc or _sample_ctc(comps))
        except ValidationError as e:
            preview_error = next(iter(e.errors.values()))
    return {"id": s.id, "version": s.version, "status": s.status, "template_name": s.template_name,
            "template_kind": s.template_kind, "has_template": bool(s.template_file), "components": comps,
            "events": s.events or [], "placeholders": _analysis(s), "preview": preview, "preview_error": preview_error,
            "sent_at": s.sent_at.strftime("%Y-%m-%d %H:%M") if s.sent_at else None,
            "decided_at": s.decided_at.strftime("%Y-%m-%d %H:%M") if s.decided_at else None}


def _state(db, org: Organization, ctc: int | None = None) -> dict:
    rows = _versions(db, org.id)
    current = next((s for s in rows if s.status in WORKING), None) or next((s for s in rows if s.status == "active"), None)
    active = next((s for s in rows if s.status == "active"), None)
    return {"company": {"id": org.id, "name": org.name, "current": _view(current, ctc) if current else None},
            "active_version": active.version if active else None,
            "versions": [{"version": s.version, "status": s.status} for s in rows]}


def _event(s: OfferStructure, ctx: Ctx, kind: str, note: str = "", rise: bool = False) -> None:
    who = ctx.user.full_name + (" (Rise Consulting)" if rise else "")
    s.events = [*(s.events or []), {"at": utcnow().strftime("%Y-%m-%d %H:%M"), "by": who, "kind": kind, "note": note[:2000]}]


def _parse_ctc_arg(ctc) -> int | None:
    try:
        return parse_ctc(ctc) if ctc else None
    except ValidationError:
        return None


def _editable(ctx: Ctx, org: Organization, rise: bool) -> OfferStructure:
    """The version that may be changed now; starts the first draft if the company has none."""
    working = _working(ctx.db, org.id)
    if working:
        if working.status == "in_review":
            raise Conflict("this version is with the company owner for review, so it cannot be changed now")
        return working
    if _active(ctx.db, org.id):
        raise Conflict("the accepted structure is locked; " + ("start a new version to change it" if rise
                                                                else "ask Rise Consulting to change it"))
    top = ctx.db.scalar(select(func.max(OfferStructure.version)).where(OfferStructure.org_id == org.id)) or 0
    s = OfferStructure(org_id=org.id, version=top + 1, status="draft", components=[], events=[], created_by=ctx.user.id)
    ctx.db.add(s)
    ctx.db.flush()
    _event(s, ctx, "created", rise=rise)
    return s


def _store_template(ctx: Ctx, s: OfferStructure, blob: bytes, filename: str, rise: bool) -> None:
    try:
        kind = offer_docs.validate_template(blob)
    except ValueError as e:
        raise ValidationError({"template": str(e)})
    name = re.sub(r"[^A-Za-z0-9 .()-]", "", filename or "")[:120].strip() or "offer-letter." + kind
    s.template_file, s.template_kind, s.template_name = blob, kind, name
    _event(s, ctx, "template", name, rise)


# ---------------------------------------------------------------- Rise side
def _audit_rise(ctx: Ctx, org: Organization, action: str, s: OfferStructure, extra: dict | None = None) -> None:
    audit.record(ctx, action, "offer_structure", s.id, {"company": org.name, "version": s.version, **(extra or {})})
    audit.record_raw(ctx.db, org.id, None, action, ctx.ip, {"by": BY, "version": s.version, **(extra or {})})


def rise_get(ctx: Ctx, org_id: int, ctc=None) -> dict:
    _need_platform(ctx)
    return _state(ctx.db, _client(ctx, org_id), _parse_ctc_arg(ctc))


def rise_save(ctx: Ctx, org_id: int, data: dict) -> dict:
    _need(ctx, "manage_compensation")
    org = _client(ctx, org_id)
    comps = clean_components(data.get("components"))
    s = _editable(ctx, org, True)
    s.components = comps
    _event(s, ctx, "saved", f"{len(comps)} components", True)
    _audit_rise(ctx, org, "offer.structure_save", s)
    ctx.db.commit()
    return _state(ctx.db, org)


def rise_template(ctx: Ctx, org_id: int, blob: bytes, filename: str) -> dict:
    _need(ctx, "manage_compensation")
    org = _client(ctx, org_id)
    s = _editable(ctx, org, True)
    _store_template(ctx, s, blob, filename, True)
    _audit_rise(ctx, org, "offer.template_upload", s, {"file": s.template_name})
    ctx.db.commit()
    return _state(ctx.db, org)


def rise_send(ctx: Ctx, org_id: int) -> dict:
    _need(ctx, "manage_compensation")
    org = _client(ctx, org_id)
    s = _working(ctx.db, org.id)
    if not s or s.status == "in_review":
        raise Conflict("there is no draft to send" if not s else "this version is already with the owner")
    problems = []
    if not s.template_file:
        problems.append("upload the offer letter template first")
    else:
        info = _analysis(s)
        if info["error"]:
            problems.append(info["error"])
        if info["malformed"]:
            problems.append("fix the broken {{ }} in: " + "; ".join(info["malformed"]))
        if info["unknown"]:
            problems.append("no compensation component matches: " + ", ".join(info["unknown"]))
    comps = s.components or []
    if comps:
        try:
            compute(comps, _sample_ctc(comps))
        except ValidationError as e:
            problems.append(next(iter(e.errors.values())))
    if problems:
        raise ValidationError({"structure": "; ".join(problems)})
    s.status, s.sent_at = "in_review", utcnow()
    _event(s, ctx, "sent", rise=True)
    _audit_rise(ctx, org, "offer.send_for_review", s)
    ctx.db.commit()
    return _state(ctx.db, org)


def rise_new_version(ctx: Ctx, org_id: int) -> dict:
    _need(ctx, "manage_compensation")
    org = _client(ctx, org_id)
    if _working(ctx.db, org.id):
        raise Conflict("a new version is already in progress")
    active = _active(ctx.db, org.id)
    if not active:
        raise Conflict("there is no accepted structure to copy")
    top = ctx.db.scalar(select(func.max(OfferStructure.version)).where(OfferStructure.org_id == org.id))
    s = OfferStructure(org_id=org.id, version=top + 1, status="draft", components=list(active.components or []),
                       template_name=active.template_name, template_kind=active.template_kind,
                       template_file=active.template_file, events=[], created_by=ctx.user.id)
    ctx.db.add(s)
    ctx.db.flush()
    _event(s, ctx, "created", f"copied from version {active.version}", True)
    _audit_rise(ctx, org, "offer.new_version", s)
    ctx.db.commit()
    return _state(ctx.db, org)


def _template_of(ctx: Ctx, org: Organization) -> tuple[bytes, str, str]:
    s = _working(ctx.db, org.id) or _active(ctx.db, org.id)
    if not s or not s.template_file:
        raise NotFound("no template uploaded")
    return s.template_file, s.template_name or "offer-letter", s.template_kind


def rise_template_file(ctx: Ctx, org_id: int) -> tuple[bytes, str, str]:
    _need_platform(ctx)
    return _template_of(ctx, _client(ctx, org_id))


# ---------------------------------------------------------------- company side
def _own_org(ctx: Ctx, owner_only: bool) -> Organization:
    if ctx.org.is_platform or ctx.vendor_id or not ctx.is_admin:
        raise Forbidden("only the company's owner and admins can see the offer letter set-up")
    if owner_only and ctx.role != "owner":
        raise Forbidden("only the company owner can do this")
    return ctx.org


def owner_get(ctx: Ctx, ctc=None) -> dict:
    return _state(ctx.db, _own_org(ctx, False), _parse_ctc_arg(ctc))


def owner_template(ctx: Ctx, blob: bytes, filename: str) -> dict:
    org = _own_org(ctx, True)
    s = _editable(ctx, org, False)
    _store_template(ctx, s, blob, filename, False)
    audit.record(ctx, "offer.template_upload", "offer_structure", s.id, {"version": s.version, "file": s.template_name})
    ctx.db.commit()
    return _state(ctx.db, org)


def owner_template_file(ctx: Ctx) -> tuple[bytes, str, str]:
    return _template_of(ctx, _own_org(ctx, False))


def owner_accept(ctx: Ctx) -> dict:
    org = _own_org(ctx, True)
    s = _working(ctx.db, org.id)
    if not s or s.status != "in_review":
        raise Conflict("there is nothing waiting for your review")
    previous = _active(ctx.db, org.id)
    if previous:
        previous.status = "superseded"
    s.status, s.decided_at, s.decided_by = "active", utcnow(), ctx.user.id
    _event(s, ctx, "accepted")
    audit.record(ctx, "offer.accept", "offer_structure", s.id, {"version": s.version})
    ctx.db.commit()
    return _state(ctx.db, org)


def owner_feedback(ctx: Ctx, data: dict) -> dict:
    org = _own_org(ctx, True)
    note = str(data.get("note") or "").strip()
    if not note:
        raise ValidationError({"note": "write what should change"})
    if len(note) > 2000:
        raise ValidationError({"note": "keep it under 2000 characters"})
    s = _working(ctx.db, org.id) or _active(ctx.db, org.id)
    if not s:
        raise Conflict("there is no offer letter set-up yet")
    if s.status == "in_review":
        s.status, s.decided_at, s.decided_by = "changes_requested", utcnow(), ctx.user.id
        _event(s, ctx, "feedback", note)
    else:
        _event(s, ctx, "note", note)
    audit.record(ctx, "offer.feedback", "offer_structure", s.id, {"version": s.version})
    ctx.db.commit()
    return _state(ctx.db, org)


# ---------------------------------------------------------------- generating letters
def _need_write(ctx: Ctx) -> None:
    if not ctx.can_write:
        raise Forbidden("your role is read-only")


def _accepted(ctx: Ctx) -> OfferStructure:
    s = _active(ctx.db, ctx.data_org_id)
    if not s or not s.template_file:
        raise ValidationError({"offer": "offer letters are not set up yet: the company owner has to accept the compensation structure first"})
    return s


def _automatic(ctx: Ctx, cand: Candidate) -> dict:
    org = ctx.db.get(Organization, ctx.data_org_id)
    return {"candidate_name": cand.full_name or "", "candidate_email": cand.email or "", "candidate_phone": cand.phone or "",
            "candidate_id": public_id(cand.seq), "designation": cand.primary_skill_role or "", "client": cand.client or "",
            "job_req_id": cand.job_req_id or "", "company_name": org.name, "offer_date": org_today(org).strftime("%d %B %Y")}


def letter_form(ctx: Ctx, ref) -> dict:
    _need_write(ctx)
    cand = get_row(ctx, ref)
    s = _accepted(ctx)
    groups = _analysis(s)
    auto = _automatic(ctx, cand)
    return {"version": s.version, "needs_ctc": bool(groups["compensation"]),
            "automatic": [{"name": n, "label": _label(n), "value": auto[n]} for n in groups["automatic"]],
            "inputs": [{"name": n, "label": _label(n)} for n in groups["asked"]]}


def letter_preview(ctx: Ctx, ref, data: dict) -> dict:
    _need_write(ctx)
    get_row(ctx, ref)
    s = _accepted(ctx)
    return compute(s.components or [], parse_ctc(data.get("ctc")))


def _resolve(ctx: Ctx, s: OfferStructure, cand: Candidate, data: dict) -> dict:
    groups = _analysis(s)
    if groups["error"] or groups["unknown"] or groups["malformed"]:
        raise ValidationError({"offer": "the accepted template has problems; ask Rise Consulting to correct it"})
    auto = _automatic(ctx, cand)
    values = {n: auto[n] for n in groups["automatic"]}
    if groups["compensation"]:
        values.update(compensation_values(compute(s.components or [], parse_ctc(data.get("ctc")))))
    given = data.get("inputs") if isinstance(data.get("inputs"), dict) else {}
    errors = {}
    for n in groups["asked"]:
        v = "".join(offer_docs._clean(given.get(n)).split())
        if not v:
            errors[n] = "required"
        elif len(v) > 200:
            errors[n] = "keep it under 200 characters"
        values[n] = v
    if errors:
        raise ValidationError(errors)
    return values


def _letter_dict(id: int, created_at, by: str | None, engine: str, version: int, public: str) -> dict:
    return {"id": id, "candidate_id": public, "created_at": created_at.strftime("%Y-%m-%d %H:%M"), "generated_by": by,
            "engine": engine, "version": version, "filename": f"Offer_{public}_{created_at:%Y%m%d}.pdf"}


def generate(ctx: Ctx, ref, data: dict) -> dict:
    _need_write(ctx)
    cand = get_row(ctx, ref)
    s = _accepted(ctx)
    values = _resolve(ctx, s, cand, data)
    try:
        pdf, engine = offer_docs.render(s.template_kind, s.template_file, values)
    except Exception:
        log.exception("offer letter rendering failed for structure %s", s.id)
        raise ValueError("the letter could not be produced from this template; ask Rise Consulting to check it")
    letter = OfferLetter(org_id=ctx.data_org_id, candidate_id=cand.id, structure_id=s.id, vendor_org_id=cand.vendor_org_id,
                         generated_by=ctx.user.id, values=values, pdf=pdf, pdf_engine=engine)
    ctx.db.add(letter)
    ctx.db.flush()
    public = public_id(cand.seq)
    out = _letter_dict(letter.id, letter.created_at or utcnow(), ctx.user.full_name, engine, s.version, public)
    audit.record(ctx, "offer.generate", "candidate", cand.id, {"candidate": public, "letter": letter.id, "version": s.version, "engine": engine})
    if ctx.vendor_id:
        audit.record_raw(ctx.db, ctx.data_org_id, ctx.user.id, "offer.generated_by_vendor", ctx.ip,
                         {"vendor_id": ctx.vendor_id, "candidate": public, "letter": letter.id})
    ctx.db.commit()
    return out


def list_letters(ctx: Ctx, ref) -> list[dict]:
    _need_write(ctx)
    cand = get_row(ctx, ref)
    rows = ctx.db.execute(
        select(OfferLetter.id, OfferLetter.created_at, OfferLetter.pdf_engine, User.full_name, OfferStructure.version)
        .join(OfferStructure, OfferStructure.id == OfferLetter.structure_id)
        .outerjoin(User, User.id == OfferLetter.generated_by)
        .where(OfferLetter.org_id == ctx.data_org_id, OfferLetter.candidate_id == cand.id).order_by(OfferLetter.id.desc())).all()
    return [_letter_dict(r[0], r[1], r[3], r[2], r[4], public_id(cand.seq)) for r in rows]


def download(ctx: Ctx, letter_id: int) -> tuple[bytes, str]:
    _need_write(ctx)
    letter = ctx.db.scalar(select(OfferLetter).where(OfferLetter.id == letter_id, OfferLetter.org_id == ctx.data_org_id))
    cand = letter and ctx.db.scalar(select(Candidate).where(*scope(ctx), Candidate.id == letter.candidate_id))
    if not letter or not cand:
        raise NotFound("offer letter not found")
    return letter.pdf, f"Offer_{public_id(cand.seq)}_{letter.created_at:%Y%m%d}.pdf"
