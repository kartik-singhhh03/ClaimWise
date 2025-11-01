import os
from typing import Dict, Optional, Tuple, List
import re

# Optional deps: keep imports lazy and guarded


def _is_pdf(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".pdf"


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def extract_text(file_path: str) -> Tuple[str, Dict[str, str]]:
    """Extract text from a file.

    - PDFs: PyPDF2 (if installed)
    - Images: pytesseract + Pillow (if installed)
    - Fallback: read as UTF-8 text (best-effort)

    Returns (text, meta) where meta contains method and any warnings.
    """
    method = "unknown"
    warnings = []
    text = ""

    if _is_pdf(file_path):
        try:
            import PyPDF2  # type: ignore
        except Exception as e:  # pragma: no cover
            warnings.append(f"PyPDF2 not available: {e}")
        else:
            method = "pdf-pypdf2"
            try:
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        try:
                            text += page.extract_text() or ""
                        except Exception:
                            # Some pages may fail extraction
                            continue
            except Exception as e:
                warnings.append(f"PDF extraction failed: {e}")

    elif _is_image(file_path):
        try:
            from PIL import Image  # type: ignore
            import pytesseract  # type: ignore
        except Exception as e:  # pragma: no cover
            warnings.append(f"Image OCR deps missing: {e}")
        else:
            method = "image-pytesseract"
            try:
                img = Image.open(file_path)
                text = pytesseract.image_to_string(img)
            except Exception as e:
                warnings.append(f"Image OCR failed: {e}")

    # Fallback if nothing extracted
    if not text:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            if method == "unknown":
                method = "raw-text"
        except Exception:
            pass

    return text, {"method": method, "warnings": warnings}


def detect_insurance_type(text: str) -> str:
    t = (text or "").lower()
    health_tokens = ["hospital", "patient", "diagnosis", "prescription", "medicine", "medical", "treatment"]
    vehicle_tokens = ["vehicle", "registration", " rc ", " dl ", "driver", "license", "chassis", "engine", "fir", "police"]

    health_score = sum(tok in t for tok in health_tokens)
    vehicle_score = sum(tok in t for tok in vehicle_tokens)

    # Direct keyword hints
    if "health" in t:
        health_score += 2
    if "motor" in t or "vehicle" in t:
        vehicle_score += 1

    if health_score > vehicle_score:
        return "health"
    if vehicle_score > health_score:
        return "vehicle"
    # Tie: prefer health due to broader 'police' mentions in medical FNOLs
    return "health" if (health_score > 0 or vehicle_score > 0) else "unknown"


def detect_document_type(text: str, insurance_type: str) -> str:
    t = (text or "").lower()

    if insurance_type == "health":
        # Score-based detection for health
        scores = {"accord": 0, "hospital": 0, "loss": 0, "prescription": 0}

        def has(label: str) -> bool:
            return label in t

        # ACORD indicators (FNOL)
        if has("policy number"): scores["accord"] += 2
        if has("insurance start date"): scores["accord"] += 2
        if has("insurance expiry date"): scores["accord"] += 2
        if has("incident type") or has("incident date"): scores["accord"] += 2
        if has("patient id") or has("hospital code"): scores["accord"] += 1
        if has("diagnosis"): scores["accord"] += 1

        # Hospital Report indicators
        if has("admission date"): scores["hospital"] += 2
        if has("discharge date"): scores["hospital"] += 2
        if has("bill amount"): scores["hospital"] += 2
        if has("hospital code") or has("patient id"): scores["hospital"] += 1
        if has("prescription"): scores["hospital"] += 1

        # Loss/Assessment indicators
        if has("inspection date"): scores["loss"] += 2
        if has("loss date"): scores["loss"] += 2
        if has("inspection location"): scores["loss"] += 1
        if has("approved repair amount"): scores["loss"] += 1
        if has("medical notes"): scores["loss"] += 1
        if has("claim status"): scores["loss"] += 1

        # Prescription indicator (optional doc type)
        if has("prescription") or has("rx"): scores["prescription"] += 1

        best_type = max(scores, key=lambda k: scores[k])
        return best_type if scores[best_type] > 0 else "unknown"

    # Vehicle: score-based detection using label presence
    scores = {"accord": 0, "loss": 0, "fir": 0, "rc": 0, "dl": 0}

    def has(label: str) -> bool:
        return label in t

    # ACORD indicators
    if has("policy number"): scores["accord"] += 2
    if has("insurance start date"): scores["accord"] += 2
    if has("insurance expiry date"): scores["accord"] += 2
    if has("incident type"): scores["accord"] += 1
    if has("incident date"): scores["accord"] += 1
    if has("police report filed"): scores["accord"] += 1

    # LOSS indicators
    if has("loss date"): scores["loss"] += 2
    if has("inspection date"): scores["loss"] += 2
    if has("approved repair amount"): scores["loss"] += 1
    if has("total loss"): scores["loss"] += 1
    if has("claim status"): scores["loss"] += 1

    # FIR indicators
    if has("police report no"): scores["fir"] += 2
    if has("report date"): scores["fir"] += 2
    if has("first information report"): scores["fir"] += 2
    if has("police report"): scores["fir"] += 1

    # RC indicators
    if has("rc no"): scores["rc"] += 2
    if has("owner"): scores["rc"] += 1
    if has("vehicle model"): scores["rc"] += 1
    if has("manufacture year"): scores["rc"] += 1
    if has("fuel type"): scores["rc"] += 1
    if has("color"): scores["rc"] += 1

    # DL indicators
    if has("dl no"): scores["dl"] += 2
    if has("valid from"): scores["dl"] += 1
    if has("valid to"): scores["dl"] += 1
    if has("issuing authority"): scores["dl"] += 1
    if has("dob"): scores["dl"] += 1
    if has("address"): scores["dl"] += 1
    if has("name"): scores["dl"] += 1

    # Choose best score; tie-breaker preference order
    best_type = max(scores, key=lambda k: scores[k])
    if scores[best_type] > 0:
        return best_type
    return "unknown"


def load_schema(insurance_type: str, document_type: str) -> Optional[dict]:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "schemas")
    path = os.path.normpath(os.path.join(base_dir, insurance_type, f"{document_type}.schema.json"))
    if not os.path.exists(path):
        return None
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _label_value(text: str, labels: List[str], value_pattern: str = r"([^\n\r]+)") -> Optional[str]:
    pattern = re.compile(rf"(?im)\b(?:{'|'.join(map(re.escape, labels))})\b\s*[:\-]?\s*{value_pattern}")
    m = pattern.search(text)
    if m:
        return m.group(1).strip()
    return None


def _regex_value(text: str, pattern: str, flags=re.I) -> Optional[str]:
    m = re.search(pattern, text, flags)
    if not m:
        return None
    # If a capturing group exists, use it; otherwise use the whole match
    val = m.group(1) if m.lastindex else m.group(0)
    return val.strip()


def _to_bool(val: Optional[str]) -> Optional[bool]:
    if val is None:
        return None
    v = val.strip().lower()
    if v in {"true", "yes", "y", "1"}:
        return True
    if v in {"false", "no", "n", "0"}:
        return False
    return None


def _to_number(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    v = re.sub(r"[,\s]", "", val)
    try:
        return float(v)
    except Exception:
        return None


def _first(*candidates: Optional[str]) -> Optional[str]:
    for c in candidates:
        if c and c.strip():
            return c.strip()
    return None


def extract_entities(text: str, insurance_type: str, document_type: str) -> Dict[str, object]:
    t = text or ""

    # Common patterns
    claim_id = _first(
        _label_value(t, ["Claim ID", "Claim"], r"([A-Z]{3,}-[A-Za-z0-9-]+)"),
        _regex_value(t, r"\b(CL[Ml]-[A-Za-z0-9-]{6,})\b")
    )
    rc_no_generic = _first(
        _label_value(t, ["RC No", "RC Number", "Registration Certificate"], r"([A-Za-z0-9-]+)"),
        _regex_value(t, r"\bRC-?[A-Za-z0-9-]+\b")
    )
    dl_no_generic = _first(
        _label_value(t, ["DL No", "Driving License", "Driver Licence"], r"([A-Za-z0-9-]+)"),
        _regex_value(t, r"\bDL-?[A-Za-z0-9-]+\b")
    )
    registration_generic = _first(
        _label_value(t, ["Registration", "Vehicle No", "Vehicle Number"], r"([A-Za-z]{2}\s*\d{1,2}\s*[A-Za-z]{1,3}\s*\d{3,5}|[A-Za-z0-9-]+)"),
        _regex_value(t, r"\b[A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{3,5}\b")
    )

    entities: Dict[str, object] = {}

    if insurance_type == "vehicle":
        if document_type == "accord":
            entities.update({
                "claim_id": claim_id,
                "policy_number": _first(
                    _label_value(t, ["Policy Number", "Policy No"], r"([A-Za-z0-9-]+)")
                ),
                "insurance_start_date": _first(
                    _label_value(t, ["Insurance Start Date", "Policy Start"], r"(\d{4}-\d{2}-\d{2})")
                ),
                "insurance_expiry_date": _first(
                    _label_value(t, ["Insurance Expiry Date", "Policy End"], r"(\d{4}-\d{2}-\d{2})")
                ),
                "incident_type": _first(
                    _label_value(t, ["Incident Type", "Accident Type"])
                ),
                "incident_date": _first(
                    _label_value(t, ["Incident Date", "Accident Date"], r"(\d{4}-\d{2}-\d{2})")
                ),
                "registration": registration_generic,
                "location": _first(
                    _label_value(t, ["Location", "Accident Location"])
                ),
                "rc_no": rc_no_generic,
                "dl_no": dl_no_generic,
                "injuries_reported": _to_bool(_first(
                    _label_value(t, ["Injuries Reported", "Injuries"])
                )),
                "estimated_damage_cost": _to_number(_first(
                    _label_value(t, ["Estimated Damage Cost", "Damage Cost", "Estimated Damage"], r"([\d,]+(?:\.\d+)?)")
                )),
                "police_report_filed": _to_bool(_first(
                    _label_value(t, ["Police Report Filed"]) 
                )),
                "police_report_no": _first(
                    _label_value(t, ["Police Report No", "PR No"], r"([A-Za-z0-9-]+)")
                ),
            })

        elif document_type == "dl":
            entities.update({
                "claim_id": claim_id,
                "dl_no": dl_no_generic,
                "name": _first(_label_value(t, ["Name"])) ,
                "dob": _first(_label_value(t, ["DOB", "Date of Birth"], r"(\d{4}-\d{2}-\d{2})")),
                "address": _first(_label_value(t, ["Address"])),
                "valid_from": _first(_label_value(t, ["Valid From", "Issue Date"], r"(\d{4}-\d{2}-\d{2})")),
                "valid_to": _first(_label_value(t, ["Valid To", "Expiry Date"], r"(\d{4}-\d{2}-\d{2})")),
                "issuing_authority": _first(_label_value(t, ["Issuing Authority", "RTO"])),
                "remarks": _first(_label_value(t, ["Remarks", "Notes"]))
            })

        elif document_type == "loss":
            entities.update({
                "claim_id": claim_id,
                "inspection_date": _first(_label_value(t, ["Inspection Date"], r"(\d{4}-\d{2}-\d{2})")),
                "loss_date": _first(_label_value(t, ["Loss Date"], r"(\d{4}-\d{2}-\d{2})")),
                "inspection_location": _first(_label_value(t, ["Inspection Location", "Assessment Site"])),
                "registration": registration_generic,
                "rc_no": rc_no_generic,
                "dl_no": dl_no_generic,
                "injuries_reported": _to_bool(_first(_label_value(t, ["Injuries Reported"]))),
                "estimated_damage_cost": _to_number(_first(_label_value(t, ["Estimated Damage Cost", "Estimated Cost"], r"([\d,]+(?:\.\d+)?)"))),
                "approved_repair_amount": _to_number(_first(_label_value(t, ["Approved Repair Amount", "Approved Amount"], r"([\d,]+(?:\.\d+)?)"))),
                "total_loss": _to_bool(_first(_label_value(t, ["Total Loss"]))),
                "claim_status": _first(_label_value(t, ["Claim Status", "Status"]))
            })

        elif document_type == "fir":
            entities.update({
                "police_report_no": _first(_label_value(t, ["Police Report No", "PR No"], r"([A-Za-z0-9-]+)")),
                "claim_id": claim_id,
                "report_date": _first(_label_value(t, ["Report Date"], r"(\d{4}-\d{2}-\d{2})")),
                "incident_date": _first(_label_value(t, ["Incident Date"], r"(\d{4}-\d{2}-\d{2})")),
                "location": _first(_label_value(t, ["Location"])),
                "registration": registration_generic,
                "rc_no": rc_no_generic,
                "dl_no": dl_no_generic,
                "injuries_reported": _to_bool(_first(_label_value(t, ["Injuries Reported"]))),
                "estimated_damage_cost": _to_number(_first(_label_value(t, ["Estimated Damage Cost", "Damage Cost"], r"([\d,]+(?:\.\d+)?)")))
            })

        elif document_type == "rc":
            entities.update({
                "claim_id": claim_id,
                "rc_no": rc_no_generic,
                "registration": registration_generic,
                "owner": _first(_label_value(t, ["Owner", "Owner Name"])),
                "vehicle_model": _first(_label_value(t, ["Vehicle Model", "Model", "Make and Model"])),
                "manufacture_year": _first(_label_value(t, ["Manufacture Year", "Year of Manufacture"], r"(\d{4})")),
                "fuel_type": _first(_label_value(t, ["Fuel Type", "Fuel"])),
                "color": _first(_label_value(t, ["Color", "Colour"])),
                "notes": _first(_label_value(t, ["Notes", "Remarks"]))
            })

    elif insurance_type == "health":
        if document_type == "accord":
            entities.update({
                "claim_id": claim_id,
                "policy_number": _first(_label_value(t, ["Policy Number", "Policy No"], r"([A-Za-z0-9-]+)")),
                "insurance_start_date": _first(_label_value(t, ["Insurance Start Date", "Policy Start"], r"(\d{4}-\d{2}-\d{2})")),
                "insurance_expiry_date": _first(_label_value(t, ["Insurance Expiry Date", "Policy End"], r"(\d{4}-\d{2}-\d{2})")),
                "incident_type": _first(_label_value(t, ["Incident Type"])),
                "incident_date": _first(_label_value(t, ["Incident Date"], r"(\d{4}-\d{2}-\d{2})")),
                "location": _first(_label_value(t, ["Location", "Treatment Location"])),
                "patient_id": _first(_label_value(t, ["Patient ID"], r"([A-Za-z0-9-]+)")),
                "hospital_code": _first(_label_value(t, ["Hospital Code"], r"([A-Za-z0-9-]+)")),
                "injuries_reported": _to_bool(_first(_label_value(t, ["Injuries Reported", "Injuries"]))),
                "estimated_damage_cost": _to_number(_first(_label_value(t, ["Estimated Damage Cost", "Estimated Cost"], r"([\d,]+(?:\.\d+)?)"))),
                "police_report_filed": _to_bool(_first(_label_value(t, ["Police Report Filed"]))),
                "police_report_no": _first(_label_value(t, ["Police Report No", "PR No"], r"([A-Za-z0-9-]+)")),
                "diagnosis": _first(_label_value(t, ["Diagnosis"])),
                "hospital": _first(_label_value(t, ["Hospital"]))
            })

        elif document_type == "hospital":
            entities.update({
                "claim_id": claim_id,
                "patient_id": _first(_label_value(t, ["Patient ID"], r"([A-Za-z0-9-]+)")),
                "hospital_code": _first(_label_value(t, ["Hospital Code"], r"([A-Za-z0-9-]+)")),
                "prescription": _first(_label_value(t, ["Prescription"])),
                "admission_date": _first(_label_value(t, ["Admission Date"], r"(\d{4}-\d{2}-\d{2})")),
                "discharge_date": _first(_label_value(t, ["Discharge Date"], r"(\d{4}-\d{2}-\d{2})")),
                "bill_amount": _to_number(_first(_label_value(t, ["Bill Amount", "Bill"], r"([\d,]+(?:\.\d+)?)")))
            })

        elif document_type == "loss":
            entities.update({
                "claim_id": claim_id,
                "inspection_date": _first(_label_value(t, ["Inspection Date"], r"(\d{4}-\d{2}-\d{2})")),
                "loss_date": _first(_label_value(t, ["Loss Date"], r"(\d{4}-\d{2}-\d{2})")),
                "inspection_location": _first(_label_value(t, ["Inspection Location"])),
                "injuries_reported": _to_bool(_first(_label_value(t, ["Injuries Reported"]))),
                "estimated_damage_cost": _to_number(_first(_label_value(t, ["Estimated Damage Cost", "Estimated Cost"], r"([\d,]+(?:\.\d+)?)"))),
                "approved_repair_amount": _to_number(_first(_label_value(t, ["Approved Repair Amount", "Approved Amount"], r"([\d,]+(?:\.\d+)?)"))),
                "total_loss": _to_bool(_first(_label_value(t, ["Total Loss"]))),
                "claim_status": _first(_label_value(t, ["Claim Status", "Status"])),
                "medical_notes": _first(_label_value(t, ["Medical Notes", "Notes"]))
            })

    # Remove None values to keep payload clean
    return {k: v for k, v in entities.items() if v is not None}


def validate_against_schema(entities: dict, insurance_type: str, document_type: str) -> Dict[str, str]:
    schema = load_schema(insurance_type, document_type)
    if not schema:
        return {"status": "skipped", "reason": "schema_pending"}
    try:
        try:
            import jsonschema  # type: ignore
        except Exception as e:
            return {"status": "skipped", "reason": f"jsonschema_missing: {e}"}
        jsonschema.validate(instance=entities, schema=schema)
        return {"status": "valid"}
    except Exception as e:
        return {"status": "invalid", "error": str(e)}


def analyze_claim_document(file_path: str) -> dict:
    text, meta = extract_text(file_path)
    insurance_type = detect_insurance_type(text)
    document_type = detect_document_type(text, insurance_type)
    entities = extract_entities(text, insurance_type, document_type)
    validation = validate_against_schema(entities, insurance_type, document_type)

    return {
        "insurance_type": insurance_type,
        "document_type": document_type,
        "extraction": entities,
        "validation": validation,
        "text_summary": {
            "chars": len(text or ""),
            "preview": (text or "")[:500]
        },
        "meta": meta,
    }
