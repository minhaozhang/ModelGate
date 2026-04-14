from typing import Optional

from fastapi import APIRouter, Cookie, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from core.config import validate_session
from services import documents as doc_svc

router = APIRouter(prefix="/admin/api/documents", tags=["documents"])


def _check(session: Optional[str]) -> bool:
    return validate_session(session)


@router.get("")
async def list_documents(request: Request, session: Optional[str] = Cookie(None)):
    if not _check(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    docs = await doc_svc.list_documents()
    return {"documents": docs}


@router.get("/{doc_id}")
async def get_document(doc_id: int, session: Optional[str] = Cookie(None)):
    if not _check(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    doc = await doc_svc.get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return doc


@router.post("")
async def create_document(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    category: str = Form(""),
    is_published: bool = Form(False),
    session: Optional[str] = Cookie(None),
):
    if not _check(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    doc = await doc_svc.create_document(
        title=title,
        content=content,
        category=category,
        is_published=is_published,
    )
    return doc


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form(""),
    is_published: bool = Form(False),
    session: Optional[str] = Cookie(None),
):
    if not _check(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not file.filename or not file.filename.endswith(".md"):
        return JSONResponse({"error": "Only .md files are allowed"}, status_code=400)

    body = await file.read()
    if len(body) > doc_svc.MAX_FILE_SIZE:
        return JSONResponse({"error": "File too large (max 1MB)"}, status_code=400)

    content = body.decode("utf-8", errors="replace")
    title = file.filename[:-3] if file.filename.endswith(".md") else file.filename
    doc = await doc_svc.create_document(
        title=title,
        content=content,
        category=category,
        is_published=is_published,
    )
    return doc


@router.put("/{doc_id}")
async def update_document(
    doc_id: int,
    request: Request,
    session: Optional[str] = Cookie(None),
):
    if not _check(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    result = await doc_svc.update_document(
        doc_id=doc_id,
        title=body.get("title"),
        content=body.get("content"),
        category=body.get("category"),
        is_published=body.get("is_published"),
    )
    if not result:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return result


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, session: Optional[str] = Cookie(None)):
    if not _check(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    ok = await doc_svc.delete_document(doc_id)
    if not ok:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return {"success": True}
