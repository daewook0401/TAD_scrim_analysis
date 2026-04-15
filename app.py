from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from models import AnalyzeRequest
from service import analyze_from_request, analyze_local_file


app = FastAPI(title="TAD Scrim Analysis")


def _run_analysis(request: AnalyzeRequest) -> JSONResponse:
    result = analyze_from_request(
        image_url=request.image_url,
        image_path=request.image_path,
        bucket=request.bucket,
        object_key=request.object_key,
    )
    return JSONResponse(content=result.model_dump())


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest) -> JSONResponse:
    try:
        return _run_analysis(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/analyze/path")
async def analyze_path(request: AnalyzeRequest) -> JSONResponse:
    try:
        return _run_analysis(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/analyze/url")
async def analyze_url(request: AnalyzeRequest) -> JSONResponse:
    try:
        return _run_analysis(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/analyze/object")
async def analyze_object(request: AnalyzeRequest) -> JSONResponse:
    try:
        return _run_analysis(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/analyze/upload")
async def analyze_upload(file: UploadFile = File(...)) -> JSONResponse:
    suffix = Path(file.filename or "upload.png").suffix or ".png"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(await file.read())
            temp_path = Path(temp_file.name)

        result = analyze_local_file(temp_path)
        return JSONResponse(content=result.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp = temp_path if "temp_path" in locals() else None
        if temp and temp.exists():
            temp.unlink(missing_ok=True)
