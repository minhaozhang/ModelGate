"""
RBAC 权限服务

提供用户权限查询、权限检查等功能
"""

from typing import List, Dict, Optional
from sqlalchemy import select
from app.core.database import (
    User, Role, UserRole, Permission, RolePermission, async_session_maker
)

_permission_cache: Dict[int, Dict] = {}
_cache_ttl = 300


async def query_user_permissions(user_id: int) -> Dict[str, List[str]]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
            .distinct()
        )
        permissions = result.scalars().all()
        
        grouped = {"menus": [], "pages": [], "elements": []}
        for perm in permissions:
            if perm.type == "menu":
                grouped["menus"].append(perm.code)
            elif perm.type == "page":
                grouped["pages"].append(perm.code)
            elif perm.type == "element":
                grouped["elements"].append(perm.code)
        
        return grouped


async def has_permission(user_id: int, permission_code: str) -> bool:
    """检查用户是否有指定权限"""
    permissions = await query_user_permissions(user_id)
    all_permissions = (
        permissions["menus"] + 
        permissions["pages"] + 
        permissions["elements"]
    )
    return permission_code in all_permissions


async def has_any_permission(user_id: int, permission_codes: List[str]) -> bool:
    """检查用户是否有任一权限"""
    permissions = await query_user_permissions(user_id)
    all_permissions = (
        permissions["menus"] + 
        permissions["pages"] + 
        permissions["elements"]
    )
    return any(code in all_permissions for code in permission_codes)


async def has_all_permissions(user_id: int, permission_codes: List[str]) -> bool:
    """检查用户是否有所有权限"""
    permissions = await query_user_permissions(user_id)
    all_permissions = (
        permissions["menus"] + 
        permissions["pages"] + 
        permissions["elements"]
    )
    return all(code in all_permissions for code in permission_codes)


async def get_user_by_username(username: str) -> Optional[User]:
    """根据用户名查询用户"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.username == username, User.is_active == True)
        )
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: int) -> Optional[User]:
    """根据 ID 查询用户"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        return result.scalar_one_or_none()


async def get_user_roles(user_id: int) -> List[Role]:
    """获取用户的所有角色"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return result.scalars().all()
