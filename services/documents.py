import re
import unicodedata

from sqlalchemy import select

from core.database import async_session_maker, Document

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
        return _doc_to_dict(doc)


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
        return _doc_to_dict(doc)


async def get_document_by_slug(slug: str) -> dict | None:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.slug == slug))
        doc = result.scalar_one_or_none()
        if not doc:
            return None
        return _doc_to_dict(doc)


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
        return [_doc_to_dict(doc) for doc in result.scalars().all()]


async def list_categories(published_only: bool = False) -> list[str]:
    async with async_session_maker() as session:
        q = select(Document.category).distinct()
        if published_only:
            q = q.where(Document.is_published == True)
        result = await session.execute(q)
        return [row[0] for row in result.fetchall() if row[0]]


def _doc_to_dict(doc: Document) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "slug": doc.slug,
        "content": doc.content,
        "category": doc.category,
        "is_published": doc.is_published,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
