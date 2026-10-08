from dataclasses import dataclass


@dataclass(frozen=True)
class MedicationMapping:
    id: str
    his_medication_id: str
    his_inventory_item: str
    his_lab_number: str
    official_material: str
    display_name: str
    unit: str
    source_quantity_field: str
    report_date_table: str

    def matches(self, *, med1: object = "", itemn: object = "", labnum: object = "") -> bool:
        values = {_normalise(med1), _normalise(itemn), _normalise(labnum)}
        return bool(
            values
            & {
                _normalise(self.his_medication_id),
                _normalise(self.his_inventory_item),
                _normalise(self.his_lab_number),
            }
        )


PUBLIC_ANTIVIRALS = (
    MedicationMapping(
        id="eraflu",
        his_medication_id="ERA",
        his_inventory_item="ERA",
        his_lab_number="A059653100",
        official_material="DDMTR2018090002:易剋冒膠囊(顆)",
        display_name="易剋冒膠囊",
        unit="capsule",
        source_quantity_field="USE_TAMT",
        report_date_table="CH011M1",
    ),
)


def get_medication_mapping(mapping_id: str) -> MedicationMapping:
    for mapping in PUBLIC_ANTIVIRALS:
        if mapping.id == mapping_id:
            return mapping
    raise KeyError(f"Unknown public antiviral mapping: {mapping_id}")


def find_medication_mapping(*, med1: object = "", itemn: object = "", labnum: object = "") -> MedicationMapping | None:
    for mapping in PUBLIC_ANTIVIRALS:
        if mapping.matches(med1=med1, itemn=itemn, labnum=labnum):
            return mapping
    return None


def _normalise(value: object) -> str:
    return str(value or "").strip().upper()
