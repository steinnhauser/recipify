"""OCR via the Mistral API for scanned PDFs and photos."""

import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral
from mistralai.client.models import DocumentURLChunkTypedDict, ImageURLChunkTypedDict

OCR_MODEL = "mistral-ocr-latest"
MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def ocr_to_markdown(path: Path) -> str:
    load_dotenv()
    api_key = os.getenv("MISTRAL_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError("Set MISTRAL_API_KEY (or API_KEY) in the environment or .env")
    mime = MIME[path.suffix.lower()]
    data_url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    document: DocumentURLChunkTypedDict | ImageURLChunkTypedDict = (
        {"type": "document_url", "document_url": data_url}
        if mime == "application/pdf"
        else {"type": "image_url", "image_url": data_url}
    )
    response = Mistral(api_key=api_key).ocr.process(
        document=document, model=OCR_MODEL, include_image_base64=False
    )
    pages = [p.markdown for p in response.pages]
    return "\n\n".join(pages).strip() + "\n"
