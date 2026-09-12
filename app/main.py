from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.db import (
    get_receipt,
    init_db,
    insert_receipt,
    list_receipts,
)
from app.services.image_service import normalize_receipt_image
from app.services.item_classifier import classify_items
from app.services.receipt_extractor import (
    MODEL_NAME,
    extract_receipt,
)
from app.services.taxonomy_service import get_taxonomy_version
from app.services.validation import build_warnings


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
RECEIPT_DIR = BASE_DIR / "data" / "receipts"


@asynccontextmanager
async def lifespan(app: FastAPI):
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    yield


app = FastAPI(
    title="Local Receipt Scanner",
    lifespan=lifespan,
)


app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)

app.mount(
    "/receipts",
    StaticFiles(directory=RECEIPT_DIR),
    name="receipts",
)


@app.get("/")
def home():
    return FileResponse(
        STATIC_DIR / "index.html"
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
    }


@app.get("/api/receipts")
def receipts():
    return list_receipts()


@app.get("/api/receipts/{receipt_id}")
def receipt(receipt_id: str):
    result = get_receipt(receipt_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Receipt not found.",
        )

    return result


@app.post("/api/receipts/scan")
async def scan_receipt(
    file: UploadFile = File(...)
):
    filename = file.filename or ""

    is_image_content_type = (
        file.content_type is not None
        and file.content_type.startswith("image/")
    )

    is_heic_extension = filename.lower().endswith(
        (".heic", ".heif")
    )

    if not (
        is_image_content_type
        or is_heic_extension
    ):
        raise HTTPException(
            status_code=415,
            detail="Please upload an image.",
        )

    receipt_id = uuid4().hex

    try:
        image_path = await normalize_receipt_image(
            file=file,
            output_dir=RECEIPT_DIR,
            receipt_id=receipt_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    try:
        # Step 1: Extract receipt contents from the image.
        # Ollama inference is blocking work, so run it
        # outside FastAPI's async event loop.
        extraction = await run_in_threadpool(
            extract_receipt,
            image_path,
        )

    except Exception as exc:
        image_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail=f"Receipt extraction failed: {exc}",
        ) from exc


    try:
        # Step 2: Classify every extracted receipt item.
        classifications = await run_in_threadpool(
            classify_items,
            extraction,
        )

    except Exception as exc:
        image_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail=f"Item classification failed: {exc}",
        ) from exc


    # Step 3: Get the current taxonomy version.
    taxonomy_version = get_taxonomy_version()


    # Step 4: Run deterministic receipt validation.
    warnings = build_warnings(
        extraction
    )


    # Step 5: Save the receipt, items, classifications,
    # and any taxonomy suggestions.
    try:
        insert_receipt(
            receipt_id=receipt_id,
            image_filename=image_path.name,
            receipt=extraction,
            classifications=classifications,
            taxonomy_version=taxonomy_version,
            warnings=warnings,
        )

    except Exception as exc:
        image_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail=f"Failed to save receipt: {exc}",
        ) from exc


    saved_receipt = get_receipt(receipt_id)

    if saved_receipt is None:
        raise HTTPException(
            status_code=500,
            detail="Receipt could not be retrieved after saving.",
        )


    return {
        "id": receipt_id,
        "image_url": f"/receipts/{image_path.name}",
        "warnings": warnings,
        "receipt": saved_receipt,
    }