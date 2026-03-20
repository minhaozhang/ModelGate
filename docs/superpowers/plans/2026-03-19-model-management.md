# 模型管理功能实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan.

**Goal:** 实现模型表、供应商-模型绑定、API Key 模型权限管理

**Architecture:** 新增 Model 和 ProviderModel 表，修改 ApiKey.allowed_models 为整数数组，添加相关 CRUD API 和前端界面

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Tailwind CSS

---

## Chunk 1: 数据库模型和表创建

### Task 1: 添加 SQLAlchemy 模型

**Files:**
- Modify: `database.py`

- [ ] **Step 1: 在 database.py 添加 Model 和 ProviderModel 类**

```python
class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    max_tokens = Column(Integer, default=4096)
    is_multimodal = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProviderModel(Base):
    __tablename__ = "provider_models"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    model_name_override = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_provider_model", "provider_id", "model_id", unique=True),
    )
```

- [ ] **Step 2: 修改 ApiKey 的 allowed_models 类型**

```python
# 将 ARRAY(String) 改为 ARRAY(Integer)
allowed_models = Column(ARRAY(Integer), default=[])
```

- [ ] **Step 3: 重启服务让 SQLAlchemy 创建新表**

Run: 重启 api_proxy.py，SQLAlchemy 会自动创建新表

---

## Chunk 2: 模型 CRUD API

### Task 2: 添加模型管理 API

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: 添加 Pydantic 模型**

在现有 Pydantic 模型后添加：

```python
class ModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    max_tokens: int = 4096
    is_multimodal: bool = False
    is_active: bool = True


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    max_tokens: Optional[int] = None
    is_multimodal: Optional[bool] = None
    is_active: Optional[bool] = None
```

- [ ] **Step 2: 添加模型 CRUD 端点**

```python
@app.get("/models")
async def list_models():
    async with async_session_maker() as session:
        result = await session.execute(select(Model).order_by(Model.name))
        models = result.scalars().all()
        return [{"id": m.id, "name": m.name, "display_name": m.display_name, 
                 "max_tokens": m.max_tokens, "is_multimodal": m.is_multimodal, 
                 "is_active": m.is_active} for m in models]


@app.post("/models")
async def create_model(data: ModelCreate):
    async with async_session_maker() as session:
        model = Model(**data.model_dump())
        session.add(model)
        await session.commit()
        return {"id": model.id, "name": model.name}


@app.put("/models/{model_id}")
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


@app.delete("/models/{model_id}")
async def delete_model(model_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if not model:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        await session.delete(model)
        await session.commit()
        return {"deleted": True}
```

---

## Chunk 3: 供应商模型绑定 API

### Task 3: 添加供应商-模型绑定 API

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: 添加 Pydantic 模型**

```python
class ProviderModelCreate(BaseModel):
    model_id: int
    model_name_override: Optional[str] = None
    is_active: bool = True
```

- [ ] **Step 2: 添加供应商模型绑定端点**

```python
@app.get("/providers/{provider_id}/models")
async def list_provider_models(provider_id: int):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.provider_id == provider_id)
        )
        pms = result.scalars().all()
        models_data = []
        for pm in pms:
            model_result = await session.execute(select(Model).where(Model.id == pm.model_id))
            model = model_result.scalar_one_or_none()
            if model:
                models_data.append({
                    "id": pm.id,
                    "model_id": model.id,
                    "model_name": model.name,
                    "display_name": model.display_name,
                    "model_name_override": pm.model_name_override,
                    "is_active": pm.is_active
                })
        return models_data


@app.post("/providers/{provider_id}/models")
async def add_provider_model(provider_id: int, data: ProviderModelCreate):
    async with async_session_maker() as session:
        pm = ProviderModel(
            provider_id=provider_id,
            model_id=data.model_id,
            model_name_override=data.model_name_override,
            is_active=data.is_active
        )
        session.add(pm)
        await session.commit()
        return {"id": pm.id}


@app.delete("/providers/{provider_id}/models/{pm_id}")
async def remove_provider_model(provider_id: int, pm_id: int):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.id == pm_id,
                ProviderModel.provider_id == provider_id
            )
        )
        pm = result.scalar_one_or_none()
        if not pm:
            return JSONResponse({"error": "ProviderModel not found"}, status_code=404)
        await session.delete(pm)
        await session.commit()
        return {"deleted": True}


@app.post("/providers/{provider_id}/sync-models")
async def sync_provider_models(provider_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(Provider).where(Provider.id == provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                headers = {}
                if provider.api_key:
                    headers["authorization"] = f"Bearer {provider.api_key}"
                resp = await client.get(f"{provider.base_url}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
                
                synced = []
                for item in data.get("data", []):
                    model_name = item.get("id", "")
                    if not model_name:
                        continue
                    
                    existing = await session.execute(
                        select(Model).where(Model.name == model_name)
                    )
                    model = existing.scalar_one_or_none()
                    
                    if not model:
                        model = Model(name=model_name, display_name=model_name)
                        session.add(model)
                        await session.flush()
                    
                    pm_exists = await session.execute(
                        select(ProviderModel).where(
                            ProviderModel.provider_id == provider_id,
                            ProviderModel.model_id == model.id
                        )
                    )
                    if not pm_exists.scalar_one_or_none():
                        pm = ProviderModel(provider_id=provider_id, model_id=model.id)
                        session.add(pm)
                        synced.append(model_name)
                
                await session.commit()
                return {"synced": synced, "total": len(synced)}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
```

---

## Chunk 4: 获取所有可用模型 API

### Task 4: 添加获取所有可用模型的 API（供前端下拉选择用）

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: 添加获取所有 ProviderModel 的端点**

```python
@app.get("/provider-models")
async def list_all_provider_models():
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.is_active == True)
        )
        pms = result.scalars().all()
        models_data = []
        for pm in pms:
            provider_result = await session.execute(
                select(Provider).where(Provider.id == pm.provider_id)
            )
            provider = provider_result.scalar_one_or_none()
            model_result = await session.execute(select(Model).where(Model.id == pm.model_id))
            model = model_result.scalar_one_or_none()
            if provider and model:
                models_data.append({
                    "id": pm.id,
                    "provider_id": provider.id,
                    "provider_name": provider.name,
                    "model_id": model.id,
                    "model_name": model.name,
                    "display_name": f"{provider.name} - {model.display_name or model.name}"
                })
        return models_data
```

---

## Chunk 5: 修改 API Key 创建/更新逻辑

### Task 5: 修改 API Key 的 allowed_models 处理

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: 修改 ApiKeyCreate Pydantic 模型**

```python
class ApiKeyCreate(BaseModel):
    name: str
    allowed_models: list[int] = []  # 改为 int 数组（provider_model_id）
```

- [ ] **Step 2: 修改 create_api_key 端点**

找到 `async def create_api_key(data: ApiKeyCreate)` 函数，确保 allowed_models 正确存储为整数数组。

- [ ] **Step 3: 修改 update_api_key 端点**

找到 `async def update_api_key(key_id: int, data: ApiKeyUpdate)` 函数，确保 allowed_models 更新正确。

- [ ] **Step 4: 修改 list_api_keys 端点返回格式**

返回时需要包含 provider_model 的详细信息，方便前端显示。

---

## Chunk 6: 修改请求验证逻辑

### Task 6: 修改 validate_api_key 验证逻辑

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: 修改 validate_api_key 函数**

将 allowed_models 验证从字符串匹配改为 provider_model_id 验证。

需要根据请求的 provider 和 model，查找对应的 provider_model_id，然后检查是否在 api_key.allowed_models 列表中。

---

## Chunk 7: 前端 - 模型管理页面

### Task 7: 添加模型管理 Tab

**Files:**
- Modify: `api_proxy.py` (DASHBOARD_HTML 部分)

- [ ] **Step 1: 在导航栏添加「模型管理」Tab**

- [ ] **Step 2: 添加模型管理页面 HTML**

包含：
- 模型列表表格
- 添加模型按钮和弹窗
- 编辑/删除功能

---

## Chunk 8: 前端 - 供应商模型绑定

### Task 8: 在供应商编辑中添加模型绑定

**Files:**
- Modify: `api_proxy.py` (CONFIG_PAGE_HTML 部分)

- [ ] **Step 1: 修改供应商编辑弹窗**

添加：
- 已绑定模型列表
- 添加模型绑定下拉框
- 「从 API 同步」按钮

---

## Chunk 9: 前端 - API Key 模型选择

### Task 9: 修改 API Key 编辑的模型选择

**Files:**
- Modify: `api_proxy.py` (CONFIG_PAGE_HTML 部分)

- [ ] **Step 1: 修改 API Key 编辑弹窗**

将 allowed_models 从文本输入改为多选下拉框，选项为「供应商名 - 模型名」格式。

---

## 执行顺序

1. Chunk 1 - 数据库模型（必须先完成）
2. Chunk 2 - 模型 CRUD API
3. Chunk 3 - 供应商模型绑定 API
4. Chunk 4 - 获取所有可用模型 API
5. Chunk 5 - 修改 API Key 逻辑
6. Chunk 6 - 修改请求验证逻辑
7. Chunk 7-9 - 前端（可最后完成）
