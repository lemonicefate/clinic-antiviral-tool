# Official SMIS template

Place the current official SMIS Excel template here as `smis_report.xlsx`, or set `SMIS_TEMPLATE_PATH` in `.env` to the supplied template location.

The workbook is deployment input and is ignored by Git. Do not commit a workbook containing clinic or patient data. The application reads medication-use reasons from its code table and fails clearly if the workbook structure is incompatible.
