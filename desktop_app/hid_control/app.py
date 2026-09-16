from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME
from .hotkeys import GlobalHotkeyService
from .mouse_hook import MouseSideButtonService
from .privilege import is_administrator, restart_as_administrator
from .serial_service import SerialService
from .storage import SettingsStore
from .workflow import WorkflowRunner
from .ui.main_window import MainWindow


def _choose_start_mode() -> bool:
    """返回 True 表示继续以当前普通模式启动。"""
    if is_administrator():
        return True
    dialog = QMessageBox()
    dialog.setWindowTitle("启动权限选择")
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setIcon(QMessageBox.Icon.Information)
    dialog.setText("软件当前将以普通模式启动")
    dialog.setInformativeText("普通模式可使用串口和鼠标侧键控制。管理员模式可改善与管理员权限窗口交互时的兼容性，但不能抢占被其他软件占用的快捷键。")
    elevate_button = dialog.addButton("以管理员模式启动", QMessageBox.ButtonRole.AcceptRole)
    normal_button = dialog.addButton("普通模式启动", QMessageBox.ButtonRole.ActionRole)
    cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    dialog.exec()
    if dialog.clickedButton() is elevate_button:
        restart_as_administrator()
        return False
    return dialog.clickedButton() is normal_button and dialog.clickedButton() is not cancel_button


def _resource_path(name: str) -> Path:
    """返回随程序分发的资源路径；打包后从解压目录读取。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / name
    return Path(__file__).resolve().parents[2] / name


def run() -> int:
    application = QApplication(sys.argv)
    # Windows 11 中文界面统一使用系统可用的微软雅黑 UI，避免键盘选择器标签乱码。
    application.setFont(QFont("Microsoft YaHei UI", 10))
    icon_path = _resource_path("xiangzi.png")
    if icon_path.exists():
        application.setWindowIcon(QIcon(str(icon_path)))
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("LeonardoHID")

    if not _choose_start_mode():
        return 0

    store = SettingsStore()
    state = store.load()
    serial_service = SerialService()
    workflow_runner = WorkflowRunner(serial_service)
    hotkeys = GlobalHotkeyService()
    mouse_buttons = MouseSideButtonService()

    window = MainWindow(store, state, serial_service, workflow_runner, hotkeys, mouse_buttons)
    if state.window_layout.last_window_state == "minimized":
        window.showMinimized()
    elif state.window_layout.last_window_state == "maximized":
        window.showMaximized()
    else:
        window.show()
    exit_code = application.exec()

    mouse_buttons.stop()
    hotkeys.stop()
    workflow_runner.close()
    serial_service.close()
    return exit_code
