"""Leonardo 硬件键鼠控制桌面应用。

包初始化阶段即锁定 CPU-only 软件渲染策略：Qt 会在首次加载图形后端时读取相关环境
变量，因此必须早于任何 PySide6 导入完成设置。
"""

from .runtime_policy import apply_software_render_environment

apply_software_render_environment()

APP_NAME = "祥子の宝贝"
APP_VERSION = "0.1.1"
