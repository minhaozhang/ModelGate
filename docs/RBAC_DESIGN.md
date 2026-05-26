# ModelGate RBAC 设计方案

## 一、数据库设计

### 1. 用户表 (users)
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt hash
    email VARCHAR(100),
    full_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_is_active ON users(is_active);
```

### 2. 角色表 (roles)
```sql
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE,  -- 系统预设角色不可删除
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_roles_name ON roles(name);
```

### 3. 用户角色关联表 (user_roles)
```sql
CREATE TABLE user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, role_id)
);

CREATE INDEX idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX idx_user_roles_role_id ON user_roles(role_id);
```

### 4. 权限表 (permissions)
```sql
CREATE TABLE permissions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(100),
    resource VARCHAR(50),
    action VARCHAR(20),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_permissions_code ON permissions(code);
CREATE INDEX idx_permissions_resource ON permissions(resource);
```

### 5. 角色权限关联表 (role_permissions)
```sql
CREATE TABLE role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, permission_id)
);

CREATE INDEX idx_role_permissions_role_id ON role_permissions(role_id);
CREATE INDEX idx_role_permissions_permission_id ON role_permissions(permission_id);
```

## 二、预设角色

### 1. admin（管理员）
- 所有权限
- 可以管理用户、角色、权限
- 可以修改系统配置

### 2. operator（操作员）
- 可以增删改查供应商、模型、API Key
- 可以查看日志和统计
- 不能管理用户和系统配置

### 3. viewer（只读用户）
- 只能查看所有资源
- 不能进行任何增删改操作

## 三、权限列表

### Provider（供应商）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `provider.view` | 查看供应商 | provider | read | 查看供应商列表和详情 |
| `provider.create` | 创建供应商 | provider | create | 创建新供应商 |
| `provider.update` | 更新供应商 | provider | update | 修改供应商信息 |
| `provider.delete` | 删除供应商 | provider | delete | 删除供应商 |
| `provider.toggle` | 启用/禁用供应商 | provider | update | 启用或禁用供应商 |

### Model（模型）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `model.view` | 查看模型 | model | read | 查看模型列表和详情 |
| `model.create` | 创建模型 | model | create | 创建新模型 |
| `model.update` | 更新模型 | model | update | 修改模型信息 |
| `model.delete` | 删除模型 | model | delete | 删除模型 |

### API Key（密钥）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `api_key.view` | 查看密钥 | api_key | read | 查看密钥列表和详情 |
| `api_key.create` | 创建密钥 | api_key | create | 创建新密钥 |
| `api_key.update` | 更新密钥 | api_key | update | 修改密钥信息 |
| `api_key.delete` | 删除密钥 | api_key | delete | 删除密钥 |
| `api_key.toggle` | 启用/禁用密钥 | api_key | update | 启用或禁用密钥 |

### Provider Model（供应商模型关联）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `provider_model.view` | 查看关联 | provider_model | read | 查看供应商模型关联 |
| `provider_model.create` | 创建关联 | provider_model | create | 创建供应商模型关联 |
| `provider_model.update` | 更新关联 | provider_model | update | 修改关联信息 |
| `provider_model.delete` | 删除关联 | provider_model | delete | 删除关联 |
| `provider_model.sync` | 同步模型 | provider_model | update | 同步供应商模型 |

### Log（日志）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `log.view` | 查看日志 | log | read | 查看请求日志 |
| `log.delete` | 删除日志 | log | delete | 删除日志记录 |
| `log.export` | 导出日志 | log | read | 导出日志数据 |
| `log.analyze` | 分析日志 | log | read | 错误分析和报告 |

### Stats（统计）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `stats.view` | 查看统计 | stats | read | 查看统计数据 |

### System Config（系统配置）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `system_config.view` | 查看配置 | system_config | read | 查看系统配置 |
| `system_config.update` | 更新配置 | system_config | update | 修改系统配置 |
| `scheduler.view` | 查看定时任务 | scheduler | read | 查看定时任务 |
| `scheduler.trigger` | 触发任务 | scheduler | update | 手动触发定时任务 |
| `scheduler.update` | 更新任务 | scheduler | update | 修改定时任务配置 |
| `notification.view` | 查看通知 | notification | read | 查看系统通知 |
| `notification.update` | 标记通知 | notification | update | 标记通知已读 |

### User Management（用户管理）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `user.view` | 查看用户 | user | read | 查看用户列表和详情 |
| `user.create` | 创建用户 | user | create | 创建新用户 |
| `user.update` | 更新用户 | user | update | 修改用户信息 |
| `user.delete` | 删除用户 | user | delete | 删除用户 |
| `user.assign_role` | 分配角色 | user | update | 为用户分配角色 |
| `role.view` | 查看角色 | role | read | 查看角色列表 |
| `role.create` | 创建角色 | role | create | 创建新角色 |
| `role.update` | 更新角色 | role | update | 修改角色信息 |
| `role.delete` | 删除角色 | role | delete | 删除角色 |
| `permission.view` | 查看权限 | permission | read | 查看权限列表 |

### Document（文档）
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `document.view` | 查看文档 | document | read | 查看文档 |
| `document.create` | 创建文档 | document | create | 创建文档 |
| `document.update` | 更新文档 | document | update | 修改文档 |
| `document.delete` | 删除文档 | document | delete | 删除文档 |
| `document.upload` | 上传文件 | document | create | 上传文档附件 |

### MCP Server
| 权限代码 | 名称 | 资源 | 操作 | 说明 |
|---------|------|------|------|------|
| `mcp_server.view` | 查看 MCP 服务器 | mcp_server | read | 查看 MCP 服务器 |
| `mcp_server.create` | 创建 MCP 服务器 | mcp_server | create | 创建 MCP 服务器 |
| `mcp_server.update` | 更新 MCP 服务器 | mcp_server | update | 修改 MCP 服务器 |
| `mcp_server.delete` | 删除 MCP 服务器 | mcp_server | delete | 删除 MCP 服务器 |
| `mcp_server.sync` | 同步工具 | mcp_server | update | 同步 MCP 工具 |

## 四、接口权限映射

### Providers (routes/providers.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/providers` | `provider.view` | 查看供应商列表 |
| POST | `/providers` | `provider.create` | 创建供应商 |
| PUT | `/providers/{provider_id}` | `provider.update` | 更新供应商 |
| DELETE | `/providers/{provider_id}` | `provider.delete` | 删除供应商 |
| GET | `/providers/{provider_id}/keys` | `provider.view` | 查看供应商密钥 |
| POST | `/providers/{provider_id}/keys` | `provider.update` | 添加供应商密钥 |
| PUT | `/providers/{provider_id}/keys/{key_id}` | `provider.update` | 更新供应商密钥 |
| DELETE | `/providers/{provider_id}/keys/{key_id}` | `provider.update` | 删除供应商密钥 |

### Models (routes/models.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/models` | `model.view` | 查看模型列表 |
| POST | `/models` | `model.create` | 创建模型 |
| PUT | `/models/{model_id}` | `model.update` | 更新模型 |
| DELETE | `/models/{model_id}` | `model.delete` | 删除模型 |
| GET | `/models/{model_id}/api-keys` | `model.view` | 查看模型密钥 |
| PUT | `/models/{model_id}/api-keys` | `model.update` | 更新模型密钥 |

### API Keys (routes/keys.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/keys` | `api_key.view` | 查看密钥列表 |
| POST | `/keys` | `api_key.create` | 创建密钥 |
| PUT | `/keys/{key_id}` | `api_key.update` | 更新密钥 |
| DELETE | `/keys/{key_id}` | `api_key.delete` | 删除密钥 |
| GET | `/keys/{key_id}/stats` | `api_key.view` | 查看密钥统计 |
| GET | `/keys/{key_id}/logs` | `log.view` | 查看密钥日志 |
| GET | `/keys/{key_id}/time-rules` | `api_key.view` | 查看时间规则 |
| POST | `/keys/{key_id}/time-rules` | `api_key.update` | 创建时间规则 |
| PUT | `/keys/{key_id}/time-rules/{rule_id}` | `api_key.update` | 更新时间规则 |
| DELETE | `/keys/{key_id}/time-rules/{rule_id}` | `api_key.update` | 删除时间规则 |

### Provider Models (routes/provider_models.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/providers/{provider_id}/models` | `provider_model.view` | 查看供应商模型 |
| POST | `/providers/{provider_id}/models` | `provider_model.create` | 创建关联 |
| PUT | `/providers/{provider_id}/models/{pm_id}` | `provider_model.update` | 更新关联 |
| DELETE | `/providers/{provider_id}/models/{pm_id}` | `provider_model.delete` | 删除关联 |
| POST | `/providers/{provider_id}/sync-models` | `provider_model.sync` | 同步模型 |
| GET | `/provider-models` | `provider_model.view` | 查看所有关联 |

### Logs (routes/logs.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/logs/today` | `log.view` | 查看今日日志 |
| GET | `/logs/errors/today` | `log.view` | 查看今日错误 |
| GET | `/logs/errors/analyze` | `log.analyze` | 错误分析 |
| POST | `/logs/errors/analyze` | `log.analyze` | 创建分析报告 |
| GET | `/logs/errors/reports` | `log.view` | 查看分析报告 |
| GET | `/logs/errors/reports/{report_id}` | `log.view` | 查看报告详情 |
| GET | `/analysis/models` | `log.view` | 查看模型分析 |
| GET | `/logs/all` | `log.view` | 查看所有日志 |
| GET | `/logs/query` | `log.view` | 查询日志 |
| GET | `/logs/aggregate` | `log.view` | 聚合查询 |
| GET | `/mcp-logs/query` | `log.view` | 查询 MCP 日志 |

### Stats (routes/stats.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/stats/*` | `stats.view` | 查看统计数据 |

### System Config (routes/system_config.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/system/config` | `system_config.view` | 查看系统配置 |
| PUT | `/api/system/config` | `system_config.update` | 更新系统配置 |
| GET | `/api/system/ua-stats` | `stats.view` | 查看 UA 统计 |
| GET | `/api/notifications` | `notification.view` | 查看通知 |
| GET | `/api/notifications/unread-count` | `notification.view` | 未读通知数 |
| PUT | `/api/notifications/{notification_id}/read` | `notification.update` | 标记已读 |
| PUT | `/api/notifications/read-all` | `notification.update` | 全部已读 |
| GET | `/api/scheduler/tasks` | `scheduler.view` | 查看定时任务 |
| POST | `/api/scheduler/tasks/{task_id}/trigger` | `scheduler.trigger` | 触发任务 |
| PUT | `/api/scheduler/tasks/{task_id}` | `scheduler.update` | 更新任务 |
| GET | `/api/scheduler/tasks/{task_id}/logs` | `scheduler.view` | 查看任务日志 |
| GET | `/api/scheduler/logs` | `scheduler.view` | 查看所有日志 |

### Documents (routes/documents.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/documents` | `document.view` | 查看文档列表 |
| GET | `/documents/{doc_id}` | `document.view` | 查看文档详情 |
| POST | `/documents` | `document.create` | 创建文档 |
| POST | `/documents/upload` | `document.upload` | 上传文档 |
| PUT | `/documents/{doc_id}` | `document.update` | 更新文档 |
| DELETE | `/documents/{doc_id}` | `document.delete` | 删除文档 |
| POST | `/documents/{doc_id}/files` | `document.upload` | 上传附件 |
| GET | `/documents/{doc_id}/files` | `document.view` | 查看附件 |
| DELETE | `/documents/{doc_id}/files/{file_id}` | `document.delete` | 删除附件 |

### MCP Servers (routes/mcp_servers.py)
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/mcp-servers` | `mcp_server.view` | 查看 MCP 服务器 |
| POST | `/mcp-servers` | `mcp_server.create` | 创建 MCP 服务器 |
| PUT | `/mcp-servers/{server_id}` | `mcp_server.update` | 更新 MCP 服务器 |
| DELETE | `/mcp-servers/{server_id}` | `mcp_server.delete` | 删除 MCP 服务器 |
| POST | `/mcp-servers/{server_id}/sync` | `mcp_server.sync` | 同步工具 |
| GET | `/mcp-servers/{server_id}/tools` | `mcp_server.view` | 查看工具列表 |

## 五、前端按钮权限控制

### 需要权限控制的按钮/操作

#### 供应商管理页面
- **创建供应商** 按钮 → `provider.create`
- **编辑** 按钮 → `provider.update`
- **删除** 按钮 → `provider.delete`
- **启用/禁用** 开关 → `provider.toggle`
- **添加密钥** 按钮 → `provider.update`
- **编辑密钥** 按钮 → `provider.update`
- **删除密钥** 按钮 → `provider.update`

#### 模型管理页面
- **创建模型** 按钮 → `model.create`
- **编辑** 按钮 → `model.update`
- **删除** 按钮 → `model.delete`
- **关联 API Key** 按钮 → `model.update`

#### API Key 管理页面
- **创建密钥** 按钮 → `api_key.create`
- **编辑** 按钮 → `api_key.update`
- **删除** 按钮 → `api_key.delete`
- **启用/禁用** 开关 → `api_key.toggle`
- **添加时间规则** 按钮 → `api_key.update`
- **编辑时间规则** 按钮 → `api_key.update`
- **删除时间规则** 按钮 → `api_key.update`

#### 供应商模型关联页面
- **添加关联** 按钮 → `provider_model.create`
- **编辑** 按钮 → `provider_model.update`
- **删除** 按钮 → `provider_model.delete`
- **同步模型** 按钮 → `provider_model.sync`

#### 日志页面
- **删除日志** 按钮 → `log.delete`
- **导出** 按钮 → `log.export`
- **错误分析** 按钮 → `log.analyze`

#### 系统配置页面
- **保存配置** 按钮 → `system_config.update`
- **触发任务** 按钮 → `scheduler.trigger`
- **编辑任务** 按钮 → `scheduler.update`

#### 文档管理页面
- **创建文档** 按钮 → `document.create`
- **编辑** 按钮 → `document.update`
- **删除** 按钮 → `document.delete`
- **上传文件** 按钮 → `document.upload`

#### MCP 服务器页面
- **创建服务器** 按钮 → `mcp_server.create`
- **编辑** 按钮 → `mcp_server.update`
- **删除** 按钮 → `mcp_server.delete`
- **同步工具** 按钮 → `mcp_server.sync`

#### 用户管理页面（新增）
- **创建用户** 按钮 → `user.create`
- **编辑用户** 按钮 → `user.update`
- **删除用户** 按钮 → `user.delete`
- **分配角色** 按钮 → `user.assign_role`
- **创建角色** 按钮 → `role.create`
- **编辑角色** 按钮 → `role.update`
- **删除角色** 按钮 → `role.delete`

## 六、实施步骤

### 阶段一：数据库和后端基础
1. 创建数据库表结构
2. 初始化预设角色和权限数据
3. 实现用户认证（登录/登出）
4. 实现权限检查装饰器/依赖注入
5. 迁移现有 admin 用户到新用户表

### 阶段二：接口权限控制
1. 为所有需要权限的接口添加权限检查
2. 实现权限缓存机制（避免每次请求都查数据库）
3. 添加权限不足的统一错误响应

### 阶段三：前端权限控制
1. 登录后获取用户权限列表
2. 前端根据权限显示/隐藏按钮
3. 添加权限不足的友好提示

### 阶段四：用户管理界面
1. 创建用户管理页面
2. 创建角色管理页面
3. 实现用户-角色分配界面

### 阶段五：测试和优化
1. 测试各角色权限是否正确
2. 性能优化（权限缓存）
3. 审计日志（记录敏感操作）

## 七、技术实现要点

### 1. 权限检查装饰器
```python
from functools import wraps
from fastapi import HTTPException, Depends

async def require_permission(permission_code: str):
    async def dependency(user_id: int = Depends(get_current_user)):
        if not await has_permission(user_id, permission_code):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user_id
    return dependency

# 使用示例
@router.post("/providers")
async def create_provider(
    data: dict,
    _: int = Depends(require_permission("provider.create"))
):
    ...
```

### 2. 权限缓存
```python
# 使用 Redis 或内存缓存用户权限
# 格式: user:{user_id}:permissions = ["provider.view", "provider.create", ...]
# TTL: 5分钟
```

### 3. 前端权限控制
```javascript
// 获取用户权限
const permissions = await fetch('/api/auth/permissions').then(r => r.json());

// 检查权限
function hasPermission(code) {
    return permissions.includes(code);
}

// 条件渲染按钮
if (hasPermission('provider.create')) {
    showCreateButton();
}
```

### 4. 角色权限矩阵

| 权限 | admin | operator | viewer |
|------|-------|----------|--------|
| provider.* | ✓ | ✓ | view only |
| model.* | ✓ | ✓ | view only |
| api_key.* | ✓ | ✓ | view only |
| provider_model.* | ✓ | ✓ | view only |
| log.view | ✓ | ✓ | ✓ |
| log.delete | ✓ | ✗ | ✗ |
| log.analyze | ✓ | ✓ | ✗ |
| stats.view | ✓ | ✓ | ✓ |
| system_config.* | ✓ | ✗ | view only |
| user.* | ✓ | ✗ | ✗ |
| role.* | ✓ | ✗ | ✗ |
| document.* | ✓ | ✓ | view only |
| mcp_server.* | ✓ | ✓ | view only |
| scheduler.* | ✓ | ✗ | view only |
| notification.* | ✓ | ✓ | ✓ |

## 八、兼容性考虑

### 向后兼容
1. 保留现有的 `admin_users` 配置，自动迁移到新用户表
2. 现有的 `validate_session` 改为检查用户权限
3. 现有的 API Key 认证保持不变（用于 API 调用）

### 渐进式迁移
1. 第一阶段：只添加 viewer 角色，admin 保持原有权限
2. 第二阶段：细化 operator 权限
3. 第三阶段：完全基于 RBAC

## 九、安全考虑

1. **密码安全**：使用 bcrypt 加密，最少 12 轮
2. **会话管理**：JWT token，有效期 24 小时
3. **权限缓存**：5 分钟过期，角色变更立即清除缓存
4. **审计日志**：记录所有敏感操作（创建/删除用户、修改权限等）
5. **防暴力破解**：登录失败 5 次锁定 15 分钟
6. **最小权限原则**：默认无权限，显式授予

## 十、数据初始化脚本

见 `scripts/init_rbac.py`（待创建）
