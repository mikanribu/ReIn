"""Document upload and retrieval."""
import mimetypes

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document
from app.schemas.api import DocumentOut
from app.services import audit, documents

router = APIRouter(prefix="/documents", tags=["documents"])


def _guess_content_type(filename: str, provided: str | None) -> str:
    if provided and provided != "application/octet-stream":
        return provided
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        kind=doc.kind,
        sha256=doc.sha256,
        uploaded_by=doc.uploaded_by,
        created_at=doc.created_at,
        text_length=len(doc.content_text),
    )


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form("treaty", description="'treaty' or 'amendment'"),
    actor: str = Form("user"),
    db: Session = Depends(get_db),
) -> DocumentOut:
    if kind not in ("treaty", "amendment"):
        raise HTTPException(422, "kind must be 'treaty' or 'amendment'")
    data = await file.read()
    if not data:
        raise HTTPException(422, "Uploaded file is empty")
    filename = file.filename or "upload.txt"
    text = documents.extract_text(filename, data)
    doc = Document(
        filename=filename,
        kind=kind,
        content_text=text,
        content_bytes=data,
        content_type=_guess_content_type(filename, file.content_type),
        sha256=documents.sha256_hex(data),
        uploaded_by=actor,
    )
    db.add(doc)
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="document.uploaded",
        entity_type="document",
        entity_id=doc.id,
        details={"filename": doc.filename, "kind": kind, "sha256": doc.sha256},
    )
    db.commit()
    return _to_out(doc)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentOut:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, f"Document {document_id} not found")
    return _to_out(doc)


@router.get("/{document_id}/text")
def get_document_text(document_id: str, db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, f"Document {document_id} not found")
    return {"id": doc.id, "filename": doc.filename, "text": doc.content_text}


@router.get("/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)) -> Response:
    """Serve the original uploaded file so it can be viewed/downloaded.

    PDFs render inline in the browser; other types download. Documents
    uploaded before file storage was added have no bytes -> 404.
    """
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, f"Document {document_id} not found")
    if not doc.content_bytes:
        raise HTTPException(
            404,
            "The original file for this document is not stored "
            "(it was uploaded before file viewing was enabled). Re-upload to view it.",
        )
    # Inline so browsers preview PDFs/text instead of forcing a download.
    safe_name = doc.filename.replace('"', "")
    return Response(
        content=doc.content_bytes,
        media_type=doc.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )
