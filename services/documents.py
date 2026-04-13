import os
import re
import unicodedata

from sqlalchemy import select, func

from core.database import async_session_maker, Document

UPLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "uploads", "documents"
)
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


def save_file(filename: str, content: str) -> str:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = re.sub(r"[^\w.-]", "_", filename)
    filepath = os.path.join(UPLOADS_DIR, safe_name)
    base, ext = os.path.splitext(safe_name)
    counter = 1
    while os.path.exists(filepath):
        filepath = os.path.join(UPLOADS_DIR, f"{base}_{counter}{ext}")
        counter += 1
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return os.path.basename(filepath)


def delete_file(filename: str | None) -> None:
    if not filename:
        return
    filepath = os.path.join(UPLOADS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


async def create_document(
    title: str,
    content: str,
    category: str | None,
    filename: str | None,
    is_published: bool,
) -> dict:
    slug = await ensure_unique_slug(generate_slug(title))
    async with async_session_maker() as session:
        doc = Document(
            title=title,
            slug=slug,
            content=content,
            category=category or None,
            filename=filename,
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
        delete_file(doc.filename)
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
        "filename": doc.filename,
        "is_published": doc.is_published,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
