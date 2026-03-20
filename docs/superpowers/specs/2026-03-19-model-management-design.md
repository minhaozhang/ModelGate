# 模型管理功能设计

## 背景

当前系统 `allowed_models` 是简单的字符串数组，无法结构化管理模型。需要增加：
- 模型表：统一管理模型元数据
- 供应商-模型绑定：一个模型可被多个供应商提供
- API Key 绑定：绑定到具体的供应商+模型组合

## 数据库设计

### 新增 Model 表

```sql
CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,        -- 模型标识: glm-4.7, deepseek-chat
    display_name VARCHAR(100),                 -- 显示名称: GLM-4.7, DeepSeek Chat
    max_tokens INTEGER DEFAULT 4096,           -- 最大 token 数
    is_multimodal BOOLEAN DEFAULT FALSE,       -- 是否多模态
    is_active BOOLEAN DEFAULT TRUE,            -- 是否启用
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 新增 ProviderModel 中间表

```sql
CREATE TABLE provider_models (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES providers(id) ON DELETE CASCADE,
    model_id INTEGER REFERENCES models(id) ON DELETE CASCADE,
    model_name_override VARCHAR(100),          -- 可选，实际调用时的模型名
    is_active BOOLEAN DEFAULT TRUE,            -- 该供应商下是否启用
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(provider_id, model_id)
);
```

### 修改 ApiKey 表

```sql
-- allowed_models 从 ARRAY(String) 改为 ARRAY(Integer)
-- 存储 provider_model_id 列表
ALTER TABLE api_keys ALTER COLUMN allowed_models TYPE INTEGER[];
```

## 关系说明

```
Provider (1) ←→ (N) ProviderModel (N) ←→ (1) Model
                            ↓
                       (绑定到)
                            ↓
                       ApiKey.allowed_models
```

- 一个 Model 可以被多个 Provider 提供（多对多）
- ProviderModel 是中间表，存储供应商特有的配置
- ApiKey 绑定到 ProviderModel，精确控制访问

## API 接口

### 模型管理

| Method | Endpoint | 描述 |
|--------|----------|------|
| GET | `/models` | 列出所有模型 |
| POST | `/models` | 创建模型 |
| PUT | `/models/{id}` | 更新模型 |
| DELETE | `/models/{id}` | 删除模型 |

### 供应商模型绑定

| Method | Endpoint | 描述 |
|--------|----------|------|
| GET | `/providers/{id}/models` | 获取供应商的模型列表 |
| POST | `/providers/{id}/models` | 为供应商添加模型绑定 |
| PUT | `/providers/{id}/models/{pm_id}` | 更新绑定配置 |
| DELETE | `/providers/{id}/models/{pm_id}` | 移除绑定 |
| POST | `/providers/{id}/sync-models` | 从供应商 API 同步模型 |

### API Key 配置（修改现有）

| Method | Endpoint | 描述 |
|--------|----------|------|
| POST | `/api-keys` | allowed_models 改为 provider_model_id 数组 |
| PUT | `/api-keys/{id}` | 同上 |

## 前端改动

### 配置页面

1. 新增「模型管理」Tab
   - 模型列表表格
   - 添加/编辑模型弹窗

2. 供应商编辑弹窗增加「模型绑定」区域
   - 多选下拉框选择模型
   - 显示已绑定模型列表
   - 「从 API 同步」按钮

3. API Key 编辑弹窗
   - allowed_models 改为多选下拉框
   - 选项格式：「供应商名 - 模型名」

## 请求流程改动

1. 客户端请求带 `model` 参数
2. 解析 provider/model（如 `zhipu/glm-4.7`）
3. 查找 ProviderModel 记录
4. 验证 ApiKey 是否有该 ProviderModel 的权限
5. 转发请求到对应供应商

## 数据迁移

1. 创建新表
2. 迁移现有 `allowed_models` 数据（需要手动创建 Model 和 ProviderModel 记录）
3. 或清空 `allowed_models` 重新配置

## 实现优先级

1. 数据库表创建 + SQLAlchemy 模型
2. 模型 CRUD API
3. ProviderModel CRUD API
4. 修改代理请求逻辑
5. 前端模型管理页面
6. 前端供应商模型绑定
7. 前端 API Key 模型选择
