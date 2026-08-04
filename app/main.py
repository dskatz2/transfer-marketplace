from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from . import models, ingest, matching_transfers as mt
from .auth import add_auth_middleware
from .database import Base, engine, get_db
from .serializers import contract_to_dict, match_to_dict, dismissed_to_dict

Base.metadata.create_all(bind=engine)

app = FastAPI(title="H-2A Transfer Matcher")
add_auth_middleware(app)

PUBLIC_DIR = Path(__file__).parent.parent / "public"


# ---------- Uploads ----------

@app.post("/api/upload/disclosure")
async def upload_disclosure(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Expected an .xlsx file")
    content = await file.read()
    try:
        result = ingest.ingest_disclosure_xlsx(db, content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rematch = ingest.rematch_all_contracts(db)
    return {"ingest": result, "rematch": rematch}


@app.post("/api/upload/customers")
async def upload_customers(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Expected a .csv file")
    content = await file.read()
    try:
        result = ingest.ingest_customers_csv(db, content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rematch = ingest.rematch_all_contracts(db)
    return {"ingest": result, "rematch": rematch}


# ---------- Stats & review queue ----------

@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Contract.id)).scalar()
    customers = db.query(func.count(models.Contract.id)).filter(models.Contract.enterprise_id.isnot(None)).scalar()
    review = db.query(func.count(models.Contract.id)).filter(models.Contract.match_status == "review").scalar()
    prospects = db.query(func.count(models.Contract.id)).filter(models.Contract.match_status.in_(["prospect", "rejected"])).scalar()
    enterprises = db.query(func.count(models.Enterprise.id)).scalar()
    return {
        "total_contracts": total,
        "customer_contracts": customers,
        "prospect_contracts": prospects,
        "pending_review": review,
        "enterprises": enterprises,
    }


@app.get("/api/review-queue")
def review_queue(db: Session = Depends(get_db)):
    items = (
        db.query(models.Contract)
        .filter(models.Contract.match_status == "review")
        .order_by(models.Contract.match_confidence.desc())
        .all()
    )
    return [contract_to_dict(c) for c in items]


@app.post("/api/review-queue/{contract_id}/approve")
def approve_review(contract_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Contract, contract_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    if not c.candidate_enterprise_id:
        raise HTTPException(400, "No candidate enterprise to approve")
    c.enterprise_id = c.candidate_enterprise_id
    c.match_status = "manual"
    db.commit()
    return contract_to_dict(c)


@app.post("/api/review-queue/{contract_id}/reject")
def reject_review(contract_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Contract, contract_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    c.enterprise_id = None
    c.candidate_enterprise_id = None
    c.match_status = "rejected"
    db.commit()
    return contract_to_dict(c)


# ---------- Dashboard match sections ----------

_SORT_KEYS = {
    "workers": lambda m: -m.transferable_workers,
    "gap": lambda m: m.gap_days,
    "soonest": lambda m: m.to_window.start,
}


def _sorted_page(matches, sort: str, limit: int, offset: int):
    key = _SORT_KEYS.get(sort, _SORT_KEYS["workers"])
    matches = sorted(matches, key=key)
    total = len(matches)
    page = matches[offset: offset + limit]
    return total, page


@app.get("/api/matches/customer-customer")
def customer_customer(
    sort: str = Query("workers"), limit: int = Query(100, le=500), offset: int = Query(0),
    db: Session = Depends(get_db),
):
    matches = mt.customer_customer_matches(db)
    total, page = _sorted_page(matches, sort, limit, offset)
    return {"total": total, "results": [match_to_dict(m) for m in page]}


@app.get("/api/matches/customer-prospect")
def customer_prospect(
    sort: str = Query("workers"), limit: int = Query(100, le=500), offset: int = Query(0),
    db: Session = Depends(get_db),
):
    matches = mt.customer_prospect_matches(db)
    total, page = _sorted_page(matches, sort, limit, offset)
    return {"total": total, "results": [match_to_dict(m) for m in page]}


# ---------- Search ----------

@app.get("/api/search/employers")
def search_employers(q: str = Query(..., min_length=2), db: Session = Depends(get_db)):
    """Autocomplete over employer names in the disclosure data (for the prospect search box)."""
    like = f"%{q.lower()}%"
    rows = (
        db.query(models.Contract.employer_name, models.Contract.enterprise_id)
        .filter(func.lower(models.Contract.employer_name).like(like))
        .filter(models.Contract.worker_count >= mt.MIN_WORKERS)
        .distinct()
        .limit(25)
        .all()
    )
    seen = {}
    for name, enterprise_id in rows:
        seen.setdefault(name, enterprise_id)
    return [{"employer_name": name, "is_customer": eid is not None} for name, eid in seen.items()]


@app.get("/api/search/employer-contracts")
def employer_contracts(employer_name: str, db: Session = Depends(get_db)):
    contracts = (
        db.query(models.Contract)
        .filter(models.Contract.employer_name == employer_name)
        .filter(models.Contract.worker_count >= mt.MIN_WORKERS)
        .order_by(models.Contract.contract_start)
        .all()
    )
    return [contract_to_dict(c) for c in contracts]


@app.get("/api/search/quick-match")
def quick_match(
    worker_count: int = Query(..., ge=1),
    contract_date: date = Query(..., description="Contract start date for 'needs workers', end date for 'save transportation'"),
    mode: str = Query(..., pattern="^(needs_workers|save_transportation)$"),
    employer_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if worker_count < mt.MIN_WORKERS:
        raise HTTPException(400, f"H-2A transfer matches only apply to contracts of {mt.MIN_WORKERS}+ workers.")
    prospect, matches = mt.quick_match(db, worker_count, mode, contract_date, employer_name)
    return {"prospect": contract_to_dict(prospect), "results": [match_to_dict(m) for m in matches]}


# ---------- Dismiss / restore ----------

class DismissRequest(BaseModel):
    from_contract_id: int
    to_contract_id: int


@app.post("/api/matches/dismiss")
def dismiss_match(body: DismissRequest, db: Session = Depends(get_db)):
    exists = (
        db.query(models.DismissedMatch)
        .filter_by(from_contract_id=body.from_contract_id, to_contract_id=body.to_contract_id)
        .one_or_none()
    )
    if exists:
        return dismissed_to_dict(exists)
    d = models.DismissedMatch(from_contract_id=body.from_contract_id, to_contract_id=body.to_contract_id)
    db.add(d)
    db.commit()
    return dismissed_to_dict(d)


@app.get("/api/matches/dismissed")
def list_dismissed(db: Session = Depends(get_db)):
    items = db.query(models.DismissedMatch).order_by(models.DismissedMatch.dismissed_at.desc()).all()
    return [dismissed_to_dict(d) for d in items]


@app.post("/api/matches/dismissed/{dismissed_id}/restore")
def restore_dismissed(dismissed_id: int, db: Session = Depends(get_db)):
    d = db.get(models.DismissedMatch, dismissed_id)
    if not d:
        raise HTTPException(404, "Not found")
    db.delete(d)
    db.commit()
    return {"restored": dismissed_id}


@app.post("/api/matches/dismissed/reset")
def reset_dismissed(db: Session = Depends(get_db)):
    count = db.query(models.DismissedMatch).delete()
    db.commit()
    return {"restored": count}


# ---------- Dashboard summary / visuals ----------

@app.get("/api/matches/summary")
def matches_summary(db: Session = Depends(get_db)):
    combined = mt.customer_customer_matches(db) + mt.customer_prospect_matches(db)

    total_matches = len(combined)

    # A single contract can appear in many matches (one ending contract can feed
    # several destinations, and vice versa) - sum worker_count once per distinct
    # "ending" contract so this counts workers who have *a* viable option, not
    # every pairing they happen to appear in.
    from_contracts_seen = {}
    enterprise_ids = set()
    for m in combined:
        from_contracts_seen[m.from_contract.id] = m.from_contract.worker_count
        if m.from_contract.enterprise_id is not None:
            enterprise_ids.add(m.from_contract.enterprise_id)
        if m.to_contract.enterprise_id is not None:
            enterprise_ids.add(m.to_contract.enterprise_id)
    total_workers = sum(from_contracts_seen.values())
    avg_gap = round(sum(m.gap_days for m in combined) / total_matches, 1) if total_matches else 0

    top_matches = sorted(combined, key=lambda m: -m.transferable_workers)[:10]

    buckets = Counter()
    for m in combined:
        if m.gap_days <= 10:
            buckets["0-10 days"] += 1
        elif m.gap_days <= 20:
            buckets["11-20 days"] += 1
        else:
            buckets["21-30 days"] += 1
    gap_histogram = [
        {"bucket": label, "count": buckets.get(label, 0)}
        for label in ["0-10 days", "11-20 days", "21-30 days"]
    ]

    return {
        "kpis": {
            "total_open_matches": total_matches,
            "total_transferable_workers": total_workers,
            "customers_with_opportunity": len(enterprise_ids),
            "avg_gap_days": avg_gap,
        },
        "top_matches": [match_to_dict(m) for m in top_matches],
        "gap_histogram": gap_histogram,
    }


# ---------- Frontend ----------
# Local dev only (uvicorn app.main:app) - on Vercel, files under public/ are
# served directly by the platform and never hit this app at all.

app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
