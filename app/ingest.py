"""Parses the DOL H-2A disclosure xlsx and the Seso active-customers CSV into the DB.

Uses bulk_insert_mappings/bulk_update_mappings throughout instead of one
query+write per row - with 17k+ disclosure rows, per-row round trips are fine
against a local SQLite file but far too slow against a networked Postgres
(each round trip pays real network latency), so bulk operations keep uploads
well within a serverless function's execution time limit.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

import openpyxl
from sqlalchemy.orm import Session

from . import models
from .matching_entities import normalize_name, best_match, classify

def _clean_str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


VALID_CASE_STATUSES = {
    "Determination Issued - Certification",
    "Determination Issued - Certification (Expired)",
    "Determination Issued - Partial Certification",
    "Determination Issued - Partial Certification (Expired)",
}


def ingest_disclosure_xlsx(db: Session, file_bytes: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.worksheets[0]

    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    idx = {h: i for i, h in enumerate(header)}

    required = [
        "CASE_NUMBER", "CASE_STATUS", "EMPLOYER_NAME", "TRADE_NAME_DBA", "EMPLOYER_FEIN",
        "JOB_TITLE", "TOTAL_WORKERS_H2A_CERTIFIED", "TOTAL_WORKERS_H2A_REQUESTED",
        "EMPLOYMENT_BEGIN_DATE", "EMPLOYMENT_END_DATE", "WORKSITE_CITY", "WORKSITE_STATE",
    ]
    missing = [c for c in required if c not in idx]
    if missing:
        raise ValueError(f"Disclosure file is missing expected columns: {missing}")

    skipped_status = skipped_bad_row = skipped_duplicate = 0
    parsed: dict[str, dict] = {}

    for row in rows:
        case_number = row[idx["CASE_NUMBER"]]
        if not case_number:
            skipped_bad_row += 1
            continue

        status = row[idx["CASE_STATUS"]]
        if status not in VALID_CASE_STATUSES:
            skipped_status += 1
            continue

        start = row[idx["EMPLOYMENT_BEGIN_DATE"]]
        end = row[idx["EMPLOYMENT_END_DATE"]]
        if not start or not end:
            skipped_bad_row += 1
            continue
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        certified = row[idx["TOTAL_WORKERS_H2A_CERTIFIED"]] or 0
        requested = row[idx["TOTAL_WORKERS_H2A_REQUESTED"]] or 0
        if certified and certified > 0:
            worker_count, source = int(certified), "certified"
        else:
            worker_count, source = int(requested), "requested"

        employer_name = _clean_str(row[idx["EMPLOYER_NAME"]]) or ""

        anticipated_hours = None
        if "ANTICIPATED_NUMBER_OF_HOURS" in idx:
            raw_hours = row[idx["ANTICIPATED_NUMBER_OF_HOURS"]]
            try:
                anticipated_hours = int(raw_hours) if raw_hours not in (None, "") else None
            except (TypeError, ValueError):
                anticipated_hours = None

        wage_offer = None
        if "WAGE_OFFER" in idx:
            raw_wage = row[idx["WAGE_OFFER"]]
            try:
                wage_offer = float(raw_wage) if raw_wage not in (None, "") else None
            except (TypeError, ValueError):
                wage_offer = None
        wage_offer_unit = _clean_str(row[idx["PER"]]) if "PER" in idx else None

        if case_number in parsed:
            skipped_duplicate += 1
            continue
        parsed[case_number] = {
            "case_number": case_number,
            "case_status": status,
            "employer_name": employer_name,
            "trade_name_dba": _clean_str(row[idx["TRADE_NAME_DBA"]]),
            "normalized_employer_name": normalize_name(employer_name),
            "fein": _clean_str(row[idx["EMPLOYER_FEIN"]]),
            "job_title": _clean_str(row[idx["JOB_TITLE"]]),
            "worker_count": worker_count,
            "worker_count_source": source,
            "anticipated_hours": anticipated_hours,
            "wage_offer": wage_offer,
            "wage_offer_unit": wage_offer_unit,
            "contract_start": start_date,
            "contract_end": end_date,
            "worksite_city": _clean_str(row[idx["WORKSITE_CITY"]]),
            "worksite_state": _clean_str(row[idx["WORKSITE_STATE"]]),
        }

    existing_ids = {
        case_number: pk
        for case_number, pk in db.query(models.Contract.case_number, models.Contract.id)
        .filter(models.Contract.case_number.in_(parsed.keys()))
        .all()
    }

    to_insert = []
    to_update = []
    for case_number, fields in parsed.items():
        if case_number in existing_ids:
            to_update.append({**fields, "id": existing_ids[case_number]})
        else:
            to_insert.append({**fields, "match_status": "prospect"})

    if to_insert:
        db.bulk_insert_mappings(models.Contract, to_insert)
    if to_update:
        db.bulk_update_mappings(models.Contract, to_update)
    db.commit()

    return {
        "inserted": len(to_insert),
        "updated": len(to_update),
        "skipped_invalid_status": skipped_status,
        "skipped_missing_data": skipped_bad_row,
        "skipped_duplicate_rows": skipped_duplicate,
    }


def ingest_customers_csv(db: Session, file_bytes: bytes) -> dict:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    required = {"Enterprise Account Name", "Entity ID", "Entity Name"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError(f"Customer CSV must have columns: {required}")

    enterprise_by_name: dict[str, models.Enterprise] = {
        e.name: e for e in db.query(models.Enterprise).all()
    }
    existing_alias_pks = {
        entity_id: pk
        for entity_id, pk in db.query(models.EntityAlias.entity_id, models.EntityAlias.id).all()
    }

    enterprises_created = 0
    to_insert = []
    to_update = []
    seen_entity_ids = set()

    for row in reader:
        enterprise_name = (row["Enterprise Account Name"] or "").strip()
        entity_id_raw = row["Entity ID"]
        entity_name = (row["Entity Name"] or "").strip()
        if not enterprise_name or not entity_id_raw:
            continue
        entity_id = int(entity_id_raw)
        if entity_id in seen_entity_ids:
            continue
        seen_entity_ids.add(entity_id)

        enterprise = enterprise_by_name.get(enterprise_name)
        if enterprise is None:
            enterprise = models.Enterprise(name=enterprise_name)
            db.add(enterprise)
            db.flush()
            enterprise_by_name[enterprise_name] = enterprise
            enterprises_created += 1

        normalized = normalize_name(entity_name)
        if entity_id in existing_alias_pks:
            to_update.append({
                "id": existing_alias_pks[entity_id],
                "enterprise_id": enterprise.id,
                "entity_name": entity_name,
                "normalized_name": normalized,
            })
        else:
            to_insert.append({
                "enterprise_id": enterprise.id,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "normalized_name": normalized,
            })

    if to_insert:
        db.bulk_insert_mappings(models.EntityAlias, to_insert)
    if to_update:
        db.bulk_update_mappings(models.EntityAlias, to_update)
    db.commit()

    return {
        "enterprises_created": enterprises_created,
        "aliases_created": len(to_insert),
        "aliases_updated": len(to_update),
    }


def add_manual_alias(db: Session, enterprise_id: int, alias_name: str) -> models.ManualAlias:
    """Teach the matcher that alias_name is this enterprise, regardless of how far
    apart the fuzzy score put them. Re-pointing an existing alias to a different
    enterprise is allowed (upsert on normalized_name) rather than erroring."""
    normalized = normalize_name(alias_name)
    existing = db.query(models.ManualAlias).filter_by(normalized_name=normalized).one_or_none()
    if existing:
        existing.enterprise_id = enterprise_id
        existing.alias_name = alias_name
        db.commit()
        return existing
    alias = models.ManualAlias(enterprise_id=enterprise_id, alias_name=alias_name, normalized_name=normalized)
    db.add(alias)
    db.commit()
    return alias


def rematch_all_contracts(db: Session) -> dict:
    """Re-runs entity resolution for every contract that hasn't been manually
    reviewed yet. Safe to call repeatedly after new uploads."""

    candidates: list[tuple[str, int]] = []
    for alias in db.query(models.EntityAlias).all():
        candidates.append((alias.normalized_name, alias.enterprise_id))
    for ent in db.query(models.Enterprise).all():
        candidates.append((normalize_name(ent.name), ent.id))
    for alias in db.query(models.ManualAlias).all():
        candidates.append((alias.normalized_name, alias.enterprise_id))

    auto = review = prospect = 0
    updates: list[dict] = []

    contracts = (
        db.query(models.Contract.id, models.Contract.normalized_employer_name, models.Contract.trade_name_dba)
        .filter(models.Contract.match_status.notin_(["manual", "rejected"]))
        .all()
    )

    for contract_id, normalized_employer_name, trade_name_dba in contracts:
        norm_options = [n for n in {normalized_employer_name, normalize_name(trade_name_dba or "")} if n]
        best = None
        for norm in norm_options:
            m = best_match(norm, candidates)
            if m and (best is None or m[1] > best[1]):
                best = m

        if best is None:
            updates.append({
                "id": contract_id, "candidate_enterprise_id": None,
                "match_confidence": None, "enterprise_id": None, "match_status": "prospect",
            })
            prospect += 1
            continue

        cand_id, score = best
        status = classify(score)
        if status == "auto":
            updates.append({
                "id": contract_id, "enterprise_id": cand_id, "candidate_enterprise_id": cand_id,
                "match_confidence": score, "match_status": "auto",
            })
            auto += 1
        elif status == "review":
            updates.append({
                "id": contract_id, "enterprise_id": None, "candidate_enterprise_id": cand_id,
                "match_confidence": score, "match_status": "review",
            })
            review += 1
        else:
            updates.append({
                "id": contract_id, "enterprise_id": None, "candidate_enterprise_id": None,
                "match_confidence": score, "match_status": "prospect",
            })
            prospect += 1

    if updates:
        db.bulk_update_mappings(models.Contract, updates)
    db.commit()
    return {"auto": auto, "review": review, "prospect": prospect}
