from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .models import MaterialAsset


def material_by_id(materials: list[MaterialAsset], material_id: str) -> MaterialAsset | None:
    return next((item for item in materials if item.id == material_id), None)


def material_preview_path(material: MaterialAsset | None) -> Path | None:
    if material is None or not material.image_path:
        return None
    path = Path(material.image_path)
    return path if path.is_file() else None


def material_reference_summary(materials: list[MaterialAsset], material_id: str) -> str:
    material = material_by_id(materials, material_id)
    if material is None:
        return "素材不存在"
    if material.kind == "color":
        return material.color_hex or "未设置颜色"
    return material.name


def clone_material(material: MaterialAsset, *, name: str | None = None) -> MaterialAsset:
    """编辑共享素材前使用副本，避免无意修改多个钓鱼预设。"""
    return replace(material, id=MaterialAsset().id, name=name or f"{material.name} 副本", marks=list(material.marks), tags=list(material.tags), locked=False)
