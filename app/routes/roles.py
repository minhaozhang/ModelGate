"""
角色管理路由

提供角色的增删改查、权限分配等接口
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select, func
from app.core.database import Role, RolePermission, Permission, async_session_maker
from app.core.permissions import permission_required
from datetime import datetime

router = APIRouter(prefix="/admin/api/rbac/roles", tags=["角色管理"])


class RoleCreateRequest(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None


class RoleUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None


class RolePermissionAssignRequest(BaseModel):
    permission_ids: List[int]


@router.get("")
async def list_roles(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    keyword: Optional[str] = None,
    user = Depends(permission_required("page.roles"))
):
    """
    获取角色列表
    
    查询参数:
    - page: 页码（默认1）
    - page_size: 每页数量（默认50）
    - keyword: 搜索关键词（角色名、显示名）
    
    返回:
    {
        "success": true,
        "data": {
            "items": [...],
            "total": 10,
            "page": 1,
            "page_size": 50
        }
    }
    """
    async with async_session_maker() as session:
        # 构建查询
        query = select(Role)
        
        if keyword:
            query = query.where(
                (Role.name.ilike(f"%{keyword}%")) |
                (Role.display_name.ilike(f"%{keyword}%"))
            )
        
        # 总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)
        
        # 分页
        query = query.offset((page - 1) * page_size).limit(page_size)
        query = query.order_by(Role.id)
        
        result = await session.execute(query)
        roles = result.scalars().all()
        
        # 查询每个角色的权限数量
        items = []
        for r in roles:
            perm_count = await session.scalar(
                select(func.count()).where(RolePermission.role_id == r.id)
            )
            
            items.append({
                "id": r.id,
                "name": r.name,
                "display_name": r.display_name,
                "description": r.description,
                "is_system": r.is_system,
                "permission_count": perm_count,
                "created_at": r.created_at.isoformat() if r.created_at else None
            })
        
        return {
            "success": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size
            }
        }


@router.get("/{role_id}")
async def get_role(
    role_id: int,
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """获取角色详情（包含权限列表）"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Role).where(Role.id == role_id)
        )
        role = result.scalar_one_or_none()
        
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        
        # 查询权限
        perm_result = await session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.type, Permission.code)
        )
        permissions = perm_result.scalars().all()
        
        return {
            "success": True,
            "data": {
                "id": role.id,
                "name": role.name,
                "display_name": role.display_name,
                "description": role.description,
                "is_system": role.is_system,
                "created_at": role.created_at.isoformat() if role.created_at else None,
                "permissions": [
                    {
                        "id": p.id,
                        "code": p.code,
                        "name": p.name,
                        "type": p.type,
                        "resource": p.resource,
                        "action": p.action
                    }
                    for p in permissions
                ]
            }
        }


@router.post("")
async def create_role(
    data: RoleCreateRequest,
    request: Request,
    user = Depends(permission_required("role.create"))
):
    """
    创建角色
    
    请求体:
    {
        "name": "custom_role",
        "display_name": "自定义角色",
        "description": "角色描述"
    }
    """
    async with async_session_maker() as session:
        # 检查角色名是否存在
        existing = await session.execute(
            select(Role).where(Role.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="角色名已存在")
        
        # 创建角色
        new_role = Role(
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            is_system=False,
            created_at=datetime.now()
        )
        session.add(new_role)
        await session.commit()
        
        return {
            "success": True,
            "message": "角色创建成功",
            "data": {"id": new_role.id}
        }


@router.put("/{role_id}")
async def update_role(
    role_id: int,
    data: RoleUpdateRequest,
    request: Request,
    user = Depends(permission_required("role.update"))
):
    """
    更新角色信息
    
    请求体:
    {
        "display_name": "新显示名",
        "description": "新描述"
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Role).where(Role.id == role_id)
        )
        role = result.scalar_one_or_none()
        
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        
        # 系统角色不允许修改名称
        if role.is_system:
            raise HTTPException(status_code=400, detail="系统角色不允许修改")
        
        # 更新字段
        if data.display_name is not None:
            role.display_name = data.display_name
        
        if data.description is not None:
            role.description = data.description
        
        await session.commit()
        
        return {
            "success": True,
            "message": "角色更新成功"
        }


@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    request: Request,
    user = Depends(permission_required("role.delete"))
):
    """删除角色"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Role).where(Role.id == role_id)
        )
        role = result.scalar_one_or_none()
        
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        
        # 系统角色不允许删除
        if role.is_system:
            raise HTTPException(status_code=400, detail="系统角色不允许删除")
        
        # 删除角色权限关联
        await session.execute(
            RolePermission.__table__.delete().where(RolePermission.role_id == role_id)
        )
        
        # 删除角色
        await session.delete(role)
        await session.commit()
        
        return {
            "success": True,
            "message": "角色删除成功"
        }


@router.post("/{role_id}/assign-permissions")
async def assign_permissions(
    role_id: int,
    data: RolePermissionAssignRequest,
    request: Request,
    user = Depends(permission_required("role.assign_permission"))
):
    """
    分配权限
    
    请求体:
    {
        "permission_ids": [1, 2, 3, 4, 5]
    }
    """
    async with async_session_maker() as session:
        # 检查角色是否存在
        result = await session.execute(
            select(Role).where(Role.id == role_id)
        )
        role = result.scalar_one_or_none()
        
        if not role:
            raise HTTPException(status_code=404, detail="角色不存在")
        
        # 系统角色不允许修改权限
        if role.is_system:
            raise HTTPException(status_code=400, detail="系统角色权限不允许修改")
        
        # 删除旧的权限关联
        await session.execute(
            RolePermission.__table__.delete().where(RolePermission.role_id == role_id)
        )
        
        # 添加新的权限关联
        for perm_id in data.permission_ids:
            role_perm = RolePermission(role_id=role_id, permission_id=perm_id)
            session.add(role_perm)
        
        await session.commit()
        
        return {
            "success": True,
            "message": "权限分配成功"
        }


@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: int,
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """
    获取角色的权限列表（按类型分组）
    
    返回:
    {
        "success": true,
        "data": {
            "menus": [...],
            "pages": [...],
            "elements": [...]
        }
    }
    """
    async with async_session_maker() as session:
        # 检查角色是否存在
        result = await session.execute(
            select(Role).where(Role.id == role_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="角色不存在")
        
        # 查询权限
        perm_result = await session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.type, Permission.code)
        )
        permissions = perm_result.scalars().all()
        
        # 按类型分组
        grouped = {
            "menus": [],
            "pages": [],
            "elements": []
        }
        
        for p in permissions:
            perm_data = {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "resource": p.resource,
                "action": p.action
            }
            
            if p.type == "menu":
                grouped["menus"].append(perm_data)
            elif p.type == "page":
                grouped["pages"].append(perm_data)
            elif p.type == "element":
                grouped["elements"].append(perm_data)
        
        return {
            "success": True,
            "data": grouped
        }
