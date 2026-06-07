"""
初始化 RBAC 数据（角色、权限、菜单）

运行前提：
1. 数据库已启动
2. 已运行 add_rbac_tables.py 创建表结构
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from core.database import engine
import asyncio


async def init_roles():
    """初始化预设角色"""
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO roles (name, display_name, description, is_system) VALUES
            ('superadmin', '超级管理员', '拥有所有权限，不受限制', true),
            ('admin', '管理员', '业务管理权限，可管理用户', true),
            ('operator', '操作员', '业务操作权限，不能管理用户和系统配置', true),
            ('viewer', '只读用户', '只能查看，不能操作', true)
            ON CONFLICT (name) DO NOTHING;
        """))
        print("✓ 角色初始化完成")


async def init_menu_permissions():
    """初始化菜单权限"""
    async with engine.begin() as conn:
        await conn.execute(text("""
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
            ('menu.users.roles', '角色管理菜单', 'menu', 'roles', 'view')
            ON CONFLICT (code) DO NOTHING;
        """))
        print("✓ 菜单权限初始化完成")


async def init_page_permissions():
    """初始化页面权限"""
    async with engine.begin() as conn:
        await conn.execute(text("""
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
            ('page.roles', '角色管理页', 'page', 'roles', 'view')
            ON CONFLICT (code) DO NOTHING;
        """))
        print("✓ 页面权限初始化完成")


async def init_element_permissions():
    """初始化元素权限（操作按钮）"""
    async with engine.begin() as conn:
        # 供应商管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('provider.create', '创建供应商', 'element', 'provider', 'create'),
            ('provider.update', '编辑供应商', 'element', 'provider', 'update'),
            ('provider.delete', '删除供应商', 'element', 'provider', 'delete'),
            ('provider.toggle', '启用/禁用供应商', 'element', 'provider', 'update'),
            ('provider.add_key', '添加供应商密钥', 'element', 'provider', 'update'),
            ('provider.update_key', '编辑供应商密钥', 'element', 'provider', 'update'),
            ('provider.delete_key', '删除供应商密钥', 'element', 'provider', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 模型管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('model.create', '创建模型', 'element', 'model', 'create'),
            ('model.update', '编辑模型', 'element', 'model', 'update'),
            ('model.delete', '删除模型', 'element', 'model', 'delete'),
            ('model.bind_key', '关联API Key', 'element', 'model', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # API Key 管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('api_key.create', '创建密钥', 'element', 'api_key', 'create'),
            ('api_key.update', '编辑密钥', 'element', 'api_key', 'update'),
            ('api_key.delete', '删除密钥', 'element', 'api_key', 'delete'),
            ('api_key.toggle', '启用/禁用密钥', 'element', 'api_key', 'update'),
            ('api_key.add_time_rule', '添加时间规则', 'element', 'api_key', 'update'),
            ('api_key.update_time_rule', '编辑时间规则', 'element', 'api_key', 'update'),
            ('api_key.delete_time_rule', '删除时间规则', 'element', 'api_key', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 供应商模型关联
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('provider_model.create', '添加关联', 'element', 'provider_model', 'create'),
            ('provider_model.update', '编辑关联', 'element', 'provider_model', 'update'),
            ('provider_model.delete', '删除关联', 'element', 'provider_model', 'delete'),
            ('provider_model.sync', '同步模型', 'element', 'provider_model', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 日志管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('log.delete', '删除日志', 'element', 'log', 'delete'),
            ('log.export', '导出日志', 'element', 'log', 'read'),
            ('log.analyze', '错误分析', 'element', 'log', 'read'),
            ('log.create_report', '创建分析报告', 'element', 'log', 'create')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 系统配置
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('system_config.update', '保存系统配置', 'element', 'system_config', 'update'),
            ('scheduler.trigger', '手动触发任务', 'element', 'scheduler', 'update'),
            ('scheduler.update', '编辑定时任务', 'element', 'scheduler', 'update'),
            ('notification.mark_read', '标记通知已读', 'element', 'notification', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 文档管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('document.create', '创建文档', 'element', 'document', 'create'),
            ('document.update', '编辑文档', 'element', 'document', 'update'),
            ('document.delete', '删除文档', 'element', 'document', 'delete'),
            ('document.upload', '上传附件', 'element', 'document', 'create'),
            ('document.delete_file', '删除附件', 'element', 'document', 'delete')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # MCP 服务器
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('mcp_server.create', '创建MCP服务器', 'element', 'mcp_server', 'create'),
            ('mcp_server.update', '编辑MCP服务器', 'element', 'mcp_server', 'update'),
            ('mcp_server.delete', '删除MCP服务器', 'element', 'mcp_server', 'delete'),
            ('mcp_server.sync', '同步工具', 'element', 'mcp_server', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 用户管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('user.create', '创建用户', 'element', 'user', 'create'),
            ('user.update', '编辑用户', 'element', 'user', 'update'),
            ('user.delete', '删除用户', 'element', 'user', 'delete'),
            ('user.assign_role', '分配角色', 'element', 'user', 'update'),
            ('user.reset_password', '重置密码', 'element', 'user', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 角色管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('role.create', '创建角色', 'element', 'role', 'create'),
            ('role.update', '编辑角色', 'element', 'role', 'update'),
            ('role.delete', '删除角色', 'element', 'role', 'delete'),
            ('role.assign_permission', '分配权限', 'element', 'role', 'update')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 菜单管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('menu.create', '创建菜单', 'element', 'menu', 'create'),
            ('menu.update', '编辑菜单', 'element', 'menu', 'update'),
            ('menu.delete', '删除菜单', 'element', 'menu', 'delete')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        # 权限管理
        await conn.execute(text("""
            INSERT INTO permissions (code, name, type, resource, action) VALUES
            ('permission.create', '创建权限', 'element', 'permission', 'create'),
            ('permission.update', '编辑权限', 'element', 'permission', 'update'),
            ('permission.delete', '删除权限', 'element', 'permission', 'delete')
            ON CONFLICT (code) DO NOTHING;
        """))
        
        print("✓ 元素权限初始化完成")


async def init_menus():
    """初始化菜单结构"""
    async with engine.begin() as conn:
        # 顶级菜单
        await conn.execute(text("""
            INSERT INTO menus (id, parent_id, name, display_name, icon, path, component, permission_code, sort_order) VALUES
            (1, NULL, 'dashboard', '首页', 'home', '/admin/home', 'Dashboard', 'menu.dashboard', 1),
            (2, NULL, 'providers', '供应商管理', 'server', NULL, NULL, 'menu.providers', 2),
            (3, NULL, 'models', '模型管理', 'database', '/admin/models', 'Models', 'menu.models', 3),
            (4, NULL, 'api_keys', 'API Key管理', 'key', '/admin/keys', 'ApiKeys', 'menu.api_keys', 4),
            (5, NULL, 'logs', '日志管理', 'file-text', NULL, NULL, 'menu.logs', 5),
            (6, NULL, 'stats', '统计分析', 'bar-chart', '/admin/stats', 'Statistics', 'menu.stats', 6),
            (7, NULL, 'documents', '文档管理', 'book', '/admin/documents', 'Documents', 'menu.documents', 7),
            (8, NULL, 'mcp_servers', 'MCP服务器', 'cpu', '/admin/mcp-servers', 'McpServers', 'menu.mcp_servers', 8),
            (9, NULL, 'system', '系统配置', 'settings', NULL, NULL, 'menu.system', 9),
            (10, NULL, 'users', '用户管理', 'users', NULL, NULL, 'menu.users', 10)
            ON CONFLICT (id) DO NOTHING;
        """))
        
        # 二级菜单
        await conn.execute(text("""
            INSERT INTO menus (id, parent_id, name, display_name, icon, path, component, permission_code, sort_order) VALUES
            (11, 2, 'providers-list', '供应商列表', NULL, '/admin/providers', 'Providers', 'menu.providers.list', 1),
            (12, 2, 'provider-models', '供应商模型关联', NULL, '/admin/provider-models', 'ProviderModels', 'menu.providers.models', 2),
            (13, 5, 'logs-requests', '请求日志', NULL, '/admin/request-logs', 'RequestLogs', 'menu.logs.requests', 1),
            (14, 5, 'logs-errors', '错误分析', NULL, '/admin/error-analysis', 'ErrorAnalysis', 'menu.logs.errors', 2),
            (15, 5, 'logs-mcp', 'MCP日志', NULL, '/admin/mcp-logs', 'McpLogs', 'menu.logs.mcp', 3),
            (16, 9, 'system-config', '系统设置', NULL, '/admin/system-config', 'SystemConfig', 'menu.system.config', 1),
            (17, 9, 'scheduler-tasks', '定时任务', NULL, '/admin/scheduler-tasks', 'SchedulerTasks', 'menu.system.scheduler', 2),
            (18, 9, 'notifications', '通知中心', NULL, '/admin/notifications', 'Notifications', 'menu.system.notifications', 3),
            (19, 10, 'users-list', '用户列表', NULL, '/admin/users', 'Users', 'menu.users.list', 1),
            (20, 10, 'roles', '角色管理', NULL, '/admin/roles', 'Roles', 'menu.users.roles', 2)
            ON CONFLICT (id) DO NOTHING;
        """))
        
        print("✓ 菜单初始化完成")


async def assign_viewer_permissions():
    """为 viewer 角色分配权限（只读）"""
    async with engine.begin() as conn:
        # viewer 只有菜单和页面权限，没有元素权限
        await conn.execute(text("""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT 
                (SELECT id FROM roles WHERE name = 'viewer'),
                id
            FROM permissions
            WHERE type IN ('menu', 'page')
            AND code NOT LIKE '%system%'
            AND code NOT LIKE '%users%'
            ON CONFLICT DO NOTHING;
        """))
        print("✓ viewer 角色权限分配完成")


async def assign_operator_permissions():
    """为 operator 角色分配权限（业务操作）"""
    async with engine.begin() as conn:
        # operator 有业务相关的所有权限，但没有系统配置和用户管理权限
        await conn.execute(text("""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT 
                (SELECT id FROM roles WHERE name = 'operator'),
                id
            FROM permissions
            WHERE (
                (type IN ('menu', 'page') AND code NOT LIKE '%system%' AND code NOT LIKE '%users%')
                OR (type = 'element' AND resource IN ('provider', 'model', 'api_key', 'provider_model', 'document', 'mcp_server'))
                OR (type = 'element' AND code IN ('log.export', 'log.analyze', 'log.create_report'))
            )
            ON CONFLICT DO NOTHING;
        """))
        print("✓ operator 角色权限分配完成")


async def assign_admin_permissions():
    """为 admin 角色分配权限（所有权限）"""
    async with engine.begin() as conn:
        # admin 有所有权限
        await conn.execute(text("""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT 
                (SELECT id FROM roles WHERE name = 'admin'),
                id
            FROM permissions
            ON CONFLICT DO NOTHING;
        """))
        print("✓ admin 角色权限分配完成")


async def create_initial_admin():
    """创建初始 admin 用户（从 ADMIN_USERS 环境变量读取）"""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    admin_users_env = os.getenv("ADMIN_USERS", "")
    if not admin_users_env:
        admin_users_env = f"admin:{os.getenv('ADMIN_PASSWORD', 'admin123')}"

    try:
        from services.rbac_auth import hash_password
    except ImportError:
        import bcrypt
        def hash_password(p):
            return bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')

    async with engine.begin() as conn:
        for pair in admin_users_env.split(","):
            if ":" not in pair:
                continue
            username, password = pair.strip().split(":", 1)

            existing = await conn.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": username}
            )
            if existing.scalar_one_or_none():
                print(f"  ⚠ 用户 {username} 已存在，跳过")
                continue

            await conn.execute(text("""
                INSERT INTO users (username, password_hash, email, full_name, is_active, is_superuser)
                VALUES (:u, :ph, :email, :full_name, TRUE, TRUE)
            """), {
                "u": username,
                "ph": hash_password(password),
                "email": f"{username}@modelgate.local",
                "full_name": username,
            })

            user_row = await conn.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": username}
            )
            user_id = user_row.scalar()

            superadmin_row = await conn.execute(
                text("SELECT id FROM roles WHERE name = 'superadmin'")
            )
            superadmin_id = superadmin_row.scalar()

            await conn.execute(text("""
                INSERT INTO user_roles (user_id, role_id)
                VALUES (:uid, :rid)
                ON CONFLICT DO NOTHING
            """), {"uid": user_id, "rid": superadmin_id})

            print(f"  ✓ 创建用户 {username}，密码来自 ADMIN_USERS 环境变量，角色: superadmin")


async def main():
    """执行所有初始化"""
    try:
        await init_roles()
        await init_menu_permissions()
        await init_page_permissions()
        await init_element_permissions()
        await init_menus()
        await assign_viewer_permissions()
        await assign_operator_permissions()
        await assign_admin_permissions()
        await create_initial_admin()
        print("\n✓✓✓ 所有数据初始化完成 ✓✓✓")
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
