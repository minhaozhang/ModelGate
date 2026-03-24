# 路由重构清单

## 目标
- 管理端统一 `/admin` 前缀
- 用户端保持 `/user` 前缀（已规范）
- 公开接口保持 `/v1`、`/opencode`

---

## 一、页面路由改动

### 管理端页面（pages.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `/` | `/admin/` | routes/pages.py |
| `/login` | `/admin/login` | routes/pages.py |
| `/home` | `/admin/home` | routes/pages.py |
| `/config` | `/admin/config` | routes/pages.py |
| `/api-keys` | `/admin/api-keys` | routes/pages.py |
| `/monitor` | `/admin/monitor` | routes/pages.py |
| `/usage` | `/admin/usage` | routes/pages.py |
| `/dashboard` | `/admin/dashboard` | routes/pages.py |

### 用户端页面（user.py）- 已规范，无需改动

| 当前路由 | 状态 |
|---------|------|
| `/user/login` | ✅ 已规范 |
| `/user/dashboard` | ✅ 已规范 |

---

## 二、API 接口改动

### 认证接口（auth.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `POST /api/login` | `POST /admin/api/auth/login` | routes/auth.py |
| `POST /api/logout` | `POST /admin/api/auth/logout` | routes/auth.py |
| `GET /api/check-auth` | `GET /admin/api/auth/check` | routes/auth.py |

### API Key 管理接口（keys.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `GET /api/keys` | `GET /admin/api/keys` | routes/keys.py |
| `POST /api/keys` | `POST /admin/api/keys` | routes/keys.py |
| `PUT /api/keys/{key_id}` | `PUT /admin/api/keys/{key_id}` | routes/keys.py |
| `DELETE /api/keys/{key_id}` | `DELETE /admin/api/keys/{key_id}` | routes/keys.py |
| `GET /api-keys/{key_id}/stats` | `GET /admin/api/keys/{key_id}/stats` | routes/keys.py |
| `GET /api-keys/{key_id}/logs` | `GET /admin/api/keys/{key_id}/logs` | routes/keys.py |

### Provider 管理接口（providers.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `GET /providers` | `GET /admin/api/providers` | routes/providers.py |
| `POST /providers` | `POST /admin/api/providers` | routes/providers.py |
| `PUT /providers/{provider_id}` | `PUT /admin/api/providers/{provider_id}` | routes/providers.py |
| `DELETE /providers/{provider_id}` | `DELETE /admin/api/providers/{provider_id}` | routes/providers.py |

### Provider Models 管理接口（provider_models.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `GET /provider-models` | `GET /admin/api/provider-models` | routes/provider_models.py |
| `GET /providers/{provider_id}/models` | `GET /admin/api/providers/{provider_id}/models` | routes/provider_models.py |
| `POST /providers/{provider_id}/models` | `POST /admin/api/providers/{provider_id}/models` | routes/provider_models.py |
| `PUT /providers/{provider_id}/models/{pm_id}` | `PUT /admin/api/providers/{provider_id}/models/{pm_id}` | routes/provider_models.py |
| `DELETE /providers/{provider_id}/models/{pm_id}` | `DELETE /admin/api/providers/{provider_id}/models/{pm_id}` | routes/provider_models.py |
| `POST /providers/{provider_id}/sync-models` | `POST /admin/api/providers/{provider_id}/sync-models` | routes/provider_models.py |

### Model 管理接口（models.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `GET /admin/models` | `GET /admin/api/models` | routes/models.py |
| `POST /admin/models` | `POST /admin/api/models` | routes/models.py |
| `PUT /admin/models/{model_id}` | `PUT /admin/api/models/{model_id}` | routes/models.py |
| `DELETE /admin/models/{model_id}` | `DELETE /admin/api/models/{model_id}` | routes/models.py |

### 日志接口（logs.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `GET /logs/today` | `GET /admin/api/logs/today` | routes/logs.py |
| `GET /logs/all` | `GET /admin/api/logs/all` | routes/logs.py |

### 统计接口（stats.py）

| 当前路由 | 新路由 | 文件改动 |
|---------|--------|---------|
| `GET /stats` | `GET /admin/api/stats` | routes/stats.py |
| `GET /stats/aggregate` | `GET /admin/api/stats/aggregate` | routes/stats.py |
| `GET /stats/trend` | `GET /admin/api/stats/trend` | routes/stats.py |
| `GET /stats/period` | `GET /admin/api/stats/period` | routes/stats.py |
| `GET /stats/chart` | `GET /admin/api/stats/chart` | routes/stats.py |
| `POST /stats/reaggregate` | `POST /admin/api/stats/reaggregate` | routes/stats.py |
| `GET /stats/active` | `GET /admin/api/stats/active` | routes/stats.py |
| `GET /stats/active/models` | `GET /admin/api/stats/active/models` | routes/stats.py |
| `GET /stats/realtime` | `GET /admin/api/stats/realtime` | routes/stats.py |
| `GET /stats/slow` | `GET /admin/api/stats/slow` | routes/stats.py |

### 用户端接口（user.py）- 已规范，无需改动

| 当前路由 | 状态 |
|---------|------|
| `POST /user/api/login` | ✅ 已规范 |
| `POST /user/api/logout` | ✅ 已规范 |
| `GET /user/api/stats` | ✅ 已规范 |
| `GET /user/api/active` | ✅ 已规范 |
| `GET /user/api/opencode-config` | ✅ 已规范 |

### 公开接口 - 无需改动

| 当前路由 | 状态 |
|---------|------|
| `GET /v1/*` | ✅ 代理接口，保持不变 |
| `GET /opencode/setup.md` | ✅ 公开文档，保持不变 |

---

## 三、前端页面改动

### templates/home.py
- 所有 fetch 调用需要更新路径
- `/stats/period` → `/admin/api/stats/period`
- `/stats/chart` → `/admin/api/stats/chart`
- `/stats/active` → `/admin/api/stats/active`
- `/stats/realtime` → `/admin/api/stats/realtime`
- `/stats/slow` → `/admin/api/stats/slow`

### templates/config.py
- `/providers` → `/admin/api/providers`
- `/admin/models` → `/admin/api/models`
- `/provider-models` → `/admin/api/provider-models`
- `/providers/{id}/models` → `/admin/api/providers/{id}/models`
- `/providers/{id}/sync-models` → `/admin/api/providers/{id}/sync-models`

### templates/api_keys.py
- `/api/keys` → `/admin/api/keys`

### templates/monitor.py
- `/logs/today` → `/admin/api/logs/today`

### templates/usage.py
- `/stats/*` → `/admin/api/stats/*`

### templates/dashboard.py
- `/stats` → `/admin/api/stats`
- `/stats/active/models` → `/admin/api/stats/active/models`
- `/logs/all` → `/admin/api/logs/all`

### routes/pages.py 中的导航链接
- `/home` → `/admin/home`
- `/config` → `/admin/config`
- `/api-keys` → `/admin/api-keys`
- `/monitor` → `/admin/monitor`
- `/usage` → `/admin/usage`
- `/dashboard` → `/admin/dashboard`
- `/login` → `/admin/login`
- `/` → `/admin/`

---

## 四、实施步骤

### 第一阶段：修改路由定义
1. routes/auth.py - 添加 `/admin/api/auth` 前缀
2. routes/keys.py - 添加 `/admin/api` 前缀
3. routes/providers.py - 添加 `/admin/api` 前缀
4. routes/provider_models.py - 添加 `/admin/api` 前缀
5. routes/models.py - 修改为 `/admin/api/models`
6. routes/logs.py - 添加 `/admin/api` 前缀
7. routes/stats.py - 添加 `/admin/api` 前缀
8. routes/pages.py - 添加 `/admin` 前缀

### 第二阶段：修改前端调用
1. templates/home.py
2. templates/config.py
3. templates/api_keys.py
4. templates/monitor.py
5. templates/usage.py
6. templates/dashboard.py

### 第三阶段：修改导航链接
1. 所有页面中的导航链接
2. 登录成功后的跳转
3. 登出后的跳转

### 第四阶段：测试
1. 测试所有管理端页面
2. 测试所有 API 接口
3. 测试用户端（确保不受影响）
4. 测试代理接口（确保不受影响）

---

## 五、文件改动汇总

### 路由文件（需修改）
- routes/auth.py
- routes/keys.py
- routes/providers.py
- routes/provider_models.py
- routes/models.py
- routes/logs.py
- routes/stats.py
- routes/pages.py

### 模板文件（需修改）
- templates/home.py
- templates/config.py
- templates/api_keys.py
- templates/monitor.py
- templates/usage.py
- templates/dashboard.py

### 无需改动
- routes/user.py（已规范）
- routes/proxy.py（代理接口）
- routes/opencode.py（公开文档）
- templates/user_dashboard.py（用户端）

---

## 六、目录结构重构

### 当前结构

```
api-proxy/
├── main.py              # 入口
├── config.py            # 配置（根目录）
├── database.py          # 数据库（根目录）
├── deps.py              # 依赖（根目录）
├── routes/              # 路由
│   ├── auth.py
│   ├── keys.py
│   └── ...
├── services/            # 服务
│   └── ...
└── templates/           # 模板（混合）
    ├── home.py          # 管理端
    ├── config.py        # 管理端
    ├── api_keys.py      # 管理端
    ├── monitor.py       # 管理端
    ├── usage.py         # 管理端
    ├── dashboard.py     # 管理端
    ├── login.py         # 管理端
    ├── opencode.py      # 公开
    ├── query.py         # 公开
    └── user_dashboard.py# 用户端
```

### 目标结构

```
api-proxy/
├── main.py              # 入口（唯一保留在根目录）
├── core/                # 核心模块（新建）
│   ├── __init__.py
│   ├── config.py        # 配置
│   ├── database.py      # 数据库
│   └── deps.py          # 依赖
├── routes/              # 路由（保持不变）
│   ├── auth.py
│   ├── keys.py
│   └── ...
├── services/            # 服务（保持不变）
│   └── ...
├── templates/           # 模板（重新组织）
│   ├── admin/           # 管理端模板（新建）
│   │   ├── __init__.py
│   │   ├── home.py
│   │   ├── config.py
│   │   ├── api_keys.py
│   │   ├── monitor.py
│   │   ├── usage.py
│   │   ├── dashboard.py
│   │   └── login.py
│   ├── user/            # 用户端模板（新建）
│   │   ├── __init__.py
│   │   └── dashboard.py
│   └── public/          # 公开模板（新建）
│       ├── __init__.py
│       ├── opencode.py
│       └── query.py
├── logs/                # 日志目录
├── requirements.txt
├── Dockerfile
└── ...
```

### 文件移动

#### 核心模块

| 当前位置 | 新位置 | 改动类型 |
|---------|--------|---------|
| `config.py` | `core/config.py` | 移动 |
| `database.py` | `core/database.py` | 移动 |
| `deps.py` | `core/deps.py` | 移动 |
| - | `core/__init__.py` | 新建 |

#### 模板文件

| 当前位置 | 新位置 | 分类 |
|---------|--------|------|
| `templates/home.py` | `templates/admin/home.py` | 管理端 |
| `templates/config.py` | `templates/admin/config.py` | 管理端 |
| `templates/api_keys.py` | `templates/admin/api_keys.py` | 管理端 |
| `templates/monitor.py` | `templates/admin/monitor.py` | 管理端 |
| `templates/usage.py` | `templates/admin/usage.py` | 管理端 |
| `templates/dashboard.py` | `templates/admin/dashboard.py` | 管理端 |
| `templates/login.py` | `templates/admin/login.py` | 管理端 |
| `templates/user_dashboard.py` | `templates/user/dashboard.py` | 用户端 |
| `templates/opencode.py` | `templates/public/opencode.py` | 公开 |
| `templates/query.py` | `templates/public/query.py` | 公开 |
| - | `templates/admin/__init__.py` | 新建 |
| - | `templates/user/__init__.py` | 新建 |
| - | `templates/public/__init__.py` | 新建 |

### import 语句改动

#### main.py
```python
# 改动前
from config import ...
from database import ...

# 改动后
from core.config import ...
from core.database import ...
```

#### routes/*.py
```python
# 改动前
from config import ...
from database import ...
from deps import ...

# 改动后
from core.config import ...
from core.database import ...
from core.deps import ...
```

#### services/*.py
```python
# 改动前
from config import ...
from database import ...

# 改动后
from core.config import ...
from core.database import ...
```

#### templates/*.py
```python
# 改动前
from config import ...

# 改动后
from core.config import ...
```

### 需要修改 import 的文件

#### main.py
```python
# 改动前
from config import ...
from database import ...

# 改动后
from core.config import ...
from core.database import ...
```

#### routes/*.py
```python
# 改动前
from config import ...
from database import ...
from deps import ...

# 改动后
from core.config import ...
from core.database import ...
from core.deps import ...
```

#### services/*.py
```python
# 改动前
from config import ...
from database import ...

# 改动后
from core.config import ...
from core.database import ...
```

#### templates/*/*.py
```python
# 改动前
from config import ...

# 改动后
from core.config import ...
```

---

## 七、注意事项

1. **向后兼容**：如果已有外部系统调用这些 API，需要考虑兼容性
2. **部署顺序**：前端和后端需要同时部署，否则会出现 404
3. **Session Cookie**：确保 Cookie 的 path 设置正确
4. **CORS**：如果有跨域请求，需要更新 CORS 配置

---

## 八、实施顺序建议

### 方案一：先重构目录，再重构路由（推荐）
1. 创建 `core/` 目录
2. 移动文件并更新所有 import
3. 测试确保功能正常
4. 提交代码
5. 再进行路由重构

### 方案二：一次性重构
- 同时修改目录结构和路由
- 风险较高，容易遗漏

---

## 九、完整改动文件清单

### 第一阶段：目录重构 (31个文件)

#### 新建文件 (7个)
- `core/__init__.py`
- `templates/admin/__init__.py`
- `templates/user/__init__.py`
- `templates/public/__init__.py`

#### 移动文件 (13个)

**核心模块移动 (3个)**
- `config.py` → `core/config.py`
- `database.py` → `core/database.py`
- `deps.py` → `core/deps.py`

**模板文件移动 (10个)**
- `templates/home.py` → `templates/admin/home.py`
- `templates/config.py` → `templates/admin/config.py`
- `templates/api_keys.py` → `templates/admin/api_keys.py`
- `templates/monitor.py` → `templates/admin/monitor.py`
- `templates/usage.py` → `templates/admin/usage.py`
- `templates/dashboard.py` → `templates/admin/dashboard.py`
- `templates/login.py` → `templates/admin/login.py`
- `templates/user_dashboard.py` → `templates/user/dashboard.py`
- `templates/opencode.py` → `templates/public/opencode.py`
- `templates/query.py` → `templates/public/query.py`

#### 修改 import (31个文件)

**根目录 (1个)**
- main.py

**路由文件 (11个)**
- routes/auth.py
- routes/keys.py
- routes/logs.py
- routes/models.py
- routes/opencode.py
- routes/pages.py
- routes/provider_models.py
- routes/providers.py
- routes/proxy.py
- routes/stats.py
- routes/user.py

**服务文件 (3个)**
- services/proxy.py
- services/scheduler.py
- services/stats_aggregator.py

**模板文件 (10个，移动后)**
- templates/admin/home.py
- templates/admin/config.py
- templates/admin/api_keys.py
- templates/admin/monitor.py
- templates/admin/usage.py
- templates/admin/dashboard.py
- templates/admin/login.py
- templates/user/dashboard.py
- templates/public/opencode.py
- templates/public/query.py

---

### 第二阶段：路由重构 (14个文件)

**路由文件 (8个)**
- routes/auth.py - 添加 `/admin/api/auth` 前缀
- routes/keys.py - 添加 `/admin/api` 前缀
- routes/providers.py - 添加 `/admin/api` 前缀
- routes/provider_models.py - 添加 `/admin/api` 前缀
- routes/models.py - 修改为 `/admin/api/models`
- routes/logs.py - 添加 `/admin/api` 前缀
- routes/stats.py - 添加 `/admin/api` 前缀
- routes/pages.py - 添加 `/admin` 前缀

**模板文件 (6个，新路径)**
- templates/admin/home.py
- templates/admin/config.py
- templates/admin/api_keys.py
- templates/admin/monitor.py
- templates/admin/usage.py
- templates/admin/dashboard.py
