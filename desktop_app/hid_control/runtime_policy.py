"""CPU-only 运行时策略。

必须在任何 PySide6 / Qt 模块导入之前生效：Qt 会在首次加载平台插件和图形后端时
读取这些环境变量，一旦 QApplication 建立后再设置就来不及了。

本模块只依赖标准库，因此可以在包初始化阶段安全导入。
"""

from __future__ import annotations

import os

#: 强制 Qt 使用软件 OpenGL 实现（随包分发 opengl32sw.dll），不加载显卡驱动提供的
#: 桌面 OpenGL，从而避免任何 GPU 图形路径。
SOFTWARE_RENDER_ENVIRONMENT: dict[str, str] = {
    "QT_OPENGL": "software",
    # 即使将来误引入 Qt Quick/QML，也把其渲染后端锁在软件光栅化上。
    "QT_QUICK_BACKEND": "software",
    "QSG_RHI_BACKEND": "software",
    # 关闭 Widget 的 RHI 后备存储合成器。开启时 Qt 会创建 D3D11/D3D12/Vulkan 设备
    # 并把窗口内容交给 GPU 合成；关闭后窗口走纯 CPU 栅格路径。
    "QT_WIDGETS_RHI": "0",
    # 关闭 Qt 的 GPU 相关诊断/回退探测噪声。
    "QT_DISABLE_SHADER_DISK_CACHE": "1",
}

#: 需要显式置空的变量：若外部环境（例如用户 shell 或启动脚本）指定了其它后端，
#: 这里必须覆盖为软件路径，而不是继承。
CLEARED_ENVIRONMENT: tuple[str, ...] = (
    "QSG_RHI_BACKEND_FORCE",
)

_APPLIED = False


def apply_software_render_environment() -> None:
    """把软件渲染策略强制写入进程环境。

    使用直接赋值而非 ``setdefault``：外部环境若已指向硬件后端，也必须被覆盖，
    以保证"不调用 GPU"的承诺由本程序自己负责。

    该函数每次调用都会重新强制写入（而不是只生效一次）：这样即使导入后又有其他
    代码设置了硬件后端变量，再次调用也能把保证恢复回来。重复调用不会产生副作用，
    因为写入的是同一组固定值。
    """
    global _APPLIED
    for name, value in SOFTWARE_RENDER_ENVIRONMENT.items():
        os.environ[name] = value
    for name in CLEARED_ENVIRONMENT:
        os.environ.pop(name, None)
    _APPLIED = True


def is_software_render_environment_applied() -> bool:
    """返回策略是否已在本进程生效（供测试与启动自检使用）。"""
    return all(os.environ.get(name) == value for name, value in SOFTWARE_RENDER_ENVIRONMENT.items())


def qt_application_attributes() -> tuple[str, ...]:
    """返回创建 QApplication 前必须设置的 Qt ApplicationAttribute 名称。

    以字符串形式返回，避免本模块导入 PySide6，从而保证调用方能在导入 Qt 之后、
    构造 QApplication 之前逐个设置。
    """
    return ("AA_UseSoftwareOpenGL", "AA_ForceRasterWidgets")
