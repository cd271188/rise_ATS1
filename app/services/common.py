"""Shared service types: request context and domain exceptions."""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from ..fields import ADMIN_ROLES, WRITE_ROLES
from ..models import Organization, User


class ValidationError(ValueError):
    def __init__(self, errors: dict):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class NotFound(LookupError):
    pass


class Forbidden(PermissionError):
    pass


class QuotaExceeded(Exception):
    pass


class Conflict(Exception):
    def __init__(self, message: str, current: dict | None = None):
        super().__init__(message)
        self.current = current


@dataclass
class Ctx:
    db: Session
    user: User
    ip: str = ""
    data_org_id_override: int | None = None

    @property
    def org_id(self) -> int:
        return self.user.org_id

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    @property
    def org(self) -> Organization:
        return self.db.get(Organization, self.user.org_id)
    
    @property
    def data_org_id(self) -> int:
        """The Company whose candidate and interviews this user workds on: a vendor works in its client's pipeline."""
        if self.data_org_id_override is not None:
            return self.data_org_id_override
        return self.org.parent_org_id or self.user.org_id

    @property
    def vendor_id(self) -> int | None:
        """Set for vendor users: they only see the candidates and their own company submitted."""
        return self.user.org_id if self.org.parent_org_id else None

    def today(self) -> date:
        return org_today(self.org)


def org_today(org: Organization | None) -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(org.timezone)).date()
    except Exception:  # unknown zone or no tz database on this machine
        return datetime.now(timezone.utc).date()
