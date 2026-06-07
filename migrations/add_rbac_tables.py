"""
添加 RBAC 权限体系表

创建时间: 2026-05-22
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from core.database import engine
import asyncio


async def upgrade():
    """创建 RBAC 相关表"""
    async with engine.begin() as conn:
        # 1. 用户表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
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
        """))
        
        # 2. 角色表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS roles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                display_name VARCHAR(100),
                description TEXT,
                is_system BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # 3. 用户角色关联表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_roles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, role_id)
            );
        """))
        
        # 4. 菜单表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS menus (
                id SERIAL PRIMARY KEY,
                parent_id INTEGER REFERENCES menus(id) ON DELETE CASCADE,
                name VARCHAR(50) NOT NULL,
                display_name VARCHAR(100),
                icon VARCHAR(50),
                path VARCHAR(200),
                component VARCHAR(200),
                permission_code VARCHAR(100),
                sort_order INTEGER DEFAULT 0,
                is_visible BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # 5. 权限表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS permissions (
                id SERIAL PRIMARY KEY,
                code VARCHAR(100) UNIQUE NOT NULL,
                name VARCHAR(100),
                type VARCHAR(20) NOT NULL,
                resource VARCHAR(50),
                action VARCHAR(20),
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # 6. 角色权限关联表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                id SERIAL PRIMARY KEY,
                role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
                permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(role_id, permission_id)
            );
        """))
        
        # 创建索引
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_roles_name ON roles(name);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_permissions_code ON permissions(code);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_permissions_resource ON permissions(resource);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON role_permissions(role_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_id ON role_permissions(permission_id);"))
        
        print("✓ RBAC 表创建成功")


async def downgrade():
    """删除 RBAC 相关表"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS role_permissions CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS permissions CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS menus CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS user_roles CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS roles CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS users CASCADE;"))
        print("✓ RBAC 表删除成功")


if __name__ == "__main__":
    asyncio.run(upgrade())
