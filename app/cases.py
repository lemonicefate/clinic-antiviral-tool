from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MISSING_REASON = "missing_reason"
MISSING_LOT_QUANTITY = "missing_lot_quantity"
READY_TO_EXPORT = "ready_to_export"
UPLOADED = "uploaded"
CONFIRMED = "confirmed"
EXCLUDED = "excluded"

EXCLUSION_REASONS = {
    "patient_not_collected": "Patient did not collect medication",
    "cancelled": "Prescription cancelled",
    "duplicate": "Duplicate data",
    "other": "Other",
}


@dataclass(frozen=True)
class LotAllocation:
    lot_number: str
    quantity: int


class CaseFieldError(ValueError):
    code = "CASE_FIELD_001"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def parse_actual_quantity(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        quantity = int(text)
    except (TypeError, ValueError) as error:
        raise CaseFieldError("Actual quantity must be a whole number.") from error
    if quantity <= 0:
        raise CaseFieldError("Actual quantity must be greater than zero.")
    return quantity


def parse_lots(values: Iterable[tuple[object, object]]) -> tuple[LotAllocation, ...]:
    allocations: list[LotAllocation] = []
    for raw_lot, raw_quantity in values:
        lot = str(raw_lot or "").strip()
        quantity_text = str(raw_quantity or "").strip()
        if not lot and not quantity_text:
            continue
        if not lot:
            raise CaseFieldError("Every lot quantity needs a lot number.")
        if not quantity_text:
            raise CaseFieldError("Every lot number needs a quantity.")
        try:
            quantity = int(quantity_text)
        except ValueError as error:
            raise CaseFieldError("Lot quantities must be whole numbers.") from error
        if quantity <= 0:
            raise CaseFieldError("Lot quantities must be greater than zero.")
        allocations.append(LotAllocation(lot_number=lot, quantity=quantity))
    return tuple(allocations)


def derive_state(
    *,
    reason_code: str | None,
    actual_quantity: int | None,
    lots: Iterable[LotAllocation],
    previous_state: str | None = None,
) -> str:
    if previous_state == EXCLUDED:
        return EXCLUDED
    if not reason_code:
        return MISSING_REASON
    allocations = tuple(lots)
    if actual_quantity is None or not allocations or sum(item.quantity for item in allocations) != actual_quantity:
        return MISSING_LOT_QUANTITY
    return READY_TO_EXPORT


def lots_display(lots: Iterable[LotAllocation]) -> str:
    return ", ".join(f"{item.lot_number} ({item.quantity})" for item in lots)
