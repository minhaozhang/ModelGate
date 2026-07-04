# 文档分享功能 — 设计文档

## 概述

为 ModelGate 添加文档分享功能，管理员可上传、编辑、删除 Markdown 文档，用户登录后可浏览和阅读已发布文档。

## 需求

- 管理员上传 .md 文件或在线创建文档（标题、内容、分类）
- 管理员可编辑文档标题、内容、分类，可删除文档
- 管理员可控制文档发布/取消发布状态
- 用户登录后可查看已发布文档列表，按分类筛选
- 用户可阅读文档详情，Markdown 渲染展示
- 文档原始文件备份到 `uploads/documents/` 目录

## 数据模型

### documents 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| title | String(200) | 文档标题 |
| slug | String(200) unique | URL 友好标识 |
| content | Text | Markdown 正文 |
| category | String(50) | 分类标签 |
| filename | String(255) nullable | 原始上传文件名 |
| is_published | Boolean default False | 是否发布 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

## 路由设计

### Admin（需管理员登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/documents` | 文档管理页面 |
| GET | `/admin/api/documents` | 文档列表 API |
| POST | `/admin/api/documents` | 创建文档（表单提交） |
| PUT | `/admin/api/documents/{id}` | 更新文档 |
| DELETE | `/admin/api/documents/{id}` | 删除文档 |
| POST | `/admin/api/documents/upload` | 上传 .md 文件 |

### User（需 API Key 登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/documents` | 文档列表页面 |
| GET | `/user/documents/{id}` | 文档详情页面 |
| GET | `/user/api/documents` | 文档列表 API（仅已发布） |

## 架构

### 数据流

```
Admin 上传/创建 → POST /admin/api/documents
→ 验证 .md 文件或表单数据
→ 写入 documents 表 + 保存原始文件到 uploads/documents/
→ 返回文档信息

User 查看列表 → GET /user/documents
→ 查询 is_published=True 的文档
→ 按 category 分组展示

User 查看详情 → GET /user/documents/{id}
→ 查询文档 content
→ 前端 marked.js 渲染 Markdown
```

### 文件结构

```
uploads/documents/          # .md 原始文件备份
modelgate/
├── routes/
│   └── documents.py        # Admin CRUD API + 文件上传
├── services/
│   └── documents.py        # 文档业务逻辑
├── templates/
│   ├── admin/
│   │   └── documents.html  # Admin 文档管理页
│   └── user/
│       ├── documents.html  # 用户文档列表页
│       └── document_detail.html  # 用户文档详情页
```

### 现有文件修改

| 文件 | 修改内容 |
|------|----------|
| `core/database.py` | 新增 Document ORM 模型 |
| `routes/pages.py` | 新增 `/admin/documents` 页面路由 |
| `routes/user.py` | 新增 `/user/documents` 和 `/user/documents/{id}` 页面路由 |
| `main.py` | 注册 documents 路由 |
| `locales/zh/LC_MESSAGES/messages.po` | 中文翻译 |
| `locales/en/LC_MESSAGES/messages.po` | 英文翻译 |

## 前端

- Admin 管理页：文档列表 + 创建/编辑弹窗 + 删除确认，使用 Tailwind CSS
- 用户列表页：卡片式文档列表，分类筛选，与用户端现有风格一致
- 用户详情页：Markdown 渲染（marked.js），支持代码高亮
- 暗色主题支持（跟随用户端现有暗色主题）

## 约束

- 仅接受 .md 文件上传，最大 1MB
- slug 自动从标题生成（拼音或英文），重复时追加数字
- 文档内容以数据库为准，文件系统仅作备份
- 删除文档时同时删除备份文件
