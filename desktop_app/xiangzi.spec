# -*- mode: python ; coding: utf-8 -*-
"""CPU-only 打包配置。

目标：
- 只打包本应用真正需要的 Qt Widgets / QtCore / QtGui / QtNetwork 运行库；
- 明确排除 Qt Quick / QML / WebEngine / 3D / OpenGL Widget / Multimedia / PDF 等
  未被使用的 GPU 或重量级模块；
- 随包提供 ``opengl32sw.dll``，保证 ``QT_OPENGL=software`` 有可用的软件实现。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

PROJECT_DIR = Path(SPECPATH).resolve()
REPO_ROOT = PROJECT_DIR.parent

#: 必须排除的 Python 模块：GPU 计算、视觉/AI 运行时、Qt Quick 与其它未使用的 Qt 子系统。
EXCLUDED_MODULES = [
    # GPU 计算 / AI / 视觉
    "torch",
    "torchvision",
    "tensorflow",
    "cv2",
    "numpy",
    "onnxruntime",
    "onnx",
    "sklearn",
    "scipy",
    "paddle",
    "directml",
    "tensorrt",
    # Qt Quick / QML（使用 GPU 场景图后端）
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.QtQmlWorkerScript",
    # Web 引擎
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    # 3D / OpenGL Widget / 多媒体 / PDF
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    # 其它无关子系统
    "PySide6.QtBluetooth",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtWebView",
    "tkinter",
    "matplotlib",
    "pandas",
]

#: 即使 PyInstaller 分析阶段仍然收集到，也必须在打包前剔除的二进制/插件模式。
EXCLUDED_BINARY_PATTERNS = [
    "Qt6Quick",
    "Qt6Qml",
    "Qt6WebEngine",
    "Qt6WebView",
    "Qt6WebChannel",
    "Qt6WebSockets",
    "Qt63D",
    "Qt6OpenGL",
    "Qt6Multimedia",
    "Qt6Pdf",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Designer",
    "Qt6Help",
    "Qt6Sql",
    "Qt6Test",
    "Qt6VirtualKeyboard",
    "Qt6Bluetooth",
    "Qt6Nfc",
    "Qt6Positioning",
    "Qt6Scxml",
    "Qt6Sensors",
    "Qt6SerialPort",
    "Qt6RemoteObjects",
    "Qt6StateMachine",
    "qpdf",
    "qtvirtualkeyboardplugin",
    "qtuiotouchplugin",
    "qdirect2d",
    "qopensslbackend",
    "qcertonlybackend",
]

#: 只保留应用实际会加载的平台/样式/图像插件，去掉其余插件目录内容。
KEPT_PLUGIN_PATTERNS = (
    "plugins/platforms/qwindows.dll",
    "plugins/platforms/qminimal.dll",
    "plugins/platforms/qoffscreen.dll",
    "plugins/styles/qmodernwindowsstyle.dll",
    "plugins/imageformats/qico.dll",
    "plugins/imageformats/qjpeg.dll",
    "plugins/imageformats/qgif.dll",
    "plugins/networkinformation/qnetworklistmanager.dll",
    "plugins/tls/qschannelbackend.dll",
)

#: 不需要的 Qt 翻译文件（保留中文，去掉其余语言）。
KEPT_TRANSLATION_SUFFIXES = ("_zh_CN.qm", "_en.qm")

#: 随包分发的软件 OpenGL 实现，Qt 在 QT_OPENGL=software 时需要它。
opengl32sw = collect_dynamic_libs("PySide6", search_patterns=["opengl32sw.dll"])

#: hidapi 的动态库。当前 wheel 把 hidapi 静态链接进扩展模块 ``hid.pyd``，因此这里
#: 通常返回空；若某个构建把 ``hidapi.dll`` 单独随包分发，本调用会把它收进 binaries。
#: 扩展模块 ``hid.pyd`` 本身由 hiddenimports 中的 "hid" 收集。
hid_libs = collect_dynamic_libs("hid")

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=opengl32sw + hid_libs,
    datas=[
        (str(REPO_ROOT / "xiangzi.png"), "."),
    ],
    hiddenimports=["serial", "serial.tools.list_ports", "hid"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook_cpu_only.py"],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 分析完成后再次过滤：排除列表是"双保险"，因为 hook 可能仍会带入未使用的 Qt 二进制。
a.binaries = [
    entry
    for entry in a.binaries
    if not any(pattern in entry[0] for pattern in EXCLUDED_BINARY_PATTERNS)
]
a.binaries = [
    entry
    for entry in a.binaries
    if "PySide6/plugins/" not in entry[0].replace("\\", "/")
    or any(entry[0].replace("\\", "/").endswith(kept) for kept in KEPT_PLUGIN_PATTERNS)
]
# 翻译文件位于 datas 而非 binaries，需要单独过滤，只保留中英文。
a.datas = [
    entry
    for entry in a.datas
    if "PySide6/translations/" not in entry[0].replace("\\", "/")
    or entry[0].replace("\\", "/").endswith(KEPT_TRANSLATION_SUFFIXES)
]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="xiangzi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",
    # Windows 版本资源（属性 → 详细信息）。版本号与 hid_control.APP_VERSION 对齐。
    version=str(PROJECT_DIR / "version_info.txt"),
)
