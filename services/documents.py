import re
import unicodedata

from sqlalchemy import select, func

from core.database import async_session_maker, Document, DocumentFile

MAX_FILE_SIZE = 1 * 1024 * 1024


def generate_slug(title: str) -> str:
    slug = unicodedata.normalize("NFKD", title)
    slug = re.sub(r"[^\w\s-]", "", slug).strip().lower()
    slug = re.sub(r"[-\s]+", "-", slug)
    if not slug:
        slug = "doc"
    return slug[:200]


async def ensure_unique_slug(slug: str, exclude_id: int | None = None) -> str:
    async with async_session_maker() as session:
        base = slug
        counter = 1
        while True:
            q = select(Document).where(Document.slug == slug)
            if exclude_id:
                q = q.where(Document.id != exclude_id)
            result = await session.execute(q)
            if result.scalar_one_or_none() is None:
                return slug
            slug = f"{base}-{counter}"
            counter += 1


async def _get_file_count(doc_id: int) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count(DocumentFile.id)).where(
                DocumentFile.document_id == doc_id
            )
        )
        return result.scalar() or 0


async def _get_file_counts(doc_ids: list[int]) -> dict[int, int]:
    if not doc_ids:
        return {}
    async with async_session_maker() as session:
        result = await session.execute(
            select(
                DocumentFile.document_id,
                func.count(DocumentFile.id),
            )
            .where(DocumentFile.document_id.in_(doc_ids))
            .group_by(DocumentFile.document_id)
        )
        return {doc_id: file_count for doc_id, file_count in result.fetchall()}


async def create_document(
    title: str,
    content: str,
    category: str | None,
    is_published: bool,
) -> dict:
    slug = await ensure_unique_slug(generate_slug(title))
    async with async_session_maker() as session:
        doc = Document(
            title=title,
            slug=slug,
            content=content,
            category=category or None,
            filename=None,
            is_published=is_published,
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        return _doc_to_dict(doc)


async def update_document(
    doc_id: int,
    title: str | None,
    content: str | None,
    category: str | None,
    is_published: bool | None,
) -> dict | None:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return None
        doc.filename = None
        if title is not None:
            doc.title = title
            doc.slug = await ensure_unique_slug(generate_slug(title), exclude_id=doc.id)
        if content is not None:
            doc.content = content
        if category is not None:
            doc.category = category or None
        if is_published is not None:
            doc.is_published = is_published
        await session.commit()
        await session.refresh(doc)
        file_count = await _get_file_count(doc.id)
        return _doc_to_dict(doc, file_count)


async def delete_document(doc_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return False
        await session.delete(doc)
        await session.commit()
        return True


async def get_document(doc_id: int) -> dict | None:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return None
        file_count = await _get_file_count(doc.id)
        return _doc_to_dict(doc, file_count)


async def get_document_by_slug(slug: str) -> dict | None:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.slug == slug))
        doc = result.scalar_one_or_none()
        if not doc:
            return None
        file_count = await _get_file_count(doc.id)
        return _doc_to_dict(doc, file_count)


async def list_documents(
    published_only: bool = False, category: str | None = None
) -> list[dict]:
    async with async_session_maker() as session:
        q = select(Document).order_by(Document.created_at.desc())
        if published_only:
            q = q.where(Document.is_published == True)
        if category:
            q = q.where(Document.category == category)
        result = await session.execute(q)
        docs = result.scalars().all()
    file_counts = await _get_file_counts([doc.id for doc in docs])
    return [_doc_to_dict(doc, file_counts.get(doc.id, 0)) for doc in docs]


async def list_categories(published_only: bool = False) -> list[str]:
    async with async_session_maker() as session:
        q = select(Document.category).distinct()
        if published_only:
            q = q.where(Document.is_published == True)
        result = await session.execute(q)
        return [row[0] for row in result.fetchall() if row[0]]


def _doc_to_dict(doc: Document, file_count: int = 0) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "slug": doc.slug,
        "content": doc.content,
        "category": doc.category,
        "is_published": doc.is_published,
        "file_count": file_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
