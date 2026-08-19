from __future__ import annotations

from .models import ActionKind, ActionStep, DeviceSettings


NAMED_KEYS = {
    "CTRL", "SHIFT", "ALT", "WIN", "ESC", "TAB", "ENTER", "SPACE", "BACKSPACE",
    "CAPS_LOCK", "DELETE", "INSERT", "HOME", "END", "PAGE_UP", "PAGE_DOWN",
    "PRINT_SCREEN", "SCROLL_LOCK", "PAUSE", "MENU",
    "GRAVE", "MINUS", "EQUAL", "LBRACKET", "RBRACKET", "BACKSLASH", "SEMICOLON",
    "QUOTE", "COMMA", "PERIOD", "SLASH",
    "UP", "DOWN", "LEFT", "RIGHT", *(f"F{number}" for number in range(1, 13)),
}
MOUSE_BUTTONS = {"LEFT", "RIGHT", "MIDDLE", "BACK", "FORWARD"}


class ProtocolError(ValueError):
    pass


def wrapped(command: str) -> str:
    command = command.strip().strip("{}")
    if not command or len(command) > 61:
        raise ProtocolError("串口命令不能为空且内容不能超过 61 个字符")
    return "{" + command + "}"


def normalize_key(value: str) -> str:
    key = value.strip().upper()
    if len(key) == 1 and key not in {"{", "}"}:
        return key
    if key in NAMED_KEYS:
        return key
    raise ProtocolError(f"不支持的按键：{value}")


def positive_pair(value: str, lower: int, upper: int, label: str) -> tuple[int, int]:
    try:
        first_text, second_text = value.split("_", 1)
        first, second = int(first_text), int(second_text)
    except ValueError as error:
        raise ProtocolError(f"{label}必须是 X_Y 格式") from error
    if not lower <= first <= upper or not lower <= second <= upper:
        raise ProtocolError(f"{label}必须在 {lower} 到 {upper} 之间")
    return first, second


def command_for_step(step: ActionStep) -> str | None:
    kind = ActionKind(step.kind)
    value = step.value.strip()
    if kind is ActionKind.WAIT:
        return None
    if kind is ActionKind.KEY_TAP:
        return wrapped(normalize_key(value))
    if kind is ActionKind.KEY_COMBO:
        pieces = [normalize_key(item) for item in value.split("+") if item.strip()]
        if len(pieces) < 2:
            raise ProtocolError("组合键至少需要两个按键，例如 CTRL+C")
        return wrapped("+".join(pieces))
    if kind in {ActionKind.KEY_DOWN, ActionKind.KEY_UP}:
        prefix = "KEY_DOWN_" if kind is ActionKind.KEY_DOWN else "KEY_UP_"
        return wrapped(prefix + normalize_key(value))
    if kind is ActionKind.MOUSE_CLICK:
        button = value.upper()
        if button not in MOUSE_BUTTONS:
            raise ProtocolError("鼠标按键必须是 LEFT、RIGHT、MIDDLE、BACK 或 FORWARD")
        return wrapped(f"{button}_CLICK")
    if kind in {ActionKind.MOUSE_BUTTON_DOWN, ActionKind.MOUSE_BUTTON_UP}:
        button = value.upper()
        if button not in MOUSE_BUTTONS:
            raise ProtocolError("鼠标按键必须是 LEFT、RIGHT、MIDDLE、BACK 或 FORWARD")
        suffix = "PRESS" if kind is ActionKind.MOUSE_BUTTON_DOWN else "RELEASE"
        return wrapped(f"{button}_{suffix}")
    if kind is ActionKind.MOVE_PIXEL:
        x, y = positive_pair(value, 0, 32767, "像素坐标")
        return wrapped(f"MOVE_{x}_{y}")
    if kind is ActionKind.MOVE_NORMALIZED:
        x, y = positive_pair(value, 0, 1000, "比例坐标")
        return wrapped(f"MOVE_NORM_{x}_{y}")
    if kind is ActionKind.MOVE_RELATIVE:
        try:
            x_text, y_text = value.split("_", 1)
            x, y = int(x_text), int(y_text)
        except ValueError as error:
            raise ProtocolError("相对移动必须是 DX_DY 格式") from error
        return wrapped(f"MOVE_REL_{x}_{y}")
    if kind is ActionKind.WHEEL:
        amount = int(value)
        if not -127 <= amount <= 127:
            raise ProtocolError("滚轮范围必须是 -127 到 127")
        return wrapped(f"WHEEL_{amount}")
    if kind is ActionKind.RAW:
        return wrapped(value)
    raise ProtocolError(f"未知动作类型：{step.kind}")


def wait_milliseconds(step: ActionStep) -> int:
    try:
        milliseconds = int(step.value)
    except ValueError as error:
        raise ProtocolError("等待时间必须是毫秒整数") from error
    if not 0 <= milliseconds <= 3_600_000:
        raise ProtocolError("等待时间必须在 0 到 3600000ms 之间")
    return milliseconds


def device_configuration_commands(settings: DeviceSettings) -> list[str]:
    return [
        wrapped(f"SCR_{settings.screen_width}_{settings.screen_height}"),
        wrapped(f"CFG_KEY_PRESS_{settings.key_press_delay}"),
        wrapped(f"CFG_KEY_RELEASE_{settings.key_release_delay}"),
        wrapped(f"CFG_COMBO_HOLD_{settings.combo_hold_delay}"),
        wrapped(f"CFG_MOUSE_PRESS_{settings.mouse_press_delay}"),
        wrapped(f"CFG_MOUSE_CLICK_{settings.mouse_click_delay}"),
        wrapped(f"CFG_MOUSE_MOVE_{settings.mouse_move_delay}"),
        wrapped(f"CFG_MAX_JUMP_{settings.max_jump}"),
    ]
