from . import models
from .matching_transfers import TransferMatch, MIN_WORKERS


def contract_to_dict(c: models.Contract) -> dict:
    return {
        "id": c.id,
        "case_number": c.case_number,
        "employer_name": c.employer_name,
        "trade_name_dba": c.trade_name_dba,
        "job_title": c.job_title,
        "worker_count": c.worker_count,
        "worker_count_source": c.worker_count_source,
        "anticipated_hours": getattr(c, "anticipated_hours", None),
        "wage_offer": getattr(c, "wage_offer", None),
        "wage_offer_unit": getattr(c, "wage_offer_unit", None),
        "contract_start": c.contract_start.isoformat(),
        "contract_end": c.contract_end.isoformat(),
        "worksite_city": c.worksite_city,
        "worksite_state": c.worksite_state,
        "case_status": c.case_status,
        "match_status": c.match_status,
        "match_confidence": c.match_confidence,
        "qualifies_for_matching": c.worker_count >= MIN_WORKERS,
        "enterprise": {"id": c.enterprise.id, "name": c.enterprise.name} if c.enterprise else None,
        "candidate_enterprise": (
            {"id": c.candidate_enterprise.id, "name": c.candidate_enterprise.name}
            if c.candidate_enterprise else None
        ),
    }


def match_to_dict(m: TransferMatch) -> dict:
    return {
        "from": {
            **contract_to_dict(m.from_contract),
            "effective_end": m.from_window.end.isoformat(),
            "is_projected": m.from_window.is_projected,
        },
        "to": {
            **contract_to_dict(m.to_contract),
            "effective_start": m.to_window.start.isoformat(),
            "is_projected": m.to_window.is_projected,
        },
        "gap_days": m.gap_days,
        "transferable_workers": m.transferable_workers,
        "is_projected": m.is_projected,
        "distance_miles": m.distance_miles,
        "dismissable": m.from_contract.id is not None and m.to_contract.id is not None,
    }


def dismissed_to_dict(d: models.DismissedMatch) -> dict:
    return {
        "id": d.id,
        "dismissed_at": d.dismissed_at.isoformat() if d.dismissed_at else None,
        "from_contract": contract_to_dict(d.from_contract) if d.from_contract else None,
        "to_contract": contract_to_dict(d.to_contract) if d.to_contract else None,
    }


def manual_alias_to_dict(a: models.ManualAlias) -> dict:
    return {
        "id": a.id,
        "alias_name": a.alias_name,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "enterprise": {"id": a.enterprise.id, "name": a.enterprise.name} if a.enterprise else None,
    }
