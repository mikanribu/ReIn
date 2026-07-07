"""Document upload and retrieval."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document
from app.schemas.api import DocumentOut
from app.services import audit, documents

router = APIRouter(prefix="/documents", tags=["documents"])


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
    text = documents.extract_text(file.filename or "upload.txt", data)
    doc = Document(
        filename=file.filename or "upload.txt",
        kind=kind,
        content_text=text,
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
