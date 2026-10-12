# Clinic antiviral reporting tool

Small LAN utility for recording publicly funded influenza antiviral use and producing the official SMIS Excel for manual upload.

## Install

On the central Windows clinic machine, install Python 3.12, create the virtual environment, and install dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with paths for the disposable HIS mirror, SQLite runtime data, preserved uploaded workbooks, and the current official SMIS template. Keep `.env` and all HIS DBF/FPT/CDX files outside Git.

`HIS_MIRROR_PATH` must point to a read-only development mirror. Production HIS files must be read-only at the OS/share level; this application never writes them.

## Run and update

Run `scripts\start.bat` and open the displayed service on the clinic LAN. `scripts\stop.bat` stops the matching uvicorn process. `scripts\update.bat` fast-forwards the checkout and refreshes the Python dependencies without changing `.env`.

The two pages are:

- `http://<clinic-machine>:8000/doctor` for the doctor reason workflow.
- `http://<clinic-machine>:8000/pharmacy` for scanning, completion, export, upload tracking, and confirmation.

Runtime SQLite data and logs use `APP_DATA_PATH`; generated exports use its `exports` subdirectory. Preserved uploaded workbooks use `UPLOADED_PATH\YYYY\MM`. The default example paths are under `C:\clinic-data\` and should be adjusted for the clinic machine.

## Manual smoke tests

Manual checks are limited to the real boundaries:

1. With the read-only HIS mirror, verify recent prescription, MRN search, and a date scan against the expected HIS records.
2. Verify that the doctor page is quick and that the pharmacy table is usable for normal daily work.
3. Generate the official workbook with the real template and verify that SMIS accepts the manually uploaded file.
