from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QGridLayout, QGroupBox, QPushButton, QSizePolicy


# 键帽文字、发送给固件的稳定键名、横向占位、中文说明。
KEYBOARD_ROWS = [
    [("Esc\n退出", "ESC", 1, "退出/取消"), *[(f"F{number}\n功能键", f"F{number}", 1, f"功能键 F{number}") for number in range(1, 13)], ("Del\n删除", "DELETE", 1, "删除右侧字符或项目")],
    [("`\n反引号", "GRAVE", 1, "反引号"), *[(str(number), str(number), 1, f"数字 {number}") for number in range(1, 10)], ("0\n数字", "0", 1, "数字 0"), ("-\n减号", "MINUS", 1, "减号"), ("=\n等号", "EQUAL", 1, "等号"), ("Backspace\n删除左侧", "BACKSPACE", 2, "删除左侧字符")],
    [("Tab\n切换", "TAB", 2, "切换焦点"), *[(letter, letter, 1, f"字母 {letter}") for letter in "QWERTYUIOP"], ("[\n左中括号", "LBRACKET", 1, "左中括号"), ("]\n右中括号", "RBRACKET", 1, "右中括号"), ("\\\n反斜杠", "BACKSLASH", 1, "反斜杠")],
    [("Caps\n大写锁定", "CAPS_LOCK", 2, "切换大写锁定"), *[(letter, letter, 1, f"字母 {letter}") for letter in "ASDFGHJKL"], (";\n分号", "SEMICOLON", 1, "分号"), ("'\n引号", "QUOTE", 1, "单引号"), ("Enter\n确认", "ENTER", 2, "确认/换行")],
    [("Shift\n上档", "SHIFT", 2, "上档修饰键"), *[(letter, letter, 1, f"字母 {letter}") for letter in "ZXCVBNM"], (",\n逗号", "COMMA", 1, "逗号"), (".\n句点", "PERIOD", 1, "句点"), ("/\n斜杠", "SLASH", 1, "斜杠"), ("Shift\n上档", "SHIFT", 2, "上档修饰键"), ("↑\n上", "UP", 1, "向上方向键")],
    [("Ctrl\n控制", "CTRL", 1, "控制修饰键"), ("Win\n系统", "WIN", 1, "Windows 系统键"), ("Alt\n替代", "ALT", 1, "Alt 修饰键"), ("Space\n空格", "SPACE", 5, "空格"), ("Alt\n替代", "ALT", 1, "Alt 修饰键"), ("Menu\n菜单", "MENU", 1, "应用菜单键"), ("Ctrl\n控制", "CTRL", 1, "控制修饰键"), ("←\n左", "LEFT", 1, "向左方向键"), ("↓\n下", "DOWN", 1, "向下方向键"), ("→\n右", "RIGHT", 1, "向右方向键")],
]


class KeyboardPicker(QGroupBox):
    key_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__("75% 键盘选择器（Fn 属于键盘硬件层，不能通过 USB 命令发送）")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # 标题 + 六排键帽 + 网格间距；保证不依赖内部滚动也能完整显示。
        self.setMinimumHeight(270)
        layout = QGridLayout(self)
        layout.setContentsMargins(5, 7, 5, 5)
        layout.setVerticalSpacing(3)
        layout.setHorizontalSpacing(3)
        for row, keys in enumerate(KEYBOARD_ROWS):
            column = 0
            for label, key_code, span, description in keys:
                button = QPushButton(label)
                button.setObjectName("keyboardKey")
                button.setToolTip(f"{description}\n固件键名：{key_code}")
                button.setMinimumHeight(28)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.clicked.connect(lambda checked=False, code=key_code: self.key_selected.emit(code))
                layout.addWidget(button, row, column, 1, span)
                column += span
        for row in range(len(KEYBOARD_ROWS)):
            layout.setRowStretch(row, 1)

    def sizeHint(self) -> QSize:
        return QSize(760, 270)

    def minimumSizeHint(self) -> QSize:
        return QSize(560, 270)
