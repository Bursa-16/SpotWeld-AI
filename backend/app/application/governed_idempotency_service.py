"""Thin application orchestration for durable governed-command idempotency."""

from __future__ import annotations

from datetime import datetime

from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandReceiptStatus,
    CommandResultReference,
    IdempotencyDecision,
    IdempotencyDisposition,
)
from app.models.governance import GovernedCommandReceipt


class GovernedIdempotencyService:
    """Reserve, inspect, and complete receipts inside the caller's UoW."""

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = unit_of_work.idempotency_repository

    def reserve_or_inspect(
        self,
        *,
        receipt_id: str,
        identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        correlation_id: str,
        schema_version: str,
        software_version: str,
        created_at: datetime,
    ) -> IdempotencyDecision:
        self._unit_of_work.ensure_open()
        existing = self._repository.get_by_identity(identity)
        if existing is not None:
            return self._inspect(existing, request_hash)

        receipt = self._repository.add_reserved(
            receipt_id=receipt_id,
            identity=identity,
            request_hash=request_hash,
            correlation_id=correlation_id,
            schema_version=schema_version,
            software_version=software_version,
            created_at=created_at,
        )
        return IdempotencyDecision(
            disposition=IdempotencyDisposition.NEW,
            receipt_id=receipt.receipt_id,
            status=receipt.status,
        )

    def complete(
        self,
        *,
        identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        result_reference: CommandResultReference,
        completed_at: datetime,
    ) -> IdempotencyDecision:
        self._unit_of_work.ensure_open()
        receipt = self._repository.get_by_identity(identity)
        if receipt is None:
            raise ValueError("cannot complete an idempotency receipt that does not exist")
        inspected = self._inspect(receipt, request_hash)
        if inspected.disposition == IdempotencyDisposition.CONFLICT:
            return inspected
        if receipt.status == CommandReceiptStatus.COMPLETED:
            if inspected.result_reference != result_reference:
                return IdempotencyDecision(
                    disposition=IdempotencyDisposition.CONFLICT,
                    receipt_id=receipt.receipt_id,
                    status=receipt.status,
                    result_reference=inspected.result_reference,
                )
            return inspected

        completed = self._repository.complete(
            receipt,
            result_reference=result_reference,
            completed_at=completed_at,
        )
        return IdempotencyDecision(
            disposition=IdempotencyDisposition.COMPLETED,
            receipt_id=completed.receipt_id,
            status=completed.status,
            result_reference=result_reference,
        )

    @staticmethod
    def _inspect(
        receipt: GovernedCommandReceipt,
        request_hash: CanonicalRequestHash,
    ) -> IdempotencyDecision:
        same_request = (
            receipt.request_hash == request_hash.value
            and receipt.hash_algorithm == request_hash.hash_algorithm
            and receipt.canonicalization_version
            == request_hash.canonicalization_version
        )
        if not same_request:
            return IdempotencyDecision(
                disposition=IdempotencyDisposition.CONFLICT,
                receipt_id=receipt.receipt_id,
                status=receipt.status,
            )
        if receipt.status == CommandReceiptStatus.COMPLETED:
            return IdempotencyDecision(
                disposition=IdempotencyDisposition.REPLAY,
                receipt_id=receipt.receipt_id,
                status=receipt.status,
                result_reference=CommandResultReference(
                    result_type=receipt.result_type,
                    result_id=receipt.result_id,
                    result_revision=receipt.result_revision,
                ),
            )
        return IdempotencyDecision(
            disposition=IdempotencyDisposition.IN_PROGRESS,
            receipt_id=receipt.receipt_id,
            status=receipt.status,
        )
