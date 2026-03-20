from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select

from database import async_session_maker, Model

router = APIRouter(prefix="/admin", tags=["models"])


class ModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    max_tokens: int = 16384
    is_multimodal: bool = False
    is_active: bool = True


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    max_tokens: Optional[int] = None
    is_multimodal: Optional[bool] = None
    is_active: Optional[bool] = None


@router.get("/models")
async def list_all_models():
    async with async_session_maker() as session:
        result = await session.execute(select(Model).order_by(Model.name))
        models = result.scalars().all()
        return {
            "models": [
                {
                    "id": m.id,
                    "name": m.name,
                    "display_name": m.display_name,
                    "max_tokens": m.max_tokens,
                    "is_multimodal": m.is_multimodal,
                    "is_active": m.is_active,
                }
                for m in models
            ]
        }


@router.post("/models")
async def create_model(data: ModelCreate):
    async with async_session_maker() as session:
        model = Model(**data.model_dump())
        session.add(model)
        await session.commit()
        return {"id": model.id, "name": model.name}


@router.put("/models/{model_id}")
async def update_model(model_id: int, data: ModelUpdate):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if not model:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(model, k, v)
        await session.commit()
        return {"id": model.id}


@router.delete("/models/{model_id}")
async def delete_model(model_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if not model:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        await session.delete(model)
        await session.commit()
        return {"deleted": True}
