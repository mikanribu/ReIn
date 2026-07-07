"""Turn uploaded files into plain text for extraction."""
import hashlib
import io

from fastapi import HTTPException


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from PDF, DOCX or plain-text uploads."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _pdf_text(data)
    if lower.endswith(".docx"):
        return _docx_text(data)
    if lower.endswith((".txt", ".md", ".text")):
        return data.decode("utf-8", errors="replace")
    raise HTTPException(
        status_code=415,
        detail=f"Unsupported file type for '{filename}'. Supported: .pdf, .docx, .txt, .md",
    )


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        # Page markers help the LLM report accurate source locations.
        pages.append(f"[page {i}]\n{page.extract_text() or ''}")
    return "\n\n".join(pages)


def _docx_text(data: bytes) -> str:
    import docx2txt

    return docx2txt.process(io.BytesIO(data)) or ""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
