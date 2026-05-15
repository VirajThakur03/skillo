# app/services/provider_metrics.py
"""Seeker-facing provider response time + acceptance metrics (KYC-gated)."""

from __future__ import annotations

from sqlalchemy import case, func

from ..extensions import db
from ..models import Booking, BookingStatus, KycStatus, User

_DECIDED_STATUSES = (
    BookingStatus.CONFIRMED,
    BookingStatus.IN_PROGRESS,
    BookingStatus.COMPLETED,
    BookingStatus.DECLINED,
)
_ACCEPTED_STATUSES = (
    BookingStatus.CONFIRMED,
    BookingStatus.IN_PROGRESS,
    BookingStatus.COMPLETED,
)


def format_response_time(seconds: int | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    if seconds < 60:
        return "< 1 min"
    if seconds < 3600:
        return f"~{seconds // 60} min"
    if seconds < 86400:
        return f"~{seconds // 3600} hr"
    return "> 1 day"


def batch_provider_acceptance_counts(provider_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Map provider_id -> (accepted_count, decided_count)."""
    if not provider_ids:
        return {}
    accepted_expr = func.sum(
        case((Booking.status.in_(_ACCEPTED_STATUSES), 1), else_=0)
    )
    rows = (
        db.session.query(
            Booking.provider_id,
            func.count(Booking.id).label("decided_total"),
            accepted_expr.label("accepted_total"),
        )
        .filter(
            Booking.provider_id.in_(provider_ids),
            Booking.status.in_(_DECIDED_STATUSES),
        )
        .group_by(Booking.provider_id)
        .all()
    )
    out: dict[int, tuple[int, int]] = {}
    for row in rows:
        decided = int(row.decided_total or 0)
        acc = int(row.accepted_total or 0)
        out[int(row.provider_id)] = (acc, decided)
    return out


def acceptance_rate_percent(accepted: int, decided: int) -> float | None:
    if decided <= 0:
        return None
    return round((accepted / decided) * 100, 1)


def metrics_for_kyc_approved_provider(
    provider: User, stats: dict[int, tuple[int, int]]
) -> tuple[str | None, float | None]:
    """(response_label, acceptance_rate) or (None, None) if not approved."""
    if provider.kyc_status != KycStatus.approved:
        return None, None
    acc, decided = stats.get(provider.id, (0, 0))
    return (
        format_response_time(provider.avg_response_seconds),
        acceptance_rate_percent(acc, decided),
    )
