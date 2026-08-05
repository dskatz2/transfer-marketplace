"""Core H-2A transfer-window matching: a worker can move from a contract ending on
date E to a contract starting on date S if 0 <= (S - E).days <= 30.

Contracts whose real end date has already passed are projected forward by exactly
one year (H-2A jobs are seasonal and repeat annually) so we can still surface a
same-season opportunity for the *next* cycle. Projected matches are flagged so the
UI can distinguish "confirmed on file" from "estimated from last cycle timing."
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import models
from .geo import distance_miles as _distance_miles
from .matching_entities import normalize_name

MIN_WORKERS = 25
MAX_GAP_DAYS = 30


@dataclass
class EffectiveWindow:
    contract: models.Contract
    start: date
    end: date
    is_projected: bool


def effective_window(contract, today: date, project: bool = True) -> EffectiveWindow:
    """project=False is used for hand-typed quick-match dates, which already mean
    exactly what the user entered and should never be auto-shifted a year forward."""
    if project and contract.contract_end < today:
        shift = timedelta(days=365)
        return EffectiveWindow(contract, contract.contract_start + shift, contract.contract_end + shift, True)
    return EffectiveWindow(contract, contract.contract_start, contract.contract_end, False)


@dataclass
class AdHocContract:
    """A hand-typed, unsaved stand-in for a prospect's contract (quick-match search).
    Duck-types the subset of models.Contract that matching/serialization touch."""

    employer_name: str
    normalized_employer_name: str
    worker_count: int
    contract_start: date
    contract_end: date
    id: int | None = None
    case_number: str = "AD-HOC"
    trade_name_dba: str | None = None
    fein: str | None = None
    job_title: str | None = None
    worker_count_source: str = "manual entry"
    anticipated_hours: int | None = None
    wage_offer: float | None = None
    wage_offer_unit: str | None = None
    worksite_city: str | None = None
    worksite_state: str | None = None
    case_status: str = "Hypothetical — not on file"
    enterprise_id: int | None = None
    candidate_enterprise_id: int | None = None
    match_confidence: float | None = None
    match_status: str = "prospect"
    enterprise: object | None = None
    candidate_enterprise: object | None = None


@dataclass
class TransferMatch:
    from_contract: models.Contract
    to_contract: models.Contract
    from_window: EffectiveWindow
    to_window: EffectiveWindow
    gap_days: int
    transferable_workers: int

    @property
    def is_projected(self) -> bool:
        return self.from_window.is_projected or self.to_window.is_projected

    @property
    def distance_miles(self) -> float | None:
        return _distance_miles(
            self.from_contract.worksite_city, self.from_contract.worksite_state,
            self.to_contract.worksite_city, self.to_contract.worksite_state,
        )


def _eligible_contracts(db: Session, today: date) -> list[EffectiveWindow]:
    contracts = (
        db.query(models.Contract)
        .filter(models.Contract.worker_count >= MIN_WORKERS)
        .filter(models.Contract.match_status != "review")
        .all()
    )
    return [effective_window(c, today) for c in contracts]


def _same_employer(a: models.Contract, b: models.Contract) -> bool:
    if a.enterprise_id is not None and a.enterprise_id == b.enterprise_id:
        return True
    if a.enterprise_id is None and b.enterprise_id is None:
        return a.normalized_employer_name == b.normalized_employer_name
    return False


def find_all_transfer_matches(db: Session, today: date | None = None) -> list[TransferMatch]:
    today = today or date.today()
    windows = _eligible_contracts(db, today)

    # Index destinations by their effective start date for fast +/-30-day lookups.
    by_start: dict[date, list[EffectiveWindow]] = defaultdict(list)
    for w in windows:
        by_start[w.start].append(w)

    matches: list[TransferMatch] = []
    for source in windows:
        for offset in range(0, MAX_GAP_DAYS + 1):
            day = source.end + timedelta(days=offset)
            for dest in by_start.get(day, []):
                if dest.contract.id == source.contract.id:
                    continue
                if _same_employer(source.contract, dest.contract):
                    continue
                matches.append(TransferMatch(
                    from_contract=source.contract,
                    to_contract=dest.contract,
                    from_window=source,
                    to_window=dest,
                    gap_days=offset,
                    transferable_workers=min(source.contract.worker_count, dest.contract.worker_count),
                ))
    return matches


def load_dismissed_pairs(db: Session) -> set[tuple[int, int]]:
    rows = db.query(models.DismissedMatch.from_contract_id, models.DismissedMatch.to_contract_id).all()
    return {(f, t) for f, t in rows}


def customer_customer_matches(db: Session, today: date | None = None) -> list[TransferMatch]:
    dismissed = load_dismissed_pairs(db)
    return [
        m for m in find_all_transfer_matches(db, today)
        if m.from_contract.enterprise_id is not None and m.to_contract.enterprise_id is not None
        and (m.from_contract.id, m.to_contract.id) not in dismissed
    ]


def customer_prospect_matches(db: Session, today: date | None = None) -> list[TransferMatch]:
    dismissed = load_dismissed_pairs(db)
    out = []
    for m in find_all_transfer_matches(db, today):
        a_is_customer = m.from_contract.enterprise_id is not None
        b_is_customer = m.to_contract.enterprise_id is not None
        if a_is_customer != b_is_customer and (m.from_contract.id, m.to_contract.id) not in dismissed:
            out.append(m)
    return out


def search_needs_workers(
    db: Session, prospect_contract, today: date | None = None, project_prospect: bool = True,
) -> list[TransferMatch]:
    """Seso customers whose contracts end within 30 days before this prospect contract starts."""
    if prospect_contract.worker_count < MIN_WORKERS:
        return []
    today = today or date.today()
    dest = effective_window(prospect_contract, today, project=project_prospect)
    windows = _eligible_contracts(db, today)
    out = []
    for src in windows:
        if src.contract.enterprise_id is None:
            continue
        if _same_employer(src.contract, prospect_contract):
            continue
        gap = (dest.start - src.end).days
        if 0 <= gap <= MAX_GAP_DAYS:
            out.append(TransferMatch(
                from_contract=src.contract, to_contract=prospect_contract,
                from_window=src, to_window=dest, gap_days=gap,
                transferable_workers=min(src.contract.worker_count, prospect_contract.worker_count),
            ))
    return out


def search_save_outbound_transportation(
    db: Session, prospect_contract, today: date | None = None, project_prospect: bool = True,
) -> list[TransferMatch]:
    """Seso customers whose contracts start within the 30 days after this prospect contract ends."""
    if prospect_contract.worker_count < MIN_WORKERS:
        return []
    today = today or date.today()
    src = effective_window(prospect_contract, today, project=project_prospect)
    windows = _eligible_contracts(db, today)
    out = []
    for dest in windows:
        if dest.contract.enterprise_id is None:
            continue
        if _same_employer(dest.contract, prospect_contract):
            continue
        gap = (dest.start - src.end).days
        if 0 <= gap <= MAX_GAP_DAYS:
            out.append(TransferMatch(
                from_contract=prospect_contract, to_contract=dest.contract,
                from_window=src, to_window=dest, gap_days=gap,
                transferable_workers=min(prospect_contract.worker_count, dest.contract.worker_count),
            ))
    return out


def build_quick_match_contract(
    worker_count: int, target_date: date, employer_name: str | None = None,
    worksite_city: str | None = None, worksite_state: str | None = None,
) -> AdHocContract:
    label = (employer_name or "").strip() or "New prospect"
    return AdHocContract(
        employer_name=label,
        normalized_employer_name=normalize_name(label),
        worker_count=worker_count,
        contract_start=target_date,
        contract_end=target_date,
        worksite_city=(worksite_city or "").strip() or None,
        worksite_state=(worksite_state or "").strip() or None,
    )


def quick_match(
    db: Session, worker_count: int, mode: str, target_date: date,
    employer_name: str | None = None, worksite_city: str | None = None,
    worksite_state: str | None = None, today: date | None = None,
) -> tuple[AdHocContract, list[TransferMatch]]:
    """Search by hand-typed date + worker count instead of an existing filed contract."""
    prospect = build_quick_match_contract(worker_count, target_date, employer_name, worksite_city, worksite_state)
    if mode == "needs_workers":
        matches = search_needs_workers(db, prospect, today, project_prospect=False)
    else:
        matches = search_save_outbound_transportation(db, prospect, today, project_prospect=False)
    matches.sort(key=lambda m: -m.transferable_workers)
    return prospect, matches
