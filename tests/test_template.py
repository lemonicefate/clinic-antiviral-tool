from openpyxl import Workbook

import pytest

from app.template import ReasonOption, TemplateCompatibilityError, load_reason_options


def write_reason_template(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "OfficialCodes"
    sheet.append(["ReasonCode", "ReasonName"])
    sheet.append(["R01", "符合公費使用條件"])
    sheet.append(["R02", "其他正式條件"])
    workbook.save(path)


def test_reason_options_are_read_from_workbook_code_table(tmp_path):
    path = tmp_path / "smis_report.xlsx"
    write_reason_template(path)

    assert load_reason_options(path) == [
        ReasonOption(code="R01", label="符合公費使用條件"),
        ReasonOption(code="R02", label="其他正式條件"),
    ]


def test_incompatible_template_fails_with_stable_code(tmp_path):
    path = tmp_path / "wrong.xlsx"
    workbook = Workbook()
    workbook.active.append(["wrong", "columns"])
    workbook.save(path)

    with pytest.raises(TemplateCompatibilityError) as error:
        load_reason_options(path)

    assert error.value.code == "EXPORT_TEMPLATE_001"
