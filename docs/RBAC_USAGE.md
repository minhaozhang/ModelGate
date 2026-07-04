# RBAC 权限系统使用指南

## 概述

ModelGate 的 RBAC（基于角色的访问控制）系统提供了完整的四层权限管理：

1. **菜单权限** - 控制侧边栏菜单的显示
2. **页面权限** - 控制页面的访问
3. **元素权限** - 控制按钮、操作的显示和执行
4. **数据权限** - 控制数据的可见范围（预留）

## 快速开始

### 1. 数据库初始化

确保数据库已启动（`192.168.58.128:5432`），然后运行：

```bash
# 创建表结构
python db/migrations/add_rbac_tables.py

# 初始化数据（角色、权限、菜单）
python db/migrations/init_rbac_data.py
```

### 2. 安装依赖

```bash
pip install bcrypt PyJWT
```

### 3. 配置环境变量

在 `.env` 中添加：

```env
JWT_SECRET_KEY=your-secret-key-change-in-production
```

### 4. 启动服务

```bash
python -m app.main
```

## 预设角色

系统初始化后会创建 4 个预设角色：

| 角色 | 名称 | 权限范围 |
|------|------|----------|
| `superadmin` | 超级管理员 | 所有权限，不受限制 |
| `admin` | 管理员 | 所有业务权限 + 用户管理 |
| `operator` | 操作员 | 业务操作权限，不能管理用户和系统配置 |
| `viewer` | 只读用户 | 只能查看，不能操作 |

## API 接口

### 认证接口

#### 登录
```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "qwe123"
}
```

响应：
```json
{
  "success": true,
  "message": "登录成功",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user": {
      "id": 1,
      "username": "admin",
      "email": "admin@example.com",
      "full_name": "管理员",
      "is_superuser": true
    },
    "permissions": {
      "menus": ["menu.dashboard", "menu.providers", ...],
      "pages": ["page.dashboard", "page.providers", ...],
      "elements": ["provider.create", "provider.update", ...]
    }
  }
}
```

#### 登出
```http
POST /api/auth/logout
```

#### 获取当前用户信息
```http
GET /api/auth/me
Cookie: admin_token=<token>
```

#### 检查登录状态
```http
GET /api/auth/check
Cookie: admin_token=<token>
```

### 用户管理接口

#### 获取用户列表
```http
GET /api/users?page=1&page_size=20&keyword=admin
Cookie: admin_token=<token>
```

#### 创建用户
```http
POST /api/users
Cookie: admin_token=<token>
Content-Type: application/json

{
  "username": "newuser",
  "password": "password123",
  "email": "user@example.com",
  "full_name": "新用户",
  "is_superuser": false,
  "role_ids": [2, 3]
}
```

#### 更新用户
```http
PUT /api/users/{user_id}
Cookie: admin_token=<token>
Content-Type: application/json

{
  "email": "newemail@example.com",
  "full_name": "新名字",
  "is_active": true
}
```

#### 重置密码
```http
POST /api/users/{user_id}/reset-password
Cookie: admin_token=<token>
Content-Type: application/json

{
  "new_password": "newpassword123"
}
```

#### 分配角色
```http
POST /api/users/{user_id}/assign-roles
Cookie: admin_token=<token>
Content-Type: application/json

{
  "role_ids": [1, 2, 3]
}
```

### 角色管理接口

#### 获取角色列表
```http
GET /api/roles?page=1&page_size=50
Cookie: admin_token=<token>
```

#### 创建角色
```http
POST /api/roles
Cookie: admin_token=<token>
Content-Type: application/json

{
  "name": "custom_role",
  "display_name": "自定义角色",
  "description": "角色描述"
}
```

#### 分配权限
```http
POST /api/roles/{role_id}/assign-permissions
Cookie: admin_token=<token>
Content-Type: application/json

{
  "permission_ids": [1, 2, 3, 4, 5]
}
```

### 权限管理接口

#### 获取权限列表
```http
GET /api/permissions?type=menu&resource=dashboard
Cookie: admin_token=<token>
```

#### 获取权限树
```http
GET /api/permissions/tree
Cookie: admin_token=<token>
```

#### 获取权限分组
```http
GET /api/permissions/grouped
Cookie: admin_token=<token>
```

### 菜单管理接口

#### 获取当前用户菜单树
```http
GET /api/menus/tree
Cookie: admin_token=<token>
```

#### 获取所有菜单（管理用）
```http
GET /api/menus/all
Cookie: admin_token=<token>
```

## 后端使用

### 权限检查装饰器

```python
from fastapi import APIRouter, Request, Depends
from app.core.permissions import permission_required, login_required

router = APIRouter()

# 要求登录
@router.get("/profile")
async def get_profile(
    request: Request,
    user = Depends(login_required())
):
    return {"user": user.username}

# 要求特定权限
@router.get("/providers")
async def list_providers(
    request: Request,
    user = Depends(permission_required("page.providers"))
):
    return {"providers": [...]}

# 要求任一权限
from app.core.permissions import any_permission_required

@router.get("/logs")
async def list_logs(
    request: Request,
    user = Depends(any_permission_required(["page.logs.requests", "page.logs.errors"]))
):
    return {"logs": [...]}
```

### 手动权限检查

```python
from app.services.rbac import has_permission, query_user_permissions

# 检查单个权限
if await has_permission(user.id, "provider.create"):
    # 允许创建
    pass

# 获取所有权限
permissions = await query_user_permissions(user.id)
# {
#   "menus": [...],
#   "pages": [...],
#   "elements": [...]
# }
```

## 前端使用（待实现）

### 权限指令

```html
<!-- 有权限时显示 -->
<button v-permission="'provider.create'">创建供应商</button>

<!-- 有任一权限时显示 -->
<button v-permission:any="['provider.update', 'provider.delete']">操作</button>
```

### 路由守卫

```javascript
router.beforeEach((to, from, next) => {
  const requiredPermission = to.meta.permission;
  if (requiredPermission && !hasPermission(requiredPermission)) {
    next('/403');
  } else {
    next();
  }
});
```

## 权限码规范

### 菜单权限
- 格式：`menu.<resource>`
- 示例：`menu.dashboard`, `menu.providers`, `menu.logs.requests`

### 页面权限
- 格式：`page.<resource>`
- 示例：`page.dashboard`, `page.providers`, `page.users`

### 元素权限
- 格式：`<resource>.<action>`
- 示例：`provider.create`, `provider.update`, `user.delete`

### 数据权限（预留）
- 格式：`data.<resource>.<scope>`
- 示例：`data.provider.own`, `data.log.department`

## 迁移现有用户

如果你已经有 `admin_users` 配置，需要迁移到新的用户表：

```python
# 创建迁移脚本 db/migrations/migrate_admin_users.py
import asyncio
from app.core.config import admin_users
from app.core.database import User, UserRole, async_session_maker
from app.services.auth import hash_password

async def migrate():
    async with async_session_maker() as session:
        for username, password in admin_users.items():
            # 检查是否已存在
            existing = await session.execute(
                select(User).where(User.username == username)
            )
            if existing.scalar_one_or_none():
                continue
            
            # 创建用户
            user = User(
                username=username,
                password_hash=hash_password(password),
                email=f"{username}@modelgate.local",
                full_name=username,
                is_superuser=True,
                is_active=True
            )
            session.add(user)
            await session.flush()
            
            # 分配 superadmin 角色
            user_role = UserRole(user_id=user.id, role_id=1)
            session.add(user_role)
        
        await session.commit()

asyncio.run(migrate())
```

## 故障排查

### 数据库连接失败
```
Error: could not connect to server
```
解决：检查数据库是否启动，确认 `.env` 中的 `DATABASE_URL` 配置正确。

### JWT Token 过期
```
401 Unauthorized: 未登录或登录已过期
```
解决：重新登录获取新 token。Token 有效期为 24 小时。

### 权限不足
```
403 Forbidden: 无权限访问
```
解决：联系管理员分配相应权限。

## 安全建议

1. **生产环境必须修改 JWT_SECRET_KEY**
2. **使用 HTTPS** - Cookie 设置了 `httponly`，建议启用 `secure` 标志
3. **定期审计权限** - 检查用户权限分配是否合理
4. **密码策略** - 建议强制复杂密码（8位以上，包含大小写字母、数字、特殊字符）
5. **Token 刷新** - 考虑实现 refresh token 机制
6. **日志审计** - 记录所有权限变更操作

## 下一步

- [ ] 实现前端用户管理页面
- [ ] 实现前端角色管理页面
- [ ] 实现前端菜单管理页面
- [ ] 实现动态菜单渲染
- [ ] 实现权限指令 `v-permission`
- [ ] 为现有页面添加权限控制
- [ ] 实现数据权限（第四层）
- [ ] 实现操作日志审计
