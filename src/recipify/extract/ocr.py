"""OCR for scans and photos via the Mistral OCR API (paid, opt-in)."""

import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral
from mistralai.client.models import DocumentURLChunkTypedDict, ImageURLChunkTypedDict

ENGINE, VERSION = "mistral-ocr", 1
OCR_MODEL = "mistral-ocr-latest"
MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def api_key() -> str:
    load_dotenv()
    key = os.getenv("MISTRAL_API_KEY") or os.getenv("API_KEY")
    if not key:
        raise RuntimeError("Set MISTRAL_API_KEY (or API_KEY) in the environment or .env")
    return key


def extract_ocr(path: Path) -> str:
    mime = MIME[path.suffix.lower()]
    data_url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    document: DocumentURLChunkTypedDict | ImageURLChunkTypedDict = (
        {"type": "document_url", "document_url": data_url}
        if mime == "application/pdf"
        else {"type": "image_url", "image_url": data_url}
    )
    response = Mistral(api_key=api_key()).ocr.process(
        document=document, model=OCR_MODEL, include_image_base64=False
    )
    return "\n\n".join(p.markdown for p in response.pages).strip() + "\n"
