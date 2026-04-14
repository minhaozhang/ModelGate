from sqlalchemy import select

from core.database import async_session_maker, DocumentFile
from services import storage


async def add_file(
    document_id: int,
    filename: str,
    file_bytes: bytes,
) -> dict:
    object_name = storage.upload_file(file_bytes, filename)
    file_type = storage.classify_file_type(filename)
    content_type = storage._guess_content_type(storage.get_extension(filename))
    async with async_session_maker() as session:
        doc_file = DocumentFile(
            document_id=document_id,
            filename=filename,
            object_name=object_name,
            file_type=file_type,
            file_size=len(file_bytes),
            content_type=content_type,
        )
        session.add(doc_file)
        await session.commit()
        await session.refresh(doc_file)
        return _file_to_dict(doc_file)


async def get_file(file_id: int) -> dict | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentFile).where(DocumentFile.id == file_id)
        )
        f = result.scalar_one_or_none()
        if not f:
            return None
        return _file_to_dict(f)


async def list_files(document_id: int) -> list[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentFile)
            .where(DocumentFile.document_id == document_id)
            .order_by(DocumentFile.created_at.asc())
        )
        return [_file_to_dict(f) for f in result.scalars().all()]


async def delete_file(file_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentFile).where(DocumentFile.id == file_id)
        )
        f = result.scalar_one_or_none()
        if not f:
            return False
        storage.delete_file(f.object_name)
        await session.delete(f)
        await session.commit()
        return True


async def delete_files_by_document(document_id: int) -> int:
    files = await list_files(document_id)
    count = 0
    async with async_session_maker() as session:
        for f in files:
            storage.delete_file(f["object_name"])
            result = await session.execute(
                select(DocumentFile).where(DocumentFile.id == f["id"])
            )
            doc_file = result.scalar_one_or_none()
            if doc_file:
                await session.delete(doc_file)
                count += 1
        await session.commit()
    return count


def _file_to_dict(f: DocumentFile) -> dict:
    return {
        "id": f.id,
        "document_id": f.document_id,
        "filename": f.filename,
        "object_name": f.object_name,
        "file_type": f.file_type,
        "file_size": f.file_size,
        "content_type": f.content_type,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }
