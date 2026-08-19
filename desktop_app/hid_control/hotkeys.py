from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal


FALLBACK_SHORTCUTS = {
    "start": ["Ctrl+Shift+F8", "Ctrl+Alt+F10", "Ctrl+Shift+F10"],
    "stop": ["Ctrl+Shift+F9", "Ctrl+Alt+F11", "Ctrl+Shift+F11"],
}


class GlobalHotkeyService(QObject):
    activated = Signal(str)
    error_occurred = Signal(str)
    status_changed = Signal(str)
    bindings_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._bindings: dict[int, str] = {}
        self._definitions: dict[str, str] = {}
        self._active_shortcuts: dict[str, str] = {}

    @property
    def active_shortcuts(self) -> dict[str, str]:
        return dict(self._active_shortcuts)

    def configure(self, bindings: dict[str, str]) -> None:
        normalized = {str(name): str(shortcut).strip() for name, shortcut in bindings.items()}
        if normalized == self._definitions and self._thread and self._thread.is_alive():
            return
        self.stop()
        self._definitions = normalized
        if sys.platform != "win32":
            self.error_occurred.emit("系统级快捷键仅在 Windows 上可用")
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._message_loop, name="global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
            self._thread.join(timeout=1)
        self._thread = None
        self._thread_id = 0
        self._bindings.clear()
        self._active_shortcuts.clear()

    @staticmethod
    def _parse(shortcut: str) -> tuple[int, int]:
        modifiers = 0
        parts = [part.strip().upper() for part in shortcut.split("+") if part.strip()]
        if not parts:
            raise ValueError("快捷键不能为空")
        modifier_map = {"ALT": 0x0001, "CTRL": 0x0002, "SHIFT": 0x0004, "WIN": 0x0008}
        key_name = parts[-1]
        for part in parts[:-1]:
            if part not in modifier_map:
                raise ValueError(f"不支持的修饰键：{part}")
            modifiers |= modifier_map[part]
        modifiers |= 0x4000  # MOD_NOREPEAT
        if len(key_name) == 1 and key_name.isalnum():
            return modifiers, ord(key_name)
        if key_name.startswith("F") and key_name[1:].isdigit() and 1 <= int(key_name[1:]) <= 24:
            return modifiers, 0x70 + int(key_name[1:]) - 1
        raise ValueError("快捷键主键仅支持字母、数字和 F1-F24")

    def _candidates(self, name: str, desired: str) -> list[str]:
        return list(dict.fromkeys([desired, *FALLBACK_SHORTCUTS.get(name, [])]))

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)  # 建立线程消息队列，确保可停止。

        for identifier, (name, desired) in enumerate(self._definitions.items(), start=1):
            registered = False
            invalid_reason = ""
            for shortcut in self._candidates(name, desired):
                try:
                    modifiers, virtual_key = self._parse(shortcut)
                except ValueError as error:
                    invalid_reason = str(error)
                    continue
                if user32.RegisterHotKey(None, identifier, modifiers, virtual_key):
                    self._bindings[identifier] = name
                    self._active_shortcuts[name] = shortcut
                    registered = True
                    if shortcut != desired:
                        self.status_changed.emit(f"快捷键 {desired} 被占用，已改用 {shortcut}（{name}）")
                    else:
                        self.status_changed.emit(f"已启用快捷键：{name} = {shortcut}")
                    break
            if not registered:
                reason = invalid_reason or f"{desired} 及备用组合均不可用"
                self.error_occurred.emit(f"无法启用 {name} 快捷键：{reason}")

        self.bindings_changed.emit(self.active_shortcuts)
        self._ready.set()

        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312 and message.wParam in self._bindings:
                self.activated.emit(self._bindings[message.wParam])
        for identifier in self._bindings:
            user32.UnregisterHotKey(None, identifier)
        self._bindings.clear()
