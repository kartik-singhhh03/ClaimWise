from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from services.file_service import save_uploaded_file
from services.ocr_service import analyze_claim_document

router = APIRouter(prefix="/upload", tags=["Upload"])

@router.post("/")
async def upload_claim_file(
    claim_number: str = Form(
        ..., description="Claim number used as filename", example="claim1"
    ),
    file: UploadFile = File(...)
):
    if not claim_number or not claim_number.strip():
        raise HTTPException(status_code=400, detail="claim_number is required")

    saved_path, public_url = await save_uploaded_file(file, claim_number)
    analysis = analyze_claim_document(saved_path)

    # 🔜 OCR + ML scoring will be added here later

    return {
        "status": "uploaded",
        "file_path": saved_path,
    "file_url": public_url,
    "analysis": analysis
    }
