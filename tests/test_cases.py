import pytest

from app.cases import (
    MISSING_LOT_QUANTITY,
    MISSING_REASON,
    READY_TO_EXPORT,
    CaseFieldError,
    LotAllocation,
    derive_state,
    parse_actual_quantity,
    parse_lots,
)


def test_quantity_and_lot_values_are_validated_without_requiring_complete_case():
    assert parse_actual_quantity(10) == 10
    assert parse_actual_quantity("") is None
    assert parse_lots([("LOT-A", "6")]) == (LotAllocation("LOT-A", 6),)

    with pytest.raises(CaseFieldError, match="whole number"):
        parse_actual_quantity("zero")
    with pytest.raises(CaseFieldError, match="needs a quantity"):
        parse_lots([("LOT-A", "")])


def test_state_derivation_distinguishes_missing_reason_lots_and_ready_case():
    assert derive_state(reason_code=None, actual_quantity=10, lots=()) == MISSING_REASON
    assert derive_state(reason_code="R01", actual_quantity=10, lots=()) == MISSING_LOT_QUANTITY
    assert derive_state(
        reason_code="R01",
        actual_quantity=10,
        lots=(LotAllocation("LOT-A", 10),),
    ) == READY_TO_EXPORT
