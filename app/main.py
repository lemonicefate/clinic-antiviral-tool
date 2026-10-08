from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.database import Database
from app.his import DbfHisReader, HisReadError, HisReader
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
    logger = logging.getLogger("clinic_antiviral")
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

    return app


app = create_app()
