# ModelGate 完整权限体系设计方案 V2

## 一、权限体系架构

### 1. 四层权限模型

```
用户 (User)
  ↓ 拥有
角色 (Role)
  ↓ 拥有
权限 (Permission)
  ├─ 菜单权限 (Menu Permission) - 控制导航菜单显示
  ├─ 页面权限 (Page Permission) - 控制页面访问
  ├─ 元素权限 (Element Permission) - 控制按钮/操作显示
  └─ 数据权限 (Data Permission) - 控制数据范围（可选）
```

### 2. 权限类型说明

| 权限类型 | 作用范围 | 示例 |
|---------|---------|------|
| 菜单权限 | 左侧导航栏 | 是否显示"供应商管理"菜单 |
| 页面权限 | 路由访问 | 是否能访问 `/admin/providers` |
| 元素权限 | 页面内操作 | 是否显示"创建供应商"按钮 |
| 数据权限 | 数据过滤 | 只能看到自己创建的 API Key |

## 二、数据库设计

### 1. 用户表 (users)
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100),
    full_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    is_superuser BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. 角色表 (roles)
```sql
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
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
```

### 4. 菜单表 (menus)
```sql
CREATE TABLE menus (
    id SERIAL PRIMARY KEY,
    parent_id INTEGER REFERENCES menus(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    icon VARCHAR(50),
    path VARCHAR(200),
    component VARCHAR(200),
    sort_order INTEGER DEFAULT 0,
    is_visible BOOLEAN DEFAULT TRUE,
    permission_code VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5. 权限表 (permissions)
```sql
CREATE TABLE permissions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(100),
    type VARCHAR(20) NOT NULL,
    resource VARCHAR(50),
    action VARCHAR(20),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**权限类型 (type):**
- menu - 菜单权限
- page - 页面权限
- element - 元素权限
- data - 数据权限

### 6. 角色权限关联表 (role_permissions)
```sql
CREATE TABLE role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, permission_id)
);
```


## 三、菜单结构设计

### 1. 菜单层级

```
首页 (Dashboard)
├─ 供应商管理 (Providers)
│  ├─ 供应商列表
│  └─ 供应商模型关联
├─ 模型管理 (Models)
├─ API Key 管理 (API Keys)
├─ 日志管理 (Logs)
│  ├─ 请求日志
│  ├─ 错误分析
│  └─ MCP 日志
├─ 统计分析 (Statistics)
├─ 文档管理 (Documents)
├─ MCP 服务器 (MCP Servers)
├─ 系统配置 (System)
│  ├─ 系统设置
│  ├─ 定时任务
│  └─ 通知中心
└─ 用户管理 (Users)
   ├─ 用户列表
   └─ 角色管理
```

### 2. 菜单权限代码

| 菜单 | 权限代码 | 说明 |
|------|---------|------|
| 首页 | menu.dashboard | 首页菜单 |
| 供应商管理 | menu.providers | 供应商管理菜单 |
| 供应商列表 | menu.providers.list | 供应商列表子菜单 |
| 供应商模型关联 | menu.providers.models | 供应商模型关联子菜单 |
| 模型管理 | menu.models | 模型管理菜单 |
| API Key 管理 | menu.api_keys | API Key 管理菜单 |
| 日志管理 | menu.logs | 日志管理菜单 |
| 请求日志 | menu.logs.requests | 请求日志子菜单 |
| 错误分析 | menu.logs.errors | 错误分析子菜单 |
| MCP 日志 | menu.logs.mcp | MCP 日志子菜单 |
| 统计分析 | menu.stats | 统计分析菜单 |
| 文档管理 | menu.documents | 文档管理菜单 |
| MCP 服务器 | menu.mcp_servers | MCP 服务器菜单 |
| 系统配置 | menu.system | 系统配置菜单 |
| 系统设置 | menu.system.config | 系统设置子菜单 |
| 定时任务 | menu.system.scheduler | 定时任务子菜单 |
| 通知中心 | menu.system.notifications | 通知中心子菜单 |
| 用户管理 | menu.users | 用户管理菜单 |
| 用户列表 | menu.users.list | 用户列表子菜单 |
| 角色管理 | menu.users.roles | 角色管理子菜单 |


## 四、页面权限设计

### 1. 页面权限代码

| 页面路径 | 权限代码 | 说明 |
|---------|---------|------|
| /admin/home | page.dashboard | 首页 |
| /admin/providers | page.providers | 供应商列表页 |
| /admin/provider-models | page.provider_models | 供应商模型关联页 |
| /admin/models | page.models | 模型列表页 |
| /admin/keys | page.api_keys | API Key 列表页 |
| /admin/request-logs | page.logs.requests | 请求日志页 |
| /admin/error-analysis | page.logs.errors | 错误分析页 |
| /admin/mcp-logs | page.logs.mcp | MCP 日志页 |
| /admin/stats | page.stats | 统计分析页 |
| /admin/documents | page.documents | 文档管理页 |
| /admin/mcp-servers | page.mcp_servers | MCP 服务器页 |
| /admin/system-config | page.system.config | 系统配置页 |
| /admin/scheduler-tasks | page.system.scheduler | 定时任务页 |
| /admin/notifications | page.system.notifications | 通知中心页 |
| /admin/users | page.users | 用户管理页 |
| /admin/roles | page.roles | 角色管理页 |

## 五、元素权限设计

### 1. 供应商管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建供应商按钮 | provider.create | element | 创建供应商 |
| 编辑按钮 | provider.update | element | 编辑供应商 |
| 删除按钮 | provider.delete | element | 删除供应商 |
| 启用/禁用开关 | provider.toggle | element | 启用/禁用供应商 |
| 添加密钥按钮 | provider.add_key | element | 添加供应商密钥 |
| 编辑密钥按钮 | provider.update_key | element | 编辑供应商密钥 |
| 删除密钥按钮 | provider.delete_key | element | 删除供应商密钥 |

### 2. 模型管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建模型按钮 | model.create | element | 创建模型 |
| 编辑按钮 | model.update | element | 编辑模型 |
| 删除按钮 | model.delete | element | 删除模型 |
| 关联 API Key 按钮 | model.bind_key | element | 关联 API Key |

### 3. API Key 管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建密钥按钮 | pi_key.create | element | 创建密钥 |
| 编辑按钮 | pi_key.update | element | 编辑密钥 |
| 删除按钮 | pi_key.delete | element | 删除密钥 |
| 启用/禁用开关 | pi_key.toggle | element | 启用/禁用密钥 |
| 添加时间规则按钮 | pi_key.add_time_rule | element | 添加时间规则 |
| 编辑时间规则按钮 | pi_key.update_time_rule | element | 编辑时间规则 |
| 删除时间规则按钮 | pi_key.delete_time_rule | element | 删除时间规则 |


### 4. 供应商模型关联页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 添加关联按钮 | provider_model.create | element | 添加关联 |
| 编辑按钮 | provider_model.update | element | 编辑关联 |
| 删除按钮 | provider_model.delete | element | 删除关联 |
| 同步模型按钮 | provider_model.sync | element | 同步模型 |

### 5. 日志管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 删除日志按钮 | log.delete | element | 删除日志 |
| 导出按钮 | log.export | element | 导出日志 |
| 错误分析按钮 | log.analyze | element | 错误分析 |
| 创建分析报告按钮 | log.create_report | element | 创建分析报告 |

### 6. 系统配置页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 保存配置按钮 | system_config.update | element | 保存系统配置 |
| 触发任务按钮 | scheduler.trigger | element | 手动触发任务 |
| 编辑任务按钮 | scheduler.update | element | 编辑定时任务 |
| 标记已读按钮 | 
otification.mark_read | element | 标记通知已读 |

### 7. 文档管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建文档按钮 | document.create | element | 创建文档 |
| 编辑按钮 | document.update | element | 编辑文档 |
| 删除按钮 | document.delete | element | 删除文档 |
| 上传文件按钮 | document.upload | element | 上传附件 |
| 删除附件按钮 | document.delete_file | element | 删除附件 |

### 8. MCP 服务器页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建服务器按钮 | mcp_server.create | element | 创建 MCP 服务器 |
| 编辑按钮 | mcp_server.update | element | 编辑 MCP 服务器 |
| 删除按钮 | mcp_server.delete | element | 删除 MCP 服务器 |
| 同步工具按钮 | mcp_server.sync | element | 同步工具 |

### 9. 用户管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建用户按钮 | user.create | element | 创建用户 |
| 编辑用户按钮 | user.update | element | 编辑用户 |
| 删除用户按钮 | user.delete | element | 删除用户 |
| 分配角色按钮 | user.assign_role | element | 分配角色 |
| 重置密码按钮 | user.reset_password | element | 重置密码 |

### 10. 角色管理页面元素权限

| 元素 | 权限代码 | 类型 | 说明 |
|------|---------|------|------|
| 创建角色按钮 | ole.create | element | 创建角色 |
| 编辑角色按钮 | ole.update | element | 编辑角色 |
| 删除角色按钮 | ole.delete | element | 删除角色 |
| 分配权限按钮 | ole.assign_permission | element | 分配权限 |


## 六、预设角色权限矩阵

### 1. 角色定义

| 角色 | 代码 | 说明 |
|------|------|------|
| 超级管理员 | superadmin | 所有权限，不受限制 |
| 管理员 | dmin | 业务管理权限，可管理用户 |
| 操作员 | operator | 业务操作权限，不能管理用户和系统配置 |
| 只读用户 | iewer | 只能查看，不能操作 |

### 2. 菜单权限矩阵

| 菜单 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 首页 | ✓ | ✓ | ✓ | ✓ |
| 供应商管理 | ✓ | ✓ | ✓ | ✓ |
| 模型管理 | ✓ | ✓ | ✓ | ✓ |
| API Key 管理 | ✓ | ✓ | ✓ | ✓ |
| 日志管理 | ✓ | ✓ | ✓ | ✓ |
| 统计分析 | ✓ | ✓ | ✓ | ✓ |
| 文档管理 | ✓ | ✓ | ✓ | ✓ |
| MCP 服务器 | ✓ | ✓ | ✓ | ✓ |
| 系统配置 | ✓ | ✓ | ✗ | ✗ |
| 用户管理 | ✓ | ✓ | ✗ | ✗ |

### 3. 元素权限矩阵（供应商管理）

| 操作 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 查看供应商 | ✓ | ✓ | ✓ | ✓ |
| 创建供应商 | ✓ | ✓ | ✓ | ✗ |
| 编辑供应商 | ✓ | ✓ | ✓ | ✗ |
| 删除供应商 | ✓ | ✓ | ✓ | ✗ |
| 启用/禁用 | ✓ | ✓ | ✓ | ✗ |
| 添加密钥 | ✓ | ✓ | ✓ | ✗ |
| 编辑密钥 | ✓ | ✓ | ✓ | ✗ |
| 删除密钥 | ✓ | ✓ | ✓ | ✗ |

### 4. 元素权限矩阵（模型管理）

| 操作 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 查看模型 | ✓ | ✓ | ✓ | ✓ |
| 创建模型 | ✓ | ✓ | ✓ | ✗ |
| 编辑模型 | ✓ | ✓ | ✓ | ✗ |
| 删除模型 | ✓ | ✓ | ✓ | ✗ |
| 关联 API Key | ✓ | ✓ | ✓ | ✗ |

### 5. 元素权限矩阵（API Key 管理）

| 操作 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 查看密钥 | ✓ | ✓ | ✓ | ✓ |
| 创建密钥 | ✓ | ✓ | ✓ | ✗ |
| 编辑密钥 | ✓ | ✓ | ✓ | ✗ |
| 删除密钥 | ✓ | ✓ | ✓ | ✗ |
| 启用/禁用 | ✓ | ✓ | ✓ | ✗ |
| 时间规则管理 | ✓ | ✓ | ✓ | ✗ |

### 6. 元素权限矩阵（日志管理）

| 操作 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 查看日志 | ✓ | ✓ | ✓ | ✓ |
| 删除日志 | ✓ | ✓ | ✗ | ✗ |
| 导出日志 | ✓ | ✓ | ✓ | ✗ |
| 错误分析 | ✓ | ✓ | ✓ | ✗ |

### 7. 元素权限矩阵（系统配置）

| 操作 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 查看配置 | ✓ | ✓ | ✗ | ✗ |
| 修改配置 | ✓ | ✓ | ✗ | ✗ |
| 查看定时任务 | ✓ | ✓ | ✗ | ✗ |
| 触发任务 | ✓ | ✓ | ✗ | ✗ |
| 编辑任务 | ✓ | ✓ | ✗ | ✗ |

### 8. 元素权限矩阵（用户管理）

| 操作 | superadmin | admin | operator | viewer |
|------|------------|-------|----------|--------|
| 查看用户 | ✓ | ✓ | ✗ | ✗ |
| 创建用户 | ✓ | ✓ | ✗ | ✗ |
| 编辑用户 | ✓ | ✓ | ✗ | ✗ |
| 删除用户 | ✓ | ✓ | ✗ | ✗ |
| 分配角色 | ✓ | ✓ | ✗ | ✗ |
| 重置密码 | ✓ | ✓ | ✗ | ✗ |
| 管理角色 | ✓ | ✓ | ✗ | ✗ |


## 七、前端实现方案

### 1. 权限数据结构

用户登录后，后端返回权限数据：

```json
{
  "user": {
    "id": 1,
    "username": "admin",
    "roles": ["admin"]
  },
  "permissions": {
    "menus": ["menu.dashboard", "menu.providers", "menu.models", ...],
    "pages": ["page.dashboard", "page.providers", "page.models", ...],
    "elements": ["provider.create", "provider.update", "model.create", ...]
  }
}
```

### 2. 菜单渲染逻辑

```javascript
// 菜单配置
const menuConfig = [
  {
    id: 'dashboard',
    name: '首页',
    path: '/admin/home',
    icon: 'home',
    permission: 'menu.dashboard'
  },
  {
    id: 'providers',
    name: '供应商管理',
    icon: 'server',
    permission: 'menu.providers',
    children: [
      {
        id: 'providers-list',
        name: '供应商列表',
        path: '/admin/providers',
        permission: 'menu.providers.list'
      },
      {
        id: 'provider-models',
        name: '供应商模型关联',
        path: '/admin/provider-models',
        permission: 'menu.providers.models'
      }
    ]
  },
  // ...
];

// 过滤菜单
function filterMenus(menus, userPermissions) {
  return menus.filter(menu => {
    if (menu.permission && !userPermissions.menus.includes(menu.permission)) {
      return false;
    }
    if (menu.children) {
      menu.children = filterMenus(menu.children, userPermissions);
    }
    return true;
  });
}

// 渲染菜单
const visibleMenus = filterMenus(menuConfig, userPermissions);
```

### 3. 页面路由守卫

```javascript
// 路由配置
const routes = [
  {
    path: '/admin/providers',
    component: ProvidersPage,
    permission: 'page.providers'
  },
  // ...
];

// 路由守卫
router.beforeEach((to, from, next) => {
  const permission = to.meta.permission;
  if (permission && !hasPagePermission(permission)) {
    next('/403'); // 无权限页面
  } else {
    next();
  }
});
```

### 4. 元素权限控制

```javascript
// 权限检查函数
function hasPermission(code) {
  return userPermissions.elements.includes(code);
}

// 按钮渲染
<button v-if="hasPermission('provider.create')" @click="createProvider">
  创建供应商
</button>

// 或使用自定义指令
<button v-permission="'provider.create'" @click="createProvider">
  创建供应商
</button>
```

### 5. 权限指令实现

```javascript
// v-permission 指令
app.directive('permission', {
  mounted(el, binding) {
    const permission = binding.value;
    if (!hasPermission(permission)) {
      el.style.display = 'none';
      // 或者直接移除元素
      // el.parentNode?.removeChild(el);
    }
  }
});
```


## 八、后端实现方案

### 1. 权限检查装饰器

```python
from functools import wraps
from fastapi import HTTPException, Depends
from typing import List

async def get_current_user_permissions(user_id: int) -> dict:
    '''获取用户权限（带缓存）'''
    cache_key = f"user:{user_id}:permissions"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # 从数据库查询
    permissions = await db.query_user_permissions(user_id)
    await redis.setex(cache_key, 300, json.dumps(permissions))  # 5分钟缓存
    return permissions

async def require_permission(permission_code: str):
    '''权限检查依赖'''
    async def dependency(user_id: int = Depends(get_current_user)):
        permissions = await get_current_user_permissions(user_id)
        if permission_code not in permissions['elements']:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user_id
    return dependency

# 使用示例
@router.post("/providers")
async def create_provider(
    data: dict,
    _: int = Depends(require_permission("provider.create"))
):
    # 创建供应商逻辑
    pass
```

### 2. 批量权限检查

```python
async def require_any_permission(permission_codes: List[str]):
    '''任一权限满足即可'''
    async def dependency(user_id: int = Depends(get_current_user)):
        permissions = await get_current_user_permissions(user_id)
        if not any(code in permissions['elements'] for code in permission_codes):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user_id
    return dependency

async def require_all_permissions(permission_codes: List[str]):
    '''所有权限都需要满足'''
    async def dependency(user_id: int = Depends(get_current_user)):
        permissions = await get_current_user_permissions(user_id)
        if not all(code in permissions['elements'] for code in permission_codes):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user_id
    return dependency
```

### 3. 用户权限查询

```python
async def query_user_permissions(user_id: int) -> dict:
    '''查询用户的所有权限'''
    async with async_session_maker() as session:
        # 查询用户角色
        result = await session.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        roles = result.scalars().all()
        
        # 查询角色权限
        permission_ids = set()
        for role in roles:
            result = await session.execute(
                select(RolePermission.permission_id)
                .where(RolePermission.role_id == role.id)
            )
            permission_ids.update(result.scalars().all())
        
        # 查询权限详情
        result = await session.execute(
            select(Permission)
            .where(Permission.id.in_(permission_ids))
        )
        permissions = result.scalars().all()
        
        # 按类型分组
        grouped = {
            'menus': [],
            'pages': [],
            'elements': []
        }
        for perm in permissions:
            if perm.type == 'menu':
                grouped['menus'].append(perm.code)
            elif perm.type == 'page':
                grouped['pages'].append(perm.code)
            elif perm.type == 'element':
                grouped['elements'].append(perm.code)
        
        return grouped
```

### 4. 登录接口返回权限

```python
@router.post("/auth/login")
async def login(username: str, password: str):
    # 验证用户名密码
    user = await authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # 生成 token
    token = create_access_token(user.id)
    
    # 获取权限
    permissions = await query_user_permissions(user.id)
    
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        },
        "permissions": permissions
    }
```


## 九、实施步骤

### 阶段一：数据库和基础架构（1-2天）
1. 创建数据库表结构
2. 初始化预设角色和权限数据
3. 编写权限查询和缓存逻辑
4. 实现用户认证（登录/登出）

### 阶段二：后端权限控制（2-3天）
1. 实现权限检查装饰器
2. 为所有需要权限的接口添加权限检查
3. 实现用户管理接口（CRUD）
4. 实现角色管理接口（CRUD）
5. 实现权限分配接口

### 阶段三：前端菜单和路由（2-3天）
1. 实现菜单配置和动态渲染
2. 实现路由守卫
3. 实现权限指令（v-permission）
4. 登录后获取并存储权限数据

### 阶段四：前端元素权限（2-3天）
1. 为所有操作按钮添加权限控制
2. 为表单提交添加权限检查
3. 优化用户体验（无权限时的提示）

### 阶段五：用户管理界面（2-3天）
1. 创建用户列表页面
2. 创建用户编辑/创建表单
3. 创建角色管理页面
4. 创建权限分配界面

### 阶段六：测试和优化（2-3天）
1. 测试各角色权限是否正确
2. 性能优化（权限缓存、查询优化）
3. 添加审计日志
4. 文档编写

**总计：11-17 天**

## 十、数据初始化脚本

### 1. 初始化角色

```sql
INSERT INTO roles (name, display_name, description, is_system) VALUES
('superadmin', '超级管理员', '拥有所有权限', true),
('admin', '管理员', '业务管理权限', true),
('operator', '操作员', '业务操作权限', true),
('viewer', '只读用户', '只能查看', true);
```

### 2. 初始化菜单权限

```sql
INSERT INTO permissions (code, name, type, resource, action) VALUES
('menu.dashboard', '首页菜单', 'menu', 'dashboard', 'view'),
('menu.providers', '供应商管理菜单', 'menu', 'providers', 'view'),
('menu.providers.list', '供应商列表菜单', 'menu', 'providers', 'view'),
('menu.providers.models', '供应商模型关联菜单', 'menu', 'provider_models', 'view'),
('menu.models', '模型管理菜单', 'menu', 'models', 'view'),
('menu.api_keys', 'API Key管理菜单', 'menu', 'api_keys', 'view'),
('menu.logs', '日志管理菜单', 'menu', 'logs', 'view'),
('menu.logs.requests', '请求日志菜单', 'menu', 'logs', 'view'),
('menu.logs.errors', '错误分析菜单', 'menu', 'logs', 'view'),
('menu.logs.mcp', 'MCP日志菜单', 'menu', 'logs', 'view'),
('menu.stats', '统计分析菜单', 'menu', 'stats', 'view'),
('menu.documents', '文档管理菜单', 'menu', 'documents', 'view'),
('menu.mcp_servers', 'MCP服务器菜单', 'menu', 'mcp_servers', 'view'),
('menu.system', '系统配置菜单', 'menu', 'system', 'view'),
('menu.system.config', '系统设置菜单', 'menu', 'system', 'view'),
('menu.system.scheduler', '定时任务菜单', 'menu', 'scheduler', 'view'),
('menu.system.notifications', '通知中心菜单', 'menu', 'notifications', 'view'),
('menu.users', '用户管理菜单', 'menu', 'users', 'view'),
('menu.users.list', '用户列表菜单', 'menu', 'users', 'view'),
('menu.users.roles', '角色管理菜单', 'menu', 'roles', 'view');
```

### 3. 初始化页面权限

```sql
INSERT INTO permissions (code, name, type, resource, action) VALUES
('page.dashboard', '首页', 'page', 'dashboard', 'view'),
('page.providers', '供应商列表页', 'page', 'providers', 'view'),
('page.provider_models', '供应商模型关联页', 'page', 'provider_models', 'view'),
('page.models', '模型列表页', 'page', 'models', 'view'),
('page.api_keys', 'API Key列表页', 'page', 'api_keys', 'view'),
('page.logs.requests', '请求日志页', 'page', 'logs', 'view'),
('page.logs.errors', '错误分析页', 'page', 'logs', 'view'),
('page.logs.mcp', 'MCP日志页', 'page', 'logs', 'view'),
('page.stats', '统计分析页', 'page', 'stats', 'view'),
('page.documents', '文档管理页', 'page', 'documents', 'view'),
('page.mcp_servers', 'MCP服务器页', 'page', 'mcp_servers', 'view'),
('page.system.config', '系统配置页', 'page', 'system', 'view'),
('page.system.scheduler', '定时任务页', 'page', 'scheduler', 'view'),
('page.system.notifications', '通知中心页', 'page', 'notifications', 'view'),
('page.users', '用户管理页', 'page', 'users', 'view'),
('page.roles', '角色管理页', 'page', 'roles', 'view');
```

### 4. 初始化元素权限（供应商）

```sql
INSERT INTO permissions (code, name, type, resource, action) VALUES
('provider.create', '创建供应商', 'element', 'provider', 'create'),
('provider.update', '编辑供应商', 'element', 'provider', 'update'),
('provider.delete', '删除供应商', 'element', 'provider', 'delete'),
('provider.toggle', '启用/禁用供应商', 'element', 'provider', 'update'),
('provider.add_key', '添加供应商密钥', 'element', 'provider', 'update'),
('provider.update_key', '编辑供应商密钥', 'element', 'provider', 'update'),
('provider.delete_key', '删除供应商密钥', 'element', 'provider', 'update');
```

### 5. 为角色分配权限（示例：viewer 角色）

```sql
-- viewer 角色只有查看权限
INSERT INTO role_permissions (role_id, permission_id)
SELECT 
    (SELECT id FROM roles WHERE name = 'viewer'),
    id
FROM permissions
WHERE type IN ('menu', 'page')
AND code NOT LIKE '%system%'
AND code NOT LIKE '%users%';
```

## 十一、技术要点

### 1. 权限缓存策略
- 使用 Redis 缓存用户权限，TTL 5分钟
- 角色权限变更时，清除相关用户的权限缓存
- 缓存 key 格式：user:{user_id}:permissions

### 2. 性能优化
- 权限查询使用 JOIN 减少数据库往返
- 前端权限数据存储在 localStorage
- 菜单配置静态化，只在登录时动态过滤

### 3. 安全考虑
- 前端权限控制只是 UI 层面，后端必须验证
- 敏感操作记录审计日志
- 密码使用 bcrypt 加密（12 轮）
- JWT token 有效期 24 小时

### 4. 向后兼容
- 保留现有 dmin_users 配置
- 自动迁移现有 admin 用户到新用户表
- API Key 认证保持不变

## 十二、总结

本方案设计了完整的四层权限体系：

1. **菜单权限** - 控制导航菜单显示
2. **页面权限** - 控制页面路由访问
3. **元素权限** - 控制按钮/操作显示
4. **数据权限** - 控制数据范围（可选）

通过细粒度的权限控制，可以灵活配置不同角色的访问范围，满足企业级应用的权限管理需求。

**预设角色：**
- superadmin：超级管理员，所有权限
- admin：管理员，业务管理权限
- operator：操作员，业务操作权限
- viewer：只读用户，只能查看

**实施周期：11-17 天**


## 十三、管理界面设计

### 1. 用户管理页面 (/admin/users)

#### 1.1 用户列表
- 表格展示：ID、用户名、邮箱、角色、状态、创建时间
- 搜索：按用户名、邮箱搜索
- 筛选：按角色、状态筛选
- 操作按钮：
  - 创建用户（权限：user.create）
  - 编辑（权限：user.update）
  - 删除（权限：user.delete）
  - 分配角色（权限：user.assign_role）
  - 重置密码（权限：user.reset_password）
  - 启用/禁用（权限：user.toggle）

#### 1.2 创建/编辑用户表单
```
字段：
- 用户名（必填，唯一）
- 密码（创建时必填，编辑时可选）
- 邮箱（可选）
- 姓名（可选）
- 角色（多选，下拉框）
- 状态（启用/禁用）
```

#### 1.3 分配角色弹窗
```
- 左侧：所有角色列表（复选框）
- 右侧：已选角色列表
- 支持搜索角色
- 保存按钮
```

### 2. 角色管理页面 (/admin/roles)

#### 2.1 角色列表
- 表格展示：ID、角色名、显示名、描述、用户数、创建时间
- 搜索：按角色名搜索
- 操作按钮：
  - 创建角色（权限：role.create）
  - 编辑（权限：role.update）
  - 删除（权限：role.delete，系统角色不可删除）
  - 分配权限（权限：role.assign_permission）
  - 查看用户（查看拥有该角色的用户）

#### 2.2 创建/编辑角色表单
```
字段：
- 角色代码（必填，唯一，如 operator）
- 显示名称（必填，如"操作员"）
- 描述（可选）
- 是否系统角色（系统角色不可删除）
```

#### 2.3 分配权限弹窗（重点）
```
布局：树形结构 + 复选框

├─ 菜单权限
│  ├─ [✓] 首页菜单 (menu.dashboard)
│  ├─ [✓] 供应商管理 (menu.providers)
│  │  ├─ [✓] 供应商列表 (menu.providers.list)
│  │  └─ [✓] 供应商模型关联 (menu.providers.models)
│  ├─ [✓] 模型管理 (menu.models)
│  └─ ...
├─ 页面权限
│  ├─ [✓] 首页 (page.dashboard)
│  ├─ [✓] 供应商列表页 (page.providers)
│  └─ ...
└─ 元素权限
   ├─ 供应商管理
   │  ├─ [✓] 创建供应商 (provider.create)
   │  ├─ [✓] 编辑供应商 (provider.update)
   │  ├─ [✓] 删除供应商 (provider.delete)
   │  └─ ...
   ├─ 模型管理
   │  ├─ [✓] 创建模型 (model.create)
   │  └─ ...
   └─ ...

功能：
- 支持全选/取消全选
- 支持按权限类型筛选
- 支持搜索权限
- 父子联动（选中父节点自动选中子节点）
- 保存按钮
```

### 3. 菜单管理页面 (/admin/menus)

#### 3.1 菜单列表（树形表格）
```
展示字段：
- 菜单名称（树形结构）
- 图标
- 路径
- 组件
- 权限代码
- 排序
- 是否可见
- 操作

示例：
├─ 首页 (menu.dashboard)
├─ 供应商管理 (menu.providers)
│  ├─ 供应商列表 (menu.providers.list)
│  └─ 供应商模型关联 (menu.providers.models)
├─ 模型管理 (menu.models)
└─ ...
```

#### 3.2 操作按钮
- 创建菜单（权限：menu.create）
- 编辑（权限：menu.update）
- 删除（权限：menu.delete）
- 上移/下移（调整排序）
- 显示/隐藏

#### 3.3 创建/编辑菜单表单
```
字段：
- 父菜单（下拉选择，可为空表示顶级菜单）
- 菜单名称（必填，如"供应商管理"）
- 菜单代码（必填，唯一，如 providers）
- 图标（可选，图标选择器）
- 路径（可选，如 /admin/providers）
- 组件（可选，如 ProvidersPage）
- 权限代码（必填，如 menu.providers）
- 排序（数字，越小越靠前）
- 是否可见（默认可见）
```

### 4. 权限管理页面 (/admin/permissions)

#### 4.1 权限列表
- 分组展示：按资源分组（供应商、模型、API Key...）
- 表格字段：权限代码、名称、类型、资源、操作、描述
- 搜索：按权限代码、名称搜索
- 筛选：按类型（菜单/页面/元素）、资源筛选

#### 4.2 操作按钮
- 创建权限（权限：permission.create）
- 编辑（权限：permission.update）
- 删除（权限：permission.delete）
- 批量导入（从配置文件导入）

#### 4.3 创建/编辑权限表单
```
字段：
- 权限代码（必填，唯一，如 provider.create）
- 权限名称（必填，如"创建供应商"）
- 权限类型（必填，下拉：menu/page/element/data）
- 资源（必填，如 provider）
- 操作（必填，如 create）
- 描述（可选）
```

### 5. 页面布局示例

#### 5.1 用户管理页面布局
```
┌─────────────────────────────────────────────────────────┐
│ 用户管理                                    [+ 创建用户] │
├─────────────────────────────────────────────────────────┤
│ 搜索: [_________]  角色: [全部▼]  状态: [全部▼] [搜索] │
├─────────────────────────────────────────────────────────┤
│ ID │ 用户名 │ 邮箱 │ 角色 │ 状态 │ 创建时间 │ 操作      │
├────┼────────┼──────┼──────┼──────┼──────────┼───────────┤
│ 1  │ admin  │ a@.. │ 管理 │ 启用 │ 2026-... │ [编辑]... │
│ 2  │ user1  │ u@.. │ 操作 │ 启用 │ 2026-... │ [编辑]... │
└─────────────────────────────────────────────────────────┘
```

#### 5.2 角色权限分配弹窗
```
┌─────────────────────────────────────────────────────────┐
│ 为角色"操作员"分配权限                          [✕]     │
├─────────────────────────────────────────────────────────┤
│ 搜索: [_________]  类型: [全部▼]                       │
├─────────────────────────────────────────────────────────┤
│ ☐ 全选                                                  │
│                                                          │
│ ▼ 菜单权限                                              │
│   ☑ 首页菜单 (menu.dashboard)                          │
│   ☑ 供应商管理 (menu.providers)                        │
│     ☑ 供应商列表 (menu.providers.list)                 │
│     ☑ 供应商模型关联 (menu.providers.models)           │
│                                                          │
│ ▼ 页面权限                                              │
│   ☑ 首页 (page.dashboard)                              │
│   ☑ 供应商列表页 (page.providers)                      │
│                                                          │
│ ▼ 元素权限                                              │
│   ▶ 供应商管理                                          │
│   ▶ 模型管理                                            │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                              [取消]  [保存]             │
└─────────────────────────────────────────────────────────┘
```

#### 5.3 菜单管理页面布局
```
┌─────────────────────────────────────────────────────────┐
│ 菜单管理                                    [+ 创建菜单] │
├─────────────────────────────────────────────────────────┤
│ 名称              │ 图标 │ 路径          │ 权限代码 │ 操作│
├───────────────────┼──────┼───────────────┼──────────┼─────┤
│ ▼ 首页            │ 🏠   │ /admin/home   │ menu.... │ ... │
│ ▼ 供应商管理      │ 🖥️   │               │ menu.... │ ... │
│   ├─ 供应商列表   │      │ /admin/prov.. │ menu.... │ ... │
│   └─ 供应商模型.. │      │ /admin/prov.. │ menu.... │ ... │
│ ▼ 模型管理        │ 📦   │ /admin/models │ menu.... │ ... │
└─────────────────────────────────────────────────────────┘
```


## 十四、管理接口设计

### 1. 用户管理接口

#### 1.1 用户列表
```
GET /admin/api/users
Query: page, page_size, search, role_id, is_active
Response: {
  "total": 100,
  "items": [
    {
      "id": 1,
      "username": "admin",
      "email": "admin@example.com",
      "full_name": "管理员",
      "is_active": true,
      "roles": [
        {"id": 1, "name": "admin", "display_name": "管理员"}
      ],
      "created_at": "2026-05-21T10:00:00"
    }
  ]
}
```

#### 1.2 创建用户
```
POST /admin/api/users
Body: {
  "username": "user1",
  "password": "password123",
  "email": "user1@example.com",
  "full_name": "用户1",
  "role_ids": [2, 3]
}
Response: {"id": 2, "username": "user1", ...}
```

#### 1.3 更新用户
```
PUT /admin/api/users/{user_id}
Body: {
  "email": "new@example.com",
  "full_name": "新名字",
  "is_active": true
}
```

#### 1.4 删除用户
```
DELETE /admin/api/users/{user_id}
```

#### 1.5 分配角色
```
PUT /admin/api/users/{user_id}/roles
Body: {
  "role_ids": [1, 2]
}
```

#### 1.6 重置密码
```
POST /admin/api/users/{user_id}/reset-password
Body: {
  "new_password": "newpassword123"
}
```

### 2. 角色管理接口

#### 2.1 角色列表
```
GET /admin/api/roles
Response: {
  "items": [
    {
      "id": 1,
      "name": "admin",
      "display_name": "管理员",
      "description": "业务管理权限",
      "is_system": true,
      "user_count": 5,
      "created_at": "2026-05-21T10:00:00"
    }
  ]
}
```

#### 2.2 创建角色
```
POST /admin/api/roles
Body: {
  "name": "custom_role",
  "display_name": "自定义角色",
  "description": "自定义角色描述"
}
```

#### 2.3 更新角色
```
PUT /admin/api/roles/{role_id}
Body: {
  "display_name": "新名称",
  "description": "新描述"
}
```

#### 2.4 删除角色
```
DELETE /admin/api/roles/{role_id}
注意：系统角色不可删除，有用户关联的角色不可删除
```

#### 2.5 获取角色权限
```
GET /admin/api/roles/{role_id}/permissions
Response: {
  "permissions": [
    {
      "id": 1,
      "code": "menu.dashboard",
      "name": "首页菜单",
      "type": "menu",
      "resource": "dashboard",
      "action": "view"
    }
  ]
}
```

#### 2.6 分配权限
```
PUT /admin/api/roles/{role_id}/permissions
Body: {
  "permission_ids": [1, 2, 3, 4, 5]
}
```

#### 2.7 查看角色用户
```
GET /admin/api/roles/{role_id}/users
Response: {
  "items": [
    {"id": 1, "username": "admin", "email": "..."}
  ]
}
```

### 3. 菜单管理接口

#### 3.1 菜单树
```
GET /admin/api/menus
Response: {
  "items": [
    {
      "id": 1,
      "parent_id": null,
      "name": "dashboard",
      "display_name": "首页",
      "icon": "home",
      "path": "/admin/home",
      "component": "Dashboard",
      "permission_code": "menu.dashboard",
      "sort_order": 1,
      "is_visible": true,
      "children": []
    },
    {
      "id": 2,
      "parent_id": null,
      "name": "providers",
      "display_name": "供应商管理",
      "icon": "server",
      "path": null,
      "permission_code": "menu.providers",
      "sort_order": 2,
      "children": [
        {
          "id": 3,
          "parent_id": 2,
          "name": "providers-list",
          "display_name": "供应商列表",
          "path": "/admin/providers",
          "permission_code": "menu.providers.list",
          "sort_order": 1
        }
      ]
    }
  ]
}
```

#### 3.2 创建菜单
```
POST /admin/api/menus
Body: {
  "parent_id": 2,
  "name": "new-menu",
  "display_name": "新菜单",
  "icon": "folder",
  "path": "/admin/new",
  "component": "NewPage",
  "permission_code": "menu.new",
  "sort_order": 10,
  "is_visible": true
}
```

#### 3.3 更新菜单
```
PUT /admin/api/menus/{menu_id}
Body: {
  "display_name": "新名称",
  "icon": "new-icon",
  "sort_order": 5
}
```

#### 3.4 删除菜单
```
DELETE /admin/api/menus/{menu_id}
注意：有子菜单的不可删除
```

#### 3.5 调整排序
```
PUT /admin/api/menus/{menu_id}/sort
Body: {
  "direction": "up"  // 或 "down"
}
```

### 4. 权限管理接口

#### 4.1 权限列表（分组）
```
GET /admin/api/permissions
Query: type, resource, search
Response: {
  "groups": [
    {
      "resource": "provider",
      "display_name": "供应商管理",
      "permissions": [
        {
          "id": 1,
          "code": "provider.create",
          "name": "创建供应商",
          "type": "element",
          "resource": "provider",
          "action": "create"
        }
      ]
    }
  ]
}
```

#### 4.2 权限树（用于角色分配）
```
GET /admin/api/permissions/tree
Response: {
  "tree": [
    {
      "label": "菜单权限",
      "type": "menu",
      "children": [
        {
          "id": 1,
          "label": "首页菜单 (menu.dashboard)",
          "code": "menu.dashboard"
        }
      ]
    },
    {
      "label": "页面权限",
      "type": "page",
      "children": [...]
    },
    {
      "label": "元素权限",
      "type": "element",
      "children": [
        {
          "label": "供应商管理",
          "children": [
            {
              "id": 10,
              "label": "创建供应商 (provider.create)",
              "code": "provider.create"
            }
          ]
        }
      ]
    }
  ]
}
```

#### 4.3 创建权限
```
POST /admin/api/permissions
Body: {
  "code": "custom.action",
  "name": "自定义操作",
  "type": "element",
  "resource": "custom",
  "action": "action",
  "description": "描述"
}
```

#### 4.4 更新权限
```
PUT /admin/api/permissions/{permission_id}
Body: {
  "name": "新名称",
  "description": "新描述"
}
```

#### 4.5 删除权限
```
DELETE /admin/api/permissions/{permission_id}
注意：有角色关联的权限不可删除
```

#### 4.6 批量导入权限
```
POST /admin/api/permissions/import
Body: {
  "permissions": [
    {
      "code": "new.permission",
      "name": "新权限",
      "type": "element",
      "resource": "new",
      "action": "create"
    }
  ]
}
```


## 十五、动态菜单实现方案

### 1. 后端菜单接口

#### 1.1 获取用户菜单
```python
@router.get("/api/user/menus")
async def get_user_menus(user_id: int = Depends(get_current_user)):
    '''获取当前用户的菜单树'''
    async with async_session_maker() as session:
        # 1. 获取用户权限
        permissions = await query_user_permissions(user_id)
        menu_permissions = set(permissions['menus'])
        
        # 2. 查询所有可见菜单
        result = await session.execute(
            select(Menu)
            .where(Menu.is_visible == True)
            .order_by(Menu.sort_order)
        )
        all_menus = result.scalars().all()
        
        # 3. 过滤用户有权限的菜单
        def filter_menus(menus, parent_id=None):
            filtered = []
            for menu in menus:
                if menu.parent_id != parent_id:
                    continue
                
                # 检查权限
                if menu.permission_code and menu.permission_code not in menu_permissions:
                    continue
                
                # 递归处理子菜单
                children = filter_menus(menus, menu.id)
                
                menu_dict = {
                    "id": menu.id,
                    "name": menu.name,
                    "display_name": menu.display_name,
                    "icon": menu.icon,
                    "path": menu.path,
                    "component": menu.component,
                    "children": children
                }
                filtered.append(menu_dict)
            
            return filtered
        
        menu_tree = filter_menus(all_menus)
        return {"menus": menu_tree}
```

### 2. 前端动态菜单渲染

#### 2.1 获取菜单数据
```javascript
// 登录后获取菜单
async function loadUserMenus() {
  const response = await fetch('/api/user/menus', {
    headers: {
      'Authorization': Bearer 
    }
  });
  const data = await response.json();
  
  // 存储到 Vuex/Pinia
  store.commit('setMenus', data.menus);
  
  // 或存储到 localStorage
  localStorage.setItem('user_menus', JSON.stringify(data.menus));
}
```

#### 2.2 递归渲染菜单组件
```vue
<!-- MenuTree.vue -->
<template>
  <div class="menu-tree">
    <template v-for="menu in menus" :key="menu.id">
      <!-- 有子菜单 -->
      <div v-if="menu.children && menu.children.length > 0" class="menu-group">
        <div class="menu-title" @click="toggleMenu(menu.id)">
          <i :class="menu.icon"></i>
          <span>{{ menu.display_name }}</span>
          <i class="arrow" :class="{ expanded: expandedMenus.includes(menu.id) }"></i>
        </div>
        <div v-show="expandedMenus.includes(menu.id)" class="menu-children">
          <MenuTree :menus="menu.children" />
        </div>
      </div>
      
      <!-- 无子菜单 -->
      <router-link v-else :to="menu.path" class="menu-item">
        <i :class="menu.icon"></i>
        <span>{{ menu.display_name }}</span>
      </router-link>
    </template>
  </div>
</template>

<script>
export default {
  name: 'MenuTree',
  props: {
    menus: {
      type: Array,
      required: true
    }
  },
  data() {
    return {
      expandedMenus: []
    };
  },
  methods: {
    toggleMenu(menuId) {
      const index = this.expandedMenus.indexOf(menuId);
      if (index > -1) {
        this.expandedMenus.splice(index, 1);
      } else {
        this.expandedMenus.push(menuId);
      }
    }
  }
};
</script>
```

#### 2.3 主布局使用菜单组件
```vue
<!-- Layout.vue -->
<template>
  <div class="admin-layout">
    <aside class="sidebar">
      <div class="logo">ModelGate</div>
      <MenuTree :menus="userMenus" />
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script>
import MenuTree from './MenuTree.vue';
import { mapState } from 'vuex';

export default {
  components: { MenuTree },
  computed: {
    ...mapState(['userMenus'])
  },
  async created() {
    // 如果没有菜单数据，加载
    if (!this.userMenus || this.userMenus.length === 0) {
      await this..dispatch('loadUserMenus');
    }
  }
};
</script>
```

### 3. 菜单图标选择器

#### 3.1 图标库
```javascript
// icons.js
export const iconList = [
  { name: 'home', label: '首页', icon: '🏠' },
  { name: 'server', label: '服务器', icon: '🖥️' },
  { name: 'database', label: '数据库', icon: '💾' },
  { name: 'key', label: '密钥', icon: '🔑' },
  { name: 'file', label: '文件', icon: '📄' },
  { name: 'chart', label: '图表', icon: '📊' },
  { name: 'settings', label: '设置', icon: '⚙️' },
  { name: 'users', label: '用户', icon: '👥' },
  { name: 'log', label: '日志', icon: '📝' },
  { name: 'folder', label: '文件夹', icon: '📁' },
  // 或使用 Font Awesome / Element Plus 图标
];
```

#### 3.2 图标选择器组件
```vue
<!-- IconPicker.vue -->
<template>
  <div class="icon-picker">
    <div class="selected-icon" @click="showPicker = true">
      <i :class="modelValue"></i>
      <span>选择图标</span>
    </div>
    
    <div v-if="showPicker" class="icon-picker-popup">
      <div class="icon-search">
        <input v-model="search" placeholder="搜索图标..." />
      </div>
      <div class="icon-grid">
        <div
          v-for="icon in filteredIcons"
          :key="icon.name"
          class="icon-item"
          :class="{ active: modelValue === icon.name }"
          @click="selectIcon(icon.name)"
        >
          <i :class="icon.icon"></i>
          <span>{{ icon.label }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { iconList } from './icons';

export default {
  props: {
    modelValue: String
  },
  data() {
    return {
      showPicker: false,
      search: '',
      iconList
    };
  },
  computed: {
    filteredIcons() {
      if (!this.search) return this.iconList;
      return this.iconList.filter(icon =>
        icon.label.includes(this.search) || icon.name.includes(this.search)
      );
    }
  },
  methods: {
    selectIcon(iconName) {
      this.('update:modelValue', iconName);
      this.showPicker = false;
    }
  }
};
</script>
```

### 4. 菜单管理页面完整实现

#### 4.1 菜单管理页面
```vue
<!-- MenuManagement.vue -->
<template>
  <div class="menu-management">
    <div class="header">
      <h2>菜单管理</h2>
      <button @click="showCreateDialog = true" v-permission="'menu.create'">
        创建菜单
      </button>
    </div>
    
    <el-table :data="menuTree" row-key="id" :tree-props="{ children: 'children' }">
      <el-table-column prop="display_name" label="菜单名称" width="200" />
      <el-table-column prop="icon" label="图标" width="80">
        <template #default="{ row }">
          <i :class="row.icon"></i>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="路径" />
      <el-table-column prop="permission_code" label="权限代码" />
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column label="可见" width="80">
        <template #default="{ row }">
          <el-switch v-model="row.is_visible" @change="updateMenu(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <button @click="editMenu(row)" v-permission="'menu.update'">编辑</button>
          <button @click="moveUp(row)" v-permission="'menu.update'">上移</button>
          <button @click="moveDown(row)" v-permission="'menu.update'">下移</button>
          <button @click="deleteMenu(row)" v-permission="'menu.delete'">删除</button>
        </template>
      </el-table-column>
    </el-table>
    
    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="showCreateDialog" title="创建菜单">
      <el-form :model="form" label-width="100px">
        <el-form-item label="父菜单">
          <el-tree-select
            v-model="form.parent_id"
            :data="menuTreeOptions"
            placeholder="选择父菜单（留空为顶级菜单）"
          />
        </el-form-item>
        <el-form-item label="菜单名称">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="菜单代码">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="图标">
          <IconPicker v-model="form.icon" />
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="form.path" />
        </el-form-item>
        <el-form-item label="组件">
          <el-input v-model="form.component" />
        </el-form-item>
        <el-form-item label="权限代码">
          <el-input v-model="form.permission_code" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" />
        </el-form-item>
        <el-form-item label="是否可见">
          <el-switch v-model="form.is_visible" />
        </el-form-item>
      </el-form>
      <template #footer>
        <button @click="showCreateDialog = false">取消</button>
        <button @click="saveMenu">保存</button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
export default {
  data() {
    return {
      menuTree: [],
      showCreateDialog: false,
      form: {
        parent_id: null,
        name: '',
        display_name: '',
        icon: '',
        path: '',
        component: '',
        permission_code: '',
        sort_order: 0,
        is_visible: true
      }
    };
  },
  async created() {
    await this.loadMenus();
  },
  methods: {
    async loadMenus() {
      const response = await fetch('/admin/api/menus');
      const data = await response.json();
      this.menuTree = data.items;
    },
    async saveMenu() {
      await fetch('/admin/api/menus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.form)
      });
      this.showCreateDialog = false;
      await this.loadMenus();
    }
  }
};
</script>
```

## 十六、完整实施清单

### 数据库层
- [ ] 创建 users 表
- [ ] 创建 roles 表
- [ ] 创建 user_roles 表
- [ ] 创建 menus 表
- [ ] 创建 permissions 表
- [ ] 创建 role_permissions 表
- [ ] 初始化预设角色数据
- [ ] 初始化菜单数据
- [ ] 初始化权限数据
- [ ] 为预设角色分配权限

### 后端接口层
- [ ] 用户管理接口（CRUD、分配角色、重置密码）
- [ ] 角色管理接口（CRUD、分配权限、查看用户）
- [ ] 菜单管理接口（CRUD、排序、树形结构）
- [ ] 权限管理接口（CRUD、树形结构、批量导入）
- [ ] 用户菜单接口（动态菜单）
- [ ] 用户权限接口（权限列表）
- [ ] 权限检查装饰器
- [ ] 权限缓存机制
- [ ] 为现有接口添加权限检查

### 前端页面层
- [ ] 用户管理页面
- [ ] 角色管理页面
- [ ] 菜单管理页面
- [ ] 权限管理页面
- [ ] 角色权限分配弹窗（树形结构）
- [ ] 用户角色分配弹窗
- [ ] 图标选择器组件
- [ ] 动态菜单组件
- [ ] 路由守卫
- [ ] 权限指令（v-permission）
- [ ] 为现有页面添加元素权限控制

### 测试验证
- [ ] 测试 viewer 角色权限
- [ ] 测试 operator 角色权限
- [ ] 测试 admin 角色权限
- [ ] 测试菜单动态渲染
- [ ] 测试路由守卫
- [ ] 测试元素权限控制
- [ ] 性能测试（权限缓存）

