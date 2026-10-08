from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.his import DbfHisReader, HisReadError, HisReader


def create_app(*, settings: Settings | None = None, his_reader: HisReader | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    reader = his_reader or DbfHisReader(settings.his_mirror_path)
    app = FastAPI(title="Clinic Antiviral Tool")
    templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))
    logger = logging.getLogger("clinic_antiviral")
    app.state.settings = settings
    app.state.his_reader = reader

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
    ) -> HTMLResponse:
        prescription = None
        prescriptions = []
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
            except HisReadError as exc:
                logger.warning("HIS read failed code=%s", exc.code)
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
                "error": error,
            },
        )

    return app


app = create_app()
