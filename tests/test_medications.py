from app.medications import PUBLIC_ANTIVIRALS, get_medication_mapping


def test_verified_eraflu_mapping_matches_known_his_and_smis_values():
    mapping = get_medication_mapping("eraflu")

    assert mapping.his_medication_id == "ERA"
    assert mapping.his_inventory_item == "ERA"
    assert mapping.his_lab_number == "A059653100"
    assert mapping.official_material == "DDMTR2018090002:易剋冒膠囊(顆)"
    assert mapping.source_quantity_field == "USE_TAMT"
    assert mapping.report_date_table == "CH011M1"


def test_only_configured_public_antivirals_are_available():
    assert [mapping.id for mapping in PUBLIC_ANTIVIRALS] == ["eraflu"]
