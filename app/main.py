from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path
from itertools import zip_longest
from urllib.parse import urlencode
from datetime import datetime, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.cases import (
    EXCLUSION_REASONS,
    CaseFieldError,
    MixedMedicationBatchError,
    parse_actual_quantity,
    parse_lots,
)
from app.database import Database
from app.exporter import ExportError, export_cases, validate_case_for_export
from app.his import DateRangeError, DbfHisReader, HisReadError, HisReader
from app.logging_setup import configure_logging
from app.template import ReasonOption, TemplateCompatibilityError, load_reason_options


def create_app(
    *,
    settings: Settings | None = None,
    his_reader: HisReader | None = None,
    database: Database | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    reader = his_reader or DbfHisReader(settings.his_mirror_path)
    database = database or Database(settings.database_path)
    app = FastAPI(title="Clinic Antiviral Tool")
    templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))
    logger = configure_logging(settings.log_path)
    app.state.settings = settings
    app.state.his_reader = reader
    app.state.database = database

    static_path = settings.base_dir / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/doctor", status_code=303)

    @app.get("/doctor", response_class=HTMLResponse)
    def doctor_page(
        request: Request,
        action: str = "",
        doctor_id: str = "",
        mrn: str = "",
        success: str = "",
    ) -> HTMLResponse:
        prescription = None
        prescriptions = []
        reason_options: list[ReasonOption] = []
        existing_case = None
        error = None
        if action:
            try:
                if action == "recent":
                    prescription = reader.most_recent(doctor_id.strip()) if doctor_id.strip() else None
                elif action == "mrn":
                    prescriptions = reader.find_by_mrn(mrn.strip(), doctor_id.strip() or None)
                    prescription = prescriptions[0] if prescriptions else None
                else:
                    error = "Unknown doctor action. Error: HIS_READ_002"
                if action in {"recent", "mrn"} and prescription is None and error is None:
                    error = "No matching antiviral prescription was found. Error: HIS_READ_002"
                if prescription is not None and error is None:
                    reason_options = load_reason_options(settings.template_path)
                    existing_case = database.get_case_by_source_id(prescription.source_id)
            except HisReadError as exc:
                logger.warning("HIS read failed code=%s", exc.code)
                error = f"{exc.message} Error: {exc.code}"
            except TemplateCompatibilityError as exc:
                error = f"{exc.message} Error: {exc.code}"
            except Exception:
                logger.exception("Unexpected doctor lookup failure")
                error = "The prescription could not be loaded. Error: HIS_READ_001"
        return templates.TemplateResponse(
            request=request,
            name="doctor.html",
            context={
                "request": request,
                "doctor_id": doctor_id,
                "mrn": mrn,
                "action": action,
                "prescription": prescription,
                "prescriptions": prescriptions,
                "reason_options": reason_options,
                "existing_case": existing_case,
                "success": success,
                "error": error,
            },
        )

    @app.post("/doctor/save", response_class=HTMLResponse)
    def save_doctor_case(
        request: Request,
        source_id: str = Form(...),
        reason_code: str = Form(...),
        doctor_id: str = Form(""),
    ) -> HTMLResponse:
        prescription = None
        reason_options: list[ReasonOption] = []
        error = None
        try:
            prescription = reader.get(source_id.strip())
            if prescription is None:
                error = "The prescription is no longer available in HIS. Error: HIS_READ_002"
            else:
                reason_options = load_reason_options(settings.template_path)
                selected = next((option for option in reason_options if option.code == reason_code), None)
                if selected is None:
                    error = "Choose an official medication-use reason. Error: EXPORT_TEMPLATE_001"
                else:
                    database.save_doctor_reason(
                        prescription,
                        selected.code,
                        selected.label,
                        doctor_id.strip() or prescription.doctor_id,
                    )
                    return templates.TemplateResponse(
                        request=request,
                        name="doctor.html",
                        context={
                            "request": request,
                            "doctor_id": doctor_id,
                            "mrn": "",
                            "action": "",
                            "prescription": None,
                            "prescriptions": [],
                            "reason_options": [],
                            "existing_case": None,
                            "success": "已儲存用藥原因。",
                            "error": None,
                        },
                    )
        except HisReadError as exc:
            logger.warning("HIS read failed code=%s", exc.code)
            error = f"{exc.message} Error: {exc.code}"
        except TemplateCompatibilityError as exc:
            error = f"{exc.message} Error: {exc.code}"
        except Exception:
            logger.exception("Unexpected doctor save failure")
            error = "The case could not be saved. Error: DB_001"

        existing_case = database.get_case_by_source_id(source_id) if prescription else None
        return templates.TemplateResponse(
            request=request,
            name="doctor.html",
            context={
                "request": request,
                "doctor_id": doctor_id,
                "mrn": prescription.medical_record_number if prescription else "",
                "action": "",
                "prescription": prescription,
                "prescriptions": [],
                "reason_options": reason_options,
                "existing_case": existing_case,
                "selected_reason_code": reason_code,
                "success": "",
                "error": error,
            },
        )

    state_labels = {
        "missing_reason": "Missing reason",
        "missing_lot_quantity": "Missing lot/quantity",
        "ready_to_export": "Ready to export",
        "uploaded": "Uploaded",
        "confirmed": "Confirmed complete",
        "excluded": "Excluded",
    }

    def render_pharmacy(
        request: Request,
        *,
        error: str | None = None,
        message: str | None = None,
        view: str = "unfinished",
        report_date: str = "",
        state: str = "",
        doctor_id: str = "",
        medication_id: str = "",
        export_summary: dict[str, object] | None = None,
        download_url: str | None = None,
        batch_id: int | None = None,
    ) -> HTMLResponse:
        parsed_date = None
        if report_date:
            try:
                parsed_date = date.fromisoformat(report_date)
            except ValueError:
                error = "The selected date is invalid. Error: HIS_RANGE_002"
        try:
            reason_options = load_reason_options(settings.template_path)
        except TemplateCompatibilityError as exc:
            reason_options = []
            error = f"{exc.message} Error: {exc.code}"
        cases = database.list_cases(
            include_completed=view == "all",
            include_excluded=view in {"all", "excluded"},
            report_date=parsed_date,
            state=state or None,
            doctor_id=doctor_id.strip() or None,
            medication_id=medication_id.strip() or None,
        )
        return templates.TemplateResponse(
            request=request,
            name="pharmacy.html",
            context={
                "request": request,
                "cases": cases,
                "reason_options": reason_options,
                "state_labels": state_labels,
                "state": state,
                "view": view,
                "report_date": report_date,
                "doctor_id": doctor_id,
                "medication_id": medication_id,
                "exclusion_reasons": EXCLUSION_REASONS,
                "message": message,
                "success": message,
                "error": error,
                "export_summary": export_summary,
                "download_url": download_url,
                "batch_id": batch_id,
            },
        )

    @app.get("/pharmacy", response_class=HTMLResponse)
    def pharmacy_page(
        request: Request,
        view: str = "unfinished",
        report_date: str = "",
        state: str = "",
        doctor_id: str = "",
        medication_id: str = "",
        message: str = "",
        error: str = "",
    ) -> HTMLResponse:
        return render_pharmacy(
            request,
            error=error or None,
            message=message or None,
            view=view,
            report_date=report_date,
            state=state,
            doctor_id=doctor_id,
            medication_id=medication_id,
        )

    @app.post("/pharmacy/scan", response_class=HTMLResponse)
    def scan_pharmacy(
        request: Request,
        scan_mode: str = Form(...),
        scan_date: str = Form(""),
        start_date: str = Form(""),
        end_date: str = Form(""),
        operator: str = Form(""),
    ) -> HTMLResponse:
        try:
            if scan_mode == "today":
                start = end = date.today()
            elif scan_mode == "date":
                start = end = date.fromisoformat(scan_date)
            elif scan_mode == "range":
                start = date.fromisoformat(start_date)
                end = date.fromisoformat(end_date)
            else:
                raise DateRangeError()
            if settings.go_live_date and start < settings.go_live_date:
                raise HisReadError("HIS_RANGE_002", "The scan cannot include dates before go-live.")
            prescriptions = reader.scan(start, end)
            created = 0
            for prescription in prescriptions:
                if database.get_case_by_source_id(prescription.source_id) is None:
                    database.ensure_case(prescription)
                    created += 1
            query = urlencode({"message": f"Scanned {len(prescriptions)} prescriptions; created {created} cases."})
            return RedirectResponse(f"/pharmacy?{query}", status_code=303)
        except DateRangeError as exc:
            return render_pharmacy(request, error=f"{exc.message} Error: {exc.code}")
        except HisReadError as exc:
            logger.warning("HIS scan failed code=%s", exc.code)
            return render_pharmacy(request, error=f"{exc.message} Error: {exc.code}")
        except ValueError:
            return render_pharmacy(request, error="Enter a valid scan date or range. Error: HIS_RANGE_002")
        except Exception:
            logger.exception("Unexpected pharmacy scan failure")
            return render_pharmacy(request, error="The scan could not be completed. Error: HIS_READ_001")

    @app.post("/pharmacy/save", response_class=HTMLResponse)
    def save_pharmacy_case(
        request: Request,
        case_id: int = Form(...),
        reason_code: str = Form(""),
        actual_quantity: str = Form(""),
        lot_number: list[str] = Form(default=[]),
        lot_quantity: list[str] = Form(default=[]),
        operator: str = Form(""),
        confirm_edit: str = Form(""),
    ) -> HTMLResponse:
        try:
            current_case = database.get_case(case_id)
            if current_case is None:
                raise KeyError(case_id)
            selected_code = reason_code.strip() or None
            selected_label = None
            if selected_code:
                reason_options = load_reason_options(settings.template_path)
                selected = next((option for option in reason_options if option.code == selected_code), None)
                if selected is None:
                    raise CaseFieldError("Choose an official medication-use reason.")
                selected_label = selected.label
            quantity = parse_actual_quantity(actual_quantity)
            lots = parse_lots(zip_longest(lot_number, lot_quantity, fillvalue=""))
            if current_case.state == "confirmed" and confirm_edit != "yes":
                return templates.TemplateResponse(
                    request=request,
                    name="confirmed-warning.html",
                    context={
                        "request": request,
                        "case": current_case,
                        "reason_code": selected_code,
                        "reason_label": selected_label,
                        "actual_quantity": quantity,
                        "lots": lots,
                        "operator": operator,
                        "reason_options": load_reason_options(settings.template_path),
                        "error": None,
                        "success": None,
                    },
                )
            database.save_pharmacy_fields(
                case_id,
                reason_code=selected_code,
                reason_label=selected_label,
                actual_quantity=quantity,
                lots=lots,
                operator=operator.strip() or "pharmacy",
            )
            query = urlencode({"message": "Case saved."})
            return RedirectResponse(f"/pharmacy?{query}", status_code=303)
        except CaseFieldError as exc:
            return render_pharmacy(request, error=f"{exc.message} Error: {exc.code}")
        except TemplateCompatibilityError as exc:
            return render_pharmacy(request, error=f"{exc.message} Error: {exc.code}")
        except KeyError:
            return render_pharmacy(request, error="The case no longer exists. Error: DB_001")
        except Exception:
            logger.exception("Unexpected pharmacy save failure")
            return render_pharmacy(request, error="The case could not be saved. Error: DB_001")

    @app.post("/pharmacy/batch-lot", response_class=HTMLResponse)
    def batch_lot(
        request: Request,
        case_ids: list[int] = Form(default=[]),
        lot_number: str = Form(""),
        operator: str = Form(""),
    ) -> HTMLResponse:
        try:
            database.batch_assign_lot(
                case_ids,
                lot_number=lot_number,
                operator=operator.strip() or "pharmacy",
            )
            return RedirectResponse("/pharmacy?message=Batch+lot+applied.", status_code=303)
        except MixedMedicationBatchError as exc:
            return render_pharmacy(request, error=f"{exc.message} Error: {exc.code}")
        except CaseFieldError as exc:
            return render_pharmacy(request, error=f"{exc.message} Error: {exc.code}")
        except KeyError:
            return render_pharmacy(request, error="Choose existing cases before batch assignment. Error: DB_001")
        except Exception:
            logger.exception("Unexpected batch lot failure")
            return render_pharmacy(request, error="The batch lot action failed. Error: DB_001")

    @app.post("/pharmacy/export", response_class=HTMLResponse)
    async def export_pharmacy(request: Request) -> HTMLResponse:
        form = await request.form()
        try:
            selected_ids = [int(value) for value in form.getlist("export_case_ids")]
        except ValueError:
            return render_pharmacy(request, error="Choose valid cases for export. Error: EXPORT_002")
        operator = str(form.get("operator") or "pharmacy").strip() or "pharmacy"
        if not selected_ids:
            return render_pharmacy(request, error="Choose at least one case for export. Error: EXPORT_002")
        cases = [database.get_case(case_id) for case_id in selected_ids]
        if any(case is None for case in cases):
            return render_pharmacy(request, error="A selected case no longer exists. Error: DB_001")
        cases = [case for case in cases if case is not None]
        differences = []
        for case in cases:
            current = reader.get(case.source_id)
            changes = _his_changes(case, current)
            if changes:
                differences.append({"case": case, "current": current, "changes": changes})
        unresolved = []
        for difference in differences:
            decision = str(form.get(f"resolution_{difference['case'].id}") or "").strip()
            if decision not in {"latest", "keep", "exclude"}:
                unresolved.append(difference)
                continue
            if decision == "latest" and difference["current"] is None:
                unresolved.append(difference)
                continue
            try:
                database.resolve_his_difference(
                    difference["case"].id,
                    difference["current"],
                    decision=decision,
                    operator=operator,
                )
            except ValueError as error:
                return _render_his_differences(
                    request,
                    differences,
                    selected_ids,
                    operator,
                    error=str(error),
                )
        if unresolved:
            return _render_his_differences(request, unresolved, selected_ids, operator)

        refreshed_cases = [database.get_case(case_id) for case_id in selected_ids]
        refreshed_cases = [case for case in refreshed_cases if case is not None]
        valid_cases = []
        skipped = []
        for case in refreshed_cases:
            reasons = validate_case_for_export(case)
            if reasons:
                skipped.append({"case_id": case.id, "patient_name": case.patient_name, "reasons": reasons})
            else:
                valid_cases.append(case)
        if not valid_cases:
            return render_pharmacy(
                request,
                message="No valid cases were exported.",
                export_summary={
                    "selected": len(selected_ids),
                    "exported": 0,
                    "skipped": len(skipped),
                    "skips": skipped,
                },
            )
        filename = _new_export_filename(settings.app_data_path / "exports")
        output_path = settings.app_data_path / "exports" / filename
        try:
            exported = export_cases(settings.template_path, output_path, valid_cases)
            batch_id = database.create_export_batch(filename, operator, [case.id for case in valid_cases])
        except (TemplateCompatibilityError, ExportError) as exc:
            logger.exception("Excel export failed")
            return render_pharmacy(request, error=f"{exc} Error: {exc.code}")
        except Exception:
            logger.exception("Unexpected Excel export failure")
            output_path.unlink(missing_ok=True)
            return render_pharmacy(request, error="The Excel export failed. Error: EXPORT_002")
        return render_pharmacy(
            request,
            message=f"Exported {len(valid_cases)} cases; skipped {len(skipped)}.",
            export_summary={
                "selected": len(selected_ids),
                "exported": len(valid_cases),
                "skipped": len(skipped),
                "skips": skipped,
            },
            download_url=f"/pharmacy/export/{batch_id}/download",
            batch_id=batch_id,
        )

    @app.get("/pharmacy/export/{batch_id}/download")
    def download_export(batch_id: int) -> Response:
        batch = database.get_export_batch(batch_id)
        if not batch:
            return HTMLResponse("The export batch was not found. Error: EXPORT_002", status_code=404)
        path = settings.app_data_path / "exports" / str(batch["filename"])
        if not path.exists():
            return HTMLResponse("The generated workbook is missing. Error: EXPORT_002", status_code=404)
        return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/pharmacy/batch/{batch_id}/uploaded", response_class=HTMLResponse)
    def mark_uploaded(request: Request, batch_id: int) -> HTMLResponse:
        batch = database.get_export_batch(batch_id)
        if not batch:
            return render_pharmacy(request, error="The export batch was not found. Error: DB_001")
        source_path = settings.app_data_path / "exports" / str(batch["filename"])
        if not source_path.exists():
            return render_pharmacy(request, error="The generated workbook is missing. Error: EXPORT_002")
        try:
            if batch["uploaded"]:
                return render_pharmacy(request, message="Batch is already marked uploaded.")
            destination = _uploaded_destination(settings.uploaded_path, source_path.name)
            shutil.copy2(source_path, destination)
            database.mark_batch_uploaded(batch_id, str(destination))
            return render_pharmacy(request, message="Batch marked uploaded; workbook preserved.")
        except Exception:
            logger.exception("Upload preservation failed batch_id=%s", batch_id)
            return render_pharmacy(request, error="The uploaded workbook could not be preserved. Error: EXPORT_002")

    @app.post("/pharmacy/confirm", response_class=HTMLResponse)
    def confirm_cases(request: Request, confirm_case_ids: list[int] = Form(default=[])) -> HTMLResponse:
        try:
            database.confirm_cases(confirm_case_ids)
            return RedirectResponse("/pharmacy?message=Cases+marked+confirmed.", status_code=303)
        except KeyError:
            return render_pharmacy(request, error="Choose existing cases to confirm. Error: DB_001")
        except ValueError as error:
            return render_pharmacy(request, error=f"{error} Error: CASE_STATE_001")

    @app.post("/pharmacy/exclude", response_class=HTMLResponse)
    def exclude_pharmacy_case(
        request: Request,
        case_id: int = Form(...),
        reason: str = Form(...),
        other_reason: str = Form(""),
    ) -> HTMLResponse:
        label = EXCLUSION_REASONS.get(reason)
        if label is None:
            return render_pharmacy(request, error="Choose a valid exclusion reason. Error: CASE_FIELD_001")
        if reason == "other":
            if not other_reason.strip():
                return render_pharmacy(request, error="Enter a short reason for Other. Error: CASE_FIELD_001")
            label = f"Other: {other_reason.strip()}"
        try:
            database.exclude_case(case_id, label)
            return RedirectResponse("/pharmacy?message=Case+excluded.", status_code=303)
        except KeyError:
            return render_pharmacy(request, error="The case no longer exists. Error: DB_001")

    @app.post("/pharmacy/reinclude", response_class=HTMLResponse)
    def reinclude_pharmacy_case(request: Request, case_id: int = Form(...)) -> HTMLResponse:
        try:
            database.reinclude_case(case_id)
            return RedirectResponse("/pharmacy?message=Case+included+again.", status_code=303)
        except KeyError:
            return render_pharmacy(request, error="The case no longer exists. Error: DB_001")

    @app.get("/pharmacy/history/{case_id}", response_class=HTMLResponse)
    def pharmacy_history(request: Request, case_id: int) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="history.html",
            context={"request": request, "case_id": case_id, "history": database.list_history(case_id)},
        )

    def _render_his_differences(
        request: Request,
        differences: list[dict[str, object]],
        selected_ids: list[int],
        operator: str,
        error: str | None = None,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="hisdiff.html",
            context={
                "request": request,
                "differences": differences,
                "selected_ids": selected_ids,
                "operator": operator,
                "error": error,
                "success": None,
            },
        )

    return app


def _his_changes(case, current) -> list[dict[str, str]]:
    if current is None:
        return [{"field": "HIS order", "before": "saved case", "after": "not found"}]
    names = [
        "medical record number",
        "patient name",
        "patient ID",
        "birth date",
        "sex",
        "report date",
        "doctor ID",
        "medication",
        "official material",
        "source quantity",
        "treat",
    ]
    changes = []
    for name, before, after in zip(names, case.source_fingerprint, current.reporting_fingerprint):
        if before != after:
            changes.append({"field": name, "before": str(before), "after": str(after)})
    return changes


def _new_export_filename(export_directory: Path) -> str:
    export_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"smis-report-{stamp}.xlsx"


def _uploaded_destination(uploaded_directory: Path, filename: str) -> Path:
    month_directory = uploaded_directory / datetime.now().strftime("%Y") / datetime.now().strftime("%m")
    month_directory.mkdir(parents=True, exist_ok=True)
    destination = month_directory / filename
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    counter = 1
    while True:
        candidate = month_directory / f"{stem}-copy-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


app = create_app()
