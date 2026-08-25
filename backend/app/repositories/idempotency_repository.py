"""Persistence adapter for durable governed-command idempotency receipts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandReceiptStatus,
    CommandResultReference,
)
from app.models.governance import GovernedCommandReceipt


class IdempotencyRepository:
    """Add, inspect, and complete receipts in a caller-owned transaction."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_identity(
        self,
        identity: CommandIdentity,
    ) -> GovernedCommandReceipt | None:
        return self.session.scalar(
            select(GovernedCommandReceipt).where(
                GovernedCommandReceipt.command_namespace
                == identity.command_namespace,
                GovernedCommandReceipt.command_scope == identity.command_scope,
                GovernedCommandReceipt.idempotency_key == identity.idempotency_key,
            )
        )

    def add_reserved(
        self,
        *,
        receipt_id: str,
        identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        correlation_id: str,
        schema_version: str,
        software_version: str,
        created_at: datetime,
    ) -> GovernedCommandReceipt:
        receipt = GovernedCommandReceipt(
            receipt_id=receipt_id,
            command_namespace=identity.command_namespace,
            command_scope=identity.command_scope,
            idempotency_key=identity.idempotency_key,
            request_hash=request_hash.value,
            status=CommandReceiptStatus.RESERVED,
            result_type=None,
            result_id=None,
            result_revision=None,
            correlation_id=correlation_id,
            schema_version=schema_version,
            software_version=software_version,
            canonicalization_version=request_hash.canonicalization_version,
            hash_algorithm=request_hash.hash_algorithm,
            created_at=created_at,
            completed_at=None,
        )
        self.session.add(receipt)
        self.session.flush()
        return receipt

    def complete(
        self,
        receipt: GovernedCommandReceipt,
        *,
        result_reference: CommandResultReference,
        completed_at: datetime,
    ) -> GovernedCommandReceipt:
        if receipt not in self.session:
            raise ValueError("idempotency receipt must belong to this repository session")
        if receipt.status != CommandReceiptStatus.RESERVED:
            raise ValueError("only a RESERVED idempotency receipt can be completed")
        receipt.status = CommandReceiptStatus.COMPLETED
        receipt.result_type = result_reference.result_type
        receipt.result_id = result_reference.result_id
        receipt.result_revision = result_reference.result_revision
        receipt.completed_at = completed_at
        self.session.flush()
        return receipt
