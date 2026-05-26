"""
权限管理路由

提供权限的查询、树形结构等接口
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select, func
from core.database import Permission, async_session_maker
from core.permissions import permission_required

router = APIRouter(prefix="/admin/api/rbac/permissions", tags=["权限管理"])


@router.get("")
async def list_permissions(
    request: Request,
    type: Optional[str] = None,
    resource: Optional[str] = None,
    keyword: Optional[str] = None,
    user = Depends(permission_required("page.roles"))
):
    """
    获取权限列表
    
    查询参数:
    - type: 权限类型（menu/page/element/data）
    - resource: 资源名称
    - keyword: 搜索关键词（权限码、名称）
    
    返回:
    {
        "success": true,
        "data": [
            {
                "id": 1,
                "code": "menu.dashboard",
                "name": "首页菜单",
                "type": "menu",
                "resource": "dashboard",
                "action": "view"
            },
            ...
        ]
    }
    """
    async with async_session_maker() as session:
        # 构建查询
        query = select(Permission)
        
        if type:
            query = query.where(Permission.type == type)
        
        if resource:
            query = query.where(Permission.resource == resource)
        
        if keyword:
            query = query.where(
                (Permission.code.ilike(f"%{keyword}%")) |
                (Permission.name.ilike(f"%{keyword}%"))
            )
        
        query = query.order_by(Permission.type, Permission.code)
        
        result = await session.execute(query)
        permissions = result.scalars().all()
        
        return {
            "success": True,
            "data": [
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


@router.get("/tree")
async def get_permission_tree(
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """
    获取权限树形结构（用于角色权限分配界面）
    
    返回:
    {
        "success": true,
        "data": [
            {
                "label": "菜单权限",
                "type": "menu",
                "children": [
                    {
                        "label": "首页",
                        "resource": "dashboard",
                        "children": [
                            {
                                "id": 1,
                                "code": "menu.dashboard",
                                "label": "首页菜单"
                            }
                        ]
                    },
                    ...
                ]
            },
            {
                "label": "页面权限",
                "type": "page",
                "children": [...]
            },
            {
                "label": "操作权限",
                "type": "element",
                "children": [...]
            }
        ]
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Permission).order_by(Permission.type, Permission.resource, Permission.code)
        )
        permissions = result.scalars().all()
        
        # 按类型和资源分组
        tree = []
        
        # 菜单权限
        menu_perms = [p for p in permissions if p.type == "menu"]
        menu_resources = {}
        for p in menu_perms:
            if p.resource not in menu_resources:
                menu_resources[p.resource] = []
            menu_resources[p.resource].append({
                "id": p.id,
                "code": p.code,
                "label": p.name
            })
        
        menu_node = {
            "label": "菜单权限",
            "type": "menu",
            "children": [
                {
                    "label": resource,
                    "resource": resource,
                    "children": items
                }
                for resource, items in menu_resources.items()
            ]
        }
        tree.append(menu_node)
        
        # 页面权限
        page_perms = [p for p in permissions if p.type == "page"]
        page_resources = {}
        for p in page_perms:
            if p.resource not in page_resources:
                page_resources[p.resource] = []
            page_resources[p.resource].append({
                "id": p.id,
                "code": p.code,
                "label": p.name
            })
        
        page_node = {
            "label": "页面权限",
            "type": "page",
            "children": [
                {
                    "label": resource,
                    "resource": resource,
                    "children": items
                }
                for resource, items in page_resources.items()
            ]
        }
        tree.append(page_node)
        
        # 元素权限（操作按钮）
        element_perms = [p for p in permissions if p.type == "element"]
        element_resources = {}
        for p in element_perms:
            if p.resource not in element_resources:
                element_resources[p.resource] = []
            element_resources[p.resource].append({
                "id": p.id,
                "code": p.code,
                "label": p.name,
                "action": p.action
            })
        
        element_node = {
            "label": "操作权限",
            "type": "element",
            "children": [
                {
                    "label": resource,
                    "resource": resource,
                    "children": items
                }
                for resource, items in element_resources.items()
            ]
        }
        tree.append(element_node)
        
        return {
            "success": True,
            "data": tree
        }


@router.get("/grouped")
async def get_permissions_grouped(
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """
    获取权限列表（按类型分组，扁平结构）
    
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
        result = await session.execute(
            select(Permission).order_by(Permission.type, Permission.code)
        )
        permissions = result.scalars().all()
        
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


@router.get("/resources")
async def get_resources(
    request: Request,
    user = Depends(permission_required("page.roles"))
):
    """
    获取所有资源列表（去重）
    
    返回:
    {
        "success": true,
        "data": ["dashboard", "provider", "model", "api_key", ...]
    }
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Permission.resource).distinct().order_by(Permission.resource)
        )
        resources = result.scalars().all()
        
        return {
            "success": True,
            "data": resources
        }
