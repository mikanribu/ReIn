"""Document upload and retrieval."""
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Document, TreatyVersion
from app.schemas.api import DocumentOut
from app.services import audit, documents

router = APIRouter(prefix="/documents", tags=["documents"])

# Bundled sample documents, so a demo can be run without hunting for a file.
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_SAMPLE_FILES = {"treaty": "sample_treaty.txt", "amendment": "sample_amendment.txt"}


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


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentOut]:
    """All uploaded documents (newest first), each linked to the treaty it
    produced or amended, if any."""
    docs = db.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    # Map document -> (treaty_id, reference) via the version that used it.
    versions = db.execute(
        select(TreatyVersion).where(TreatyVersion.source_document_id.is_not(None))
    ).scalars().all()
    link: dict[str, TreatyVersion] = {}
    for v in versions:
        link.setdefault(v.source_document_id, v)
    out = []
    for d in docs:
        item = _to_out(d)
        v = link.get(d.id)
        if v is not None:
            item.treaty_id = v.treaty_id
            item.treaty_reference = v.treaty.reference
        out.append(item)
    return out


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
    limit = get_settings().max_upload_bytes
    if len(data) > limit:
        raise HTTPException(
            413,
            f"File is too large ({len(data) // (1024 * 1024)} MB). "
            f"The maximum is {limit // (1024 * 1024)} MB.",
        )
    filename = file.filename or "upload.txt"
    content_type = _guess_content_type(filename, file.content_type)
    return _store_document(db, filename, data, kind, content_type, actor)


def _store_document(db, filename, data, kind, content_type, actor) -> DocumentOut:
    text = documents.extract_text(filename, data)
    doc = Document(
        filename=filename,
        kind=kind,
        content_text=text,
        content_bytes=data,
        content_type=content_type,
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


@router.post("/sample", response_model=DocumentOut, status_code=201)
def load_sample_document(
    kind: str = Form("treaty", description="'treaty' or 'amendment'"),
    actor: str = Form("user"),
    db: Session = Depends(get_db),
) -> DocumentOut:
    """Load a bundled sample document, so a demo can run without a file upload."""
    name = _SAMPLE_FILES.get(kind)
    if name is None:
        raise HTTPException(422, "kind must be 'treaty' or 'amendment'")
    path = SAMPLES_DIR / name
    if not path.exists():
        raise HTTPException(404, f"Sample '{name}' is not available on the server.")
    data = path.read_bytes()
    return _store_document(db, name, data, kind, "text/plain", actor)


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
