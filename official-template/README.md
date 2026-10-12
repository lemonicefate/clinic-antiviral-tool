# Official SMIS template

Place the current official SMIS Excel template here as `smis_report.xlsx`, or set `SMIS_TEMPLATE_PATH` in `.env` to the supplied template location.

The workbook is deployment input and is ignored by Git. Do not commit a workbook containing clinic or patient data. The application reads medication-use reasons from its code table and fails clearly if the workbook structure is incompatible.

The supplied SMIS workbook uses a `住院病患` report sheet and a `代碼表` sheet. Medication-use reasons are the complete dropdown values in the code table's `用藥對象` column. Preserve the complete value, including any subcondition; the leading numeric code alone is not unique.

The reason dropdown supports this format. The export writer still requires its existing column layout and rejects this supplied report layout. Complete the verified report-field mapping before enabling export; the current case model does not contain continuation-of-course or foreign-national flags.
