from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class Enterprise(Base):
    """A Seso customer, as rolled up from the active_customers_enterprises.csv."""

    __tablename__ = "enterprises"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    aliases = relationship("EntityAlias", back_populates="enterprise", cascade="all, delete-orphan")
    contracts = relationship("Contract", back_populates="enterprise", foreign_keys="Contract.enterprise_id")


class EntityAlias(Base):
    """One legal entity belonging to an Enterprise (customers can have multiple entities)."""

    __tablename__ = "entity_aliases"

    id = Column(Integer, primary_key=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    entity_id = Column(Integer, unique=True, nullable=False)  # Entity ID from the CSV
    entity_name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, index=True)

    enterprise = relationship("Enterprise", back_populates="aliases")


class ManualAlias(Base):
    """A user-taught 'this disclosure name is actually this customer' mapping, for
    cases where the fuzzy matcher scored two names too far apart to auto-link or
    even queue for review (e.g. 'Araona Labor' vs 'ARAONA Labor Logistics, LLC').
    Kept separate from EntityAlias (CSV-sourced) so a customer-list re-upload can
    never silently overwrite or collide with something a human corrected."""

    __tablename__ = "manual_aliases"

    id = Column(Integer, primary_key=True)
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=False)
    alias_name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    enterprise = relationship("Enterprise")

    __table_args__ = (UniqueConstraint("normalized_name", name="uq_manual_alias_normalized"),)


class Contract(Base):
    """One job-order record from the H-2A disclosure data (one worksite/job per row)."""

    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True)
    case_number = Column(String, unique=True, nullable=False, index=True)
    case_status = Column(String)

    employer_name = Column(String, nullable=False)
    trade_name_dba = Column(String)
    normalized_employer_name = Column(String, index=True)
    fein = Column(String, index=True)

    job_title = Column(String)
    worker_count = Column(Integer, nullable=False)
    worker_count_source = Column(String)  # "certified" or "requested"
    anticipated_hours = Column(Integer, nullable=True)  # ANTICIPATED_NUMBER_OF_HOURS
    wage_offer = Column(Float, nullable=True)
    wage_offer_unit = Column(String, nullable=True)  # e.g. "Hour"

    contract_start = Column(Date, nullable=False, index=True)
    contract_end = Column(Date, nullable=False, index=True)

    worksite_city = Column(String)
    worksite_state = Column(String)

    # Entity resolution against the Seso customer list.
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=True, index=True)
    candidate_enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=True)
    match_confidence = Column(Float, nullable=True)
    match_status = Column(String, default="prospect", index=True)
    # match_status one of: "auto" (confirmed customer match), "review" (pending),
    # "prospect" (no confident match), "manual" (human-confirmed via review queue)

    created_at = Column(DateTime, default=datetime.utcnow)

    enterprise = relationship("Enterprise", foreign_keys=[enterprise_id], back_populates="contracts")
    candidate_enterprise = relationship("Enterprise", foreign_keys=[candidate_enterprise_id])

    __table_args__ = (UniqueConstraint("case_number", name="uq_contract_case_number"),)


class DismissedMatch(Base):
    """A specific (ending contract -> starting contract) pairing a user has hidden
    from the dashboard match lists. Restorable individually or in bulk."""

    __tablename__ = "dismissed_matches"

    id = Column(Integer, primary_key=True)
    from_contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    to_contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    dismissed_at = Column(DateTime, default=datetime.utcnow)

    from_contract = relationship("Contract", foreign_keys=[from_contract_id])
    to_contract = relationship("Contract", foreign_keys=[to_contract_id])

    __table_args__ = (UniqueConstraint("from_contract_id", "to_contract_id", name="uq_dismissed_pair"),)
