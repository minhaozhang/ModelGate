"""
用户管理路由

提供用户的增删改查、角色分配等接口
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import User, Role, UserRole, async_session_maker
from app.core.permissions import permission_required
from app.services.rbac_auth import hash_password
from datetime import datetime

router = APIRouter(prefix="/admin/api/rbac/users", tags=["用户管理"])


class UserCreateRequest(BaseModel):
    username: str
    password: str
    email: str
    full_name: Optional[str] = None
    is_superuser: bool = False
    role_ids: List[int] = []


class UserUpdateRequest(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class UserPasswordResetRequest(BaseModel):
    new_password: str


class UserRoleAssignRequest(BaseModel):
    role_ids: List[int]


@router.get("")
async def list_users(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    user = Depends(permission_required("page.users"))
):
    """
    获取用户列表
    
    查询参数:
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - keyword: 搜索关键词（用户名、邮箱、姓名）
    
    返回:
    {
        "success": true,
        "data": {
            "items": [...],
            "total": 100,
            "page": 1,
            "page_size": 20
        }
    }
    """
    async with async_session_maker() as session:
        # 构建查询
        query = select(User)
        
        if keyword:
            query = query.where(
                (User.username.ilike(f"%{keyword}%")) |
                (User.email.ilike(f"%{keyword}%")) |
                (User.full_name.ilike(f"%{keyword}%"))
            )
        
        # 总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)
        
        # 分页
        query = query.offset((page - 1) * page_size).limit(page_size)
        query = query.order_by(User.created_at.desc())
        
        result = await session.execute(query)
        users = result.scalars().all()
        
        # 查询每个用户的角色
        items = []
        for u in users:
            role_result = await session.execute(
                select(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == u.id)
            )
            roles = role_result.scalars().all()
            
            items.append({
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "full_name": u.full_name,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "roles": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "display_name": r.display_name
                    }
                    for r in roles
                ]
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


@router.get("/{user_id}")
async def get_user(
    user_id: int,
    request: Request,
    user = Depends(permission_required("page.users"))
):
    """获取用户详情"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        u = result.scalar_one_or_none()
        
        if not u:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 查询角色
        role_result = await session.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == u.id)
        )
        roles = role_result.scalars().all()
        
        return {
            "success": True,
            "data": {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "full_name": u.full_name,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "roles": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "display_name": r.display_name,
                        "description": r.description
                    }
                    for r in roles
                ]
            }
        }


@router.post("")
async def create_user(
    data: UserCreateRequest,
    request: Request,
    user = Depends(permission_required("user.create"))
):
    """
    创建用户
    
    请求体:
    {
        "username": "newuser",
        "password": "password123",
        "email": "user@example.com",
        "full_name": "新用户",
        "is_superuser": false,
        "role_ids": [2, 3]
    }
    """
    async with async_session_maker() as session:
        # 检查用户名是否存在
        existing = await session.execute(
            select(User).where(User.username == data.username)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="用户名已存在")
        
        # 检查邮箱是否存在
        existing = await session.execute(
            select(User).where(User.email == data.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已存在")
        
        # 创建用户
        new_user = User(
            username=data.username,
            password_hash=hash_password(data.password),
            email=data.email,
            full_name=data.full_name,
            is_superuser=data.is_superuser,
            is_active=True,
            created_at=datetime.now()
        )
        session.add(new_user)
        await session.flush()
        
        # 分配角色
        for role_id in data.role_ids:
            user_role = UserRole(user_id=new_user.id, role_id=role_id)
            session.add(user_role)
        
        await session.commit()
        
        return {
            "success": True,
            "message": "用户创建成功",
            "data": {"id": new_user.id}
        }


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    data: UserUpdateRequest,
    request: Request,
    user = Depends(permission_required("user.update"))
):
    """
    更新用户信息
    
    请求体:
    {
        "email": "newemail@example.com",
        "full_name": "新名字",
        "is_active": true,
        "is_superuser": false
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        target_user = result.scalar_one_or_none()
        
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 更新字段
        if data.email is not None:
            # 检查邮箱是否被占用
            existing = await session.execute(
                select(User).where(User.email == data.email, User.id != user_id)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="邮箱已被使用")
            target_user.email = data.email
        
        if data.full_name is not None:
            target_user.full_name = data.full_name
        
        if data.is_active is not None:
            target_user.is_active = data.is_active
        
        if data.is_superuser is not None:
            target_user.is_superuser = data.is_superuser
        
        await session.commit()
        
        return {
            "success": True,
            "message": "用户更新成功"
        }


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    user = Depends(permission_required("user.delete"))
):
    """删除用户"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        target_user = result.scalar_one_or_none()
        
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 删除用户角色关联
        await session.execute(
            UserRole.__table__.delete().where(UserRole.user_id == user_id)
        )
        
        # 删除用户
        await session.delete(target_user)
        await session.commit()
        
        return {
            "success": True,
            "message": "用户删除成功"
        }


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    data: UserPasswordResetRequest,
    request: Request,
    user = Depends(permission_required("user.reset_password"))
):
    """
    重置用户密码
    
    请求体:
    {
        "new_password": "newpassword123"
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        target_user = result.scalar_one_or_none()
        
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        target_user.password_hash = hash_password(data.new_password)
        await session.commit()
        
        return {
            "success": True,
            "message": "密码重置成功"
        }


@router.post("/{user_id}/assign-roles")
async def assign_roles(
    user_id: int,
    data: UserRoleAssignRequest,
    request: Request,
    user = Depends(permission_required("user.assign_role"))
):
    """
    分配角色
    
    请求体:
    {
        "role_ids": [1, 2, 3]
    }
    """
    async with async_session_maker() as session:
        # 检查用户是否存在
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 删除旧的角色关联
        await session.execute(
            UserRole.__table__.delete().where(UserRole.user_id == user_id)
        )
        
        # 添加新的角色关联
        for role_id in data.role_ids:
            user_role = UserRole(user_id=user_id, role_id=role_id)
            session.add(user_role)
        
        await session.commit()
        
        return {
            "success": True,
            "message": "角色分配成功"
        }
