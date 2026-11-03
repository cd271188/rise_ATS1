"""Input cleaning. Messages are identical to the v1 app so the UI behaves the same."""
import re
from datetime import datetime

from ..fields import DATES, FIELD_KEYS, INTERVIEW_DATES, INTERVIEW_FIELDS, NUMERIC, REQUIRED, STATUSES
from .common import ValidationError


def parse_ref(text) -> int | None:
    """CND-0007', 'cnd-7' or '7' -> 7."""
    m = re.fullmatch(r"\s*(?:CND-)?(\d+)\s*", str(text or ""), re.I)
    return int(m.group(1)) if m else None


def clean_date(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError("use the format YYYY-MM-DD")


def clean_candidate(data: dict, partial: bool = False) -> dict:
    errors, out = {}, {}
    for key in FIELD_KEYS + ["current_status"]:
        if key not in data:
            if not partial and key in REQUIRED:
                errors[key] = "required"
            continue
        raw = data[key]
        v = "" if raw is None else str(raw).strip()
        if len(v) > 2000:
            errors[key] = "too long"
            continue
        try:
            if key in DATES:
                v = clean_date(v)
            elif key in NUMERIC:
                v = float(v) if v != "" else None
                if v is not None and (v < 0 or v != v or v == float("inf")):
                    raise ValueError("must not be negative")
            elif key == "email" and v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise ValueError("not a valid email address")
            elif key == "phone" and v and len(re.sub(r"\D", "", v)) < 7:
                raise ValueError("not a valid phone number")
            elif key == "current_status" and v and v not in STATUSES:
                raise ValueError("not a valid status")
            else:
                v = v or None
        except ValueError as e:
            errors[key] = str(e) if str(e).startswith(("use", "must", "not")) else "not a valid number"
            continue
        if v is None and key in REQUIRED:
            errors[key] = "required"
        out[key] = v
    if errors:
        raise ValidationError(errors)
    return out


def clean_interview(data: dict):
    errors, out = {}, {}
    ref = parse_ref(data.get("candidate_id"))
    if ref is None:
        errors["candidate_id"] = "pick a candidate"
    for key in INTERVIEW_FIELDS[1:]:
        v = str(data.get(key) or "").strip()
        if len(v) > 4000:
            errors[key] = "too long"
            continue
        if key in INTERVIEW_DATES:
            try:
                v = clean_date(v)
            except ValueError as e:
                errors[key] = str(e)
                continue
        elif key == "interview_time" and v and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
            errors[key] = "use HH:MM"
            continue
        out[key] = v or None
    if not out.get("status"):
        errors["status"] = "required"
    elif out["status"] not in STATUSES:
        errors["status"] = "not a valid status"
    if errors:
        raise ValidationError(errors)
    return ref, out