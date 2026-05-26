"""
菜单管理路由

提供菜单的增删改查、树形结构等接口
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select
from core.database import Menu, async_session_maker
from core.permissions import permission_required, login_required
from services.rbac import query_user_permissions
from datetime import datetime

router = APIRouter(prefix="/admin/api/rbac/menus", tags=["菜单管理"])


class MenuCreateRequest(BaseModel):
    parent_id: Optional[int] = None
    name: str
    display_name: str
    icon: Optional[str] = None
    path: Optional[str] = None
    component: Optional[str] = None
    permission_code: Optional[str] = None
    sort_order: int = 0


class MenuUpdateRequest(BaseModel):
    parent_id: Optional[int] = None
    display_name: Optional[str] = None
    icon: Optional[str] = None
    path: Optional[str] = None
    component: Optional[str] = None
    permission_code: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("/tree")
async def get_menu_tree(
    request: Request,
    user = Depends(login_required())
):
    """
    获取当前用户的菜单树（用于渲染侧边栏）
    
    返回:
    {
        "success": true,
        "data": [
            {
                "id": 1,
                "name": "dashboard",
                "display_name": "首页",
                "icon": "home",
                "path": "/admin/home",
                "component": "Dashboard",
                "children": []
            },
            {
                "id": 2,
                "name": "providers",
                "display_name": "供应商管理",
                "icon": "server",
                "children": [
                    {
                        "id": 11,
                        "name": "providers-list",
                        "display_name": "供应商列表",
                        "path": "/admin/providers",
                        "component": "Providers"
                    }
                ]
            }
        ]
    }
    """
    async with async_session_maker() as session:
        # 获取用户权限
        permissions = await query_user_permissions(user.id)
        menu_permissions = set(permissions["menus"])
        
        # 超级管理员看到所有菜单
        if user.is_superuser:
            result = await session.execute(
                select(Menu).order_by(Menu.sort_order, Menu.id)
            )
            all_menus = result.scalars().all()
        else:
            # 普通用户只看到有权限的菜单
            result = await session.execute(
                select(Menu)
                .where(Menu.permission_code.in_(menu_permissions))
                .order_by(Menu.sort_order, Menu.id)
            )
            all_menus = result.scalars().all()
        
        # 构建树形结构
        def build_tree(parent_id: Optional[int]) -> List[dict]:
            children = []
            for menu in all_menus:
                if menu.parent_id == parent_id:
                    node = {
                        "id": menu.id,
                        "name": menu.name,
                        "display_name": menu.display_name,
                        "icon": menu.icon,
                        "path": menu.path,
                        "component": menu.component,
                        "children": build_tree(menu.id)
                    }
                    children.append(node)
            return children
        
        tree = build_tree(None)
        
        return {
            "success": True,
            "data": tree
        }


@router.get("/all")
async def get_all_menus(
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """
    获取所有菜单（管理界面用，树形结构）
    
    返回:
    {
        "success": true,
        "data": [...]
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Menu).order_by(Menu.sort_order, Menu.id)
        )
        all_menus = result.scalars().all()
        
        # 构建树形结构
        def build_tree(parent_id: Optional[int]) -> List[dict]:
            children = []
            for menu in all_menus:
                if menu.parent_id == parent_id:
                    node = {
                        "id": menu.id,
                        "parent_id": menu.parent_id,
                        "name": menu.name,
                        "display_name": menu.display_name,
                        "icon": menu.icon,
                        "path": menu.path,
                        "component": menu.component,
                        "permission_code": menu.permission_code,
                        "sort_order": menu.sort_order,
                        "children": build_tree(menu.id)
                    }
                    children.append(node)
            return children
        
        tree = build_tree(None)
        
        return {
            "success": True,
            "data": tree
        }


@router.get("/{menu_id}")
async def get_menu(
    menu_id: int,
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """获取菜单详情"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Menu).where(Menu.id == menu_id)
        )
        menu = result.scalar_one_or_none()
        
        if not menu:
            raise HTTPException(status_code=404, detail="菜单不存在")
        
        return {
            "success": True,
            "data": {
                "id": menu.id,
                "parent_id": menu.parent_id,
                "name": menu.name,
                "display_name": menu.display_name,
                "icon": menu.icon,
                "path": menu.path,
                "component": menu.component,
                "permission_code": menu.permission_code,
                "sort_order": menu.sort_order
            }
        }


@router.post("")
async def create_menu(
    data: MenuCreateRequest,
    request: Request,
    user = Depends(permission_required("menu.create"))
):
    """
    创建菜单
    
    请求体:
    {
        "parent_id": null,
        "name": "new_menu",
        "display_name": "新菜单",
        "icon": "folder",
        "path": "/admin/new-menu",
        "component": "NewMenu",
        "permission_code": "menu.new_menu",
        "sort_order": 10
    }
    """
    async with async_session_maker() as session:
        # 检查菜单名是否存在
        existing = await session.execute(
            select(Menu).where(Menu.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="菜单名已存在")
        
        # 创建菜单
        new_menu = Menu(
            parent_id=data.parent_id,
            name=data.name,
            display_name=data.display_name,
            icon=data.icon,
            path=data.path,
            component=data.component,
            permission_code=data.permission_code,
            sort_order=data.sort_order
        )
        session.add(new_menu)
        await session.commit()
        
        return {
            "success": True,
            "message": "菜单创建成功",
            "data": {"id": new_menu.id}
        }


@router.put("/{menu_id}")
async def update_menu(
    menu_id: int,
    data: MenuUpdateRequest,
    request: Request,
    user = Depends(permission_required("menu.update"))
):
    """
    更新菜单
    
    请求体:
    {
        "display_name": "新显示名",
        "icon": "new-icon",
        "sort_order": 20
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Menu).where(Menu.id == menu_id)
        )
        menu = result.scalar_one_or_none()
        
        if not menu:
            raise HTTPException(status_code=404, detail="菜单不存在")
        
        # 更新字段
        if data.parent_id is not None:
            # 检查不能设置自己为父菜单
            if data.parent_id == menu_id:
                raise HTTPException(status_code=400, detail="不能设置自己为父菜单")
            menu.parent_id = data.parent_id
        
        if data.display_name is not None:
            menu.display_name = data.display_name
        
        if data.icon is not None:
            menu.icon = data.icon
        
        if data.path is not None:
            menu.path = data.path
        
        if data.component is not None:
            menu.component = data.component
        
        if data.permission_code is not None:
            menu.permission_code = data.permission_code
        
        if data.sort_order is not None:
            menu.sort_order = data.sort_order
        
        await session.commit()
        
        return {
            "success": True,
            "message": "菜单更新成功"
        }


@router.delete("/{menu_id}")
async def delete_menu(
    menu_id: int,
    request: Request,
    user = Depends(permission_required("menu.delete"))
):
    """删除菜单"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Menu).where(Menu.id == menu_id)
        )
        menu = result.scalar_one_or_none()
        
        if not menu:
            raise HTTPException(status_code=404, detail="菜单不存在")
        
        # 检查是否有子菜单
        children = await session.execute(
            select(Menu).where(Menu.parent_id == menu_id)
        )
        if children.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="该菜单下有子菜单，不能删除")
        
        # 删除菜单
        await session.delete(menu)
        await session.commit()
        
        return {
            "success": True,
            "message": "菜单删除成功"
        }
