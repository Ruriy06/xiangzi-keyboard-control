"""HID 通信后端（LYDR_auto6 去特征 · 阶段 C-5~C-7）。

本模块与 :mod:`serial_service` 的 ``SerialService`` 接口逐一对齐，只把底层通道
从串口（CDC/COM 口）换成 HID，使上层 UI 与流程代码无需感知差异。

协议（与固件 ``source/hid_link.h``、探针 ``source/tools/hid_probe.py`` 一致）：

* 下行 主机→设备：HID Feature report，报告 ID=3，数据长度固定 63 字节（含报告
  ID 共 64 字节）。用 hidapi 的 ``send_feature_report`` 发送：缓冲区首字节必须是
  报告 ID ``0x03``，总长必须是 64（不足用 ``0x00`` 填充）。内容是 ASCII 文本行，
  以 ``\\n`` 结尾。
* 上行 设备→主机：HID 输入报告，报告 ID=4，每包固定 64 字节（首字节 ``0x04`` +
  63 字节数据，数据以 ``0x00`` 填充）。后台线程轮询 ``hid_read``：忽略 ``0x00``
  填充字节，把非零字节按顺序拼接成字节流，遇到 ``\\n`` 切出一行（跨报告自然拼接）。

最终形态设备：单一 HID 接口（非复合）、VID=0x046A、PID=0x0001、无 CDC、无 COM 口。

⚠ 注意：探针脚本里 ``REPORT_LEN = 32`` 是早期 spike 的值；真实固件为 63，以 63 为准。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

try:  # hidapi 缺失时不能让整个模块导入失败，改为运行期给出清晰中文报错。
    import hid  # type: ignore[import-not-found]  # hidapi
except ImportError as _import_error:  # pragma: no cover - 仅在缺少依赖时触发
    hid = None  # type: ignore[assignment]
    _HID_IMPORT_ERROR: Exception | None = _import_error
else:
    _HID_IMPORT_ERROR = None


#: 最终形态设备的 USB 标识（与固件 / 打包描述一致）。
VENDOR_ID = 0x046A
PRODUCT_ID = 0x0001

#: 厂商自定义集合的标识（对应 source/hid_link.h 的报告描述符：
#: Usage Page = Vendor Defined 0xFF00、Usage = 0x01）。
#:
#: ⚠ 最终固件是「单接口 + 3 个顶层集合」：Col01 鼠标、Col02 键盘、Col03 本通道。
#:   三者的 interface_number 全都是 0，仅靠 VID/PID 无法区分。若不按 usage_page
#:   过滤，下拉框里会冒出一个鼠标和一个键盘（都是假选项），且自动选择很可能打开
#:   鼠标集合，导致下行 Feature report 直接失败。
VENDOR_USAGE_PAGE = 0xFF00

#: 报告 ID 与数据长度（与 source/hid_link.h 的宏保持一致）。
REPORT_ID_DOWN = 3  # Feature 报告：主机 → 设备
REPORT_ID_UP = 4  # Input   报告：设备 → 主机
REPORT_LEN = 63  # 每个报告的数据字节数（不含报告 ID 字节）
FEATURE_TOTAL = 1 + REPORT_LEN  # 下行 Feature 报告的完整长度（含报告 ID）= 64
LINE_TERMINATOR = 0x0A  # '\n'
READ_TIMEOUT_MS = 200  # 后台轮询间隔，兼顾响应与退出时快速收尾

_MISSING_HID_MESSAGE = "缺少 hidapi 运行库，无法使用 HID 设备通信；请先安装：pip install hidapi"


@dataclass(frozen=True)
class PortInfo:
    """与 ``serial_service.PortInfo`` 同构的设备描述。

    UI（``ui/dashboard.py`` / ``ui/main_window.py``）只用到 ``device`` 与
    ``description``：``device`` 既作为下拉项的显示文本，也作为 ``connect()`` 的入参；
    ``description`` 仅用于显示。这里用 HID 设备路径充当 ``device``（等价于串口的
    ``COM5``：一个唯一、可直接打开的设备标识）。
    """

    device: str
    description: str
    hardware_id: str


def _path_to_text(path: object) -> str:
    """把 hidapi 返回的 bytes 路径无损地转成 str（Windows 上是 ASCII，安全往返）。"""
    if isinstance(path, bytes):
        return os.fsdecode(path)
    if path is None:
        return ""
    return str(path)


def _text_to_path(text: str) -> bytes:
    return os.fsencode(text)


def _encode_line(command: str) -> bytes:
    """把一条命令编码为下行文本行（末尾带 ``\\n``），与串口版一致。"""
    return (command.strip() + "\n").encode("ascii", "replace")


class HidService(QObject):
    """HID 版通信后端，接口与 ``SerialService`` 逐一对齐。"""

    message_received = Signal(str)
    message_sent = Signal(str)
    connection_changed = Signal(bool, str)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._device: "hid.device | None" = None
        self._device_path = ""
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._write_lock = threading.Lock()

    @staticmethod
    def available_ports() -> list[PortInfo]:
        """返回 VID/PID 匹配的 HID 设备，属性与串口 ``PortInfo`` 兼容。"""
        if hid is None:
            return []
        try:
            entries = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        except Exception:
            return []
        devices: list[PortInfo] = []
        for entry in entries:
            if entry.get("vendor_id") != VENDOR_ID or entry.get("product_id") != PRODUCT_ID:
                continue
            # 只保留厂商自定义集合（Col03）：同一个 VID/PID 下还有鼠标与键盘集合，
            # 它们的 usage_page 是 0x0001，必须滤掉，否则会成为可选中的假设备。
            if entry.get("usage_page") != VENDOR_USAGE_PAGE:
                continue
            path = entry.get("path")
            if not path:
                continue
            product = entry.get("product_string") or "HID 设备"
            interface = entry.get("interface_number")
            interface_text = "" if interface is None else f"，接口 {interface}"
            description = (
                f"{product}（VID:0x{VENDOR_ID:04X} PID:0x{PRODUCT_ID:04X}{interface_text}）"
            )
            hardware_id = f"HID VID:PID={VENDOR_ID:04X}:{PRODUCT_ID:04X}"
            devices.append(PortInfo(_path_to_text(path), description, hardware_id))
        return devices

    @property
    def is_connected(self) -> bool:
        return self._device is not None

    @property
    def port_name(self) -> str:
        return self._device_path if self.is_connected else ""

    def connect(self, port: str, baud_rate: int = 115200) -> bool:
        """打开 HID 设备并启动后台读取线程。

        ``baud_rate`` 仅为对齐 ``SerialService.connect`` 签名而保留；HID 不使用波特率。
        """
        self.disconnect()
        if hid is None:
            self.error_occurred.emit(_MISSING_HID_MESSAGE)
            self.connection_changed.emit(False, "未连接")
            return False
        try:
            device = hid.device()
            device.open_path(_text_to_path(port))
            try:
                # 阻塞 + 超时读取，便于后台线程周期性检查停止标志。
                device.set_nonblocking(0)
            except Exception:
                pass
        except Exception as error:
            self.error_occurred.emit(f"无法打开 HID 设备 {port}：{error}")
            self.connection_changed.emit(False, "未连接")
            return False

        self._device = device
        self._device_path = port
        self._reader_stop.clear()
        self._reader = threading.Thread(target=self._read_loop, name="hid-reader", daemon=True)
        self._reader.start()
        self.connection_changed.emit(True, f"已连接：{self._describe(port)}")
        return True

    def disconnect(self) -> None:
        self._reader_stop.set()
        device = self._device
        self._device = None
        self._device_path = ""
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        if self._reader and self._reader.is_alive() and self._reader is not threading.current_thread():
            self._reader.join(timeout=0.5)
        self._reader = None
        self.connection_changed.emit(False, "未连接")

    def send(self, command: str) -> bool:
        if not self.is_connected or self._device is None:
            self.error_occurred.emit("设备未连接，无法发送命令")
            return False
        payload = _encode_line(command)
        try:
            with self._write_lock:
                device = self._device
                if device is None:
                    raise OSError("设备已断开")
                # 首字节固定为报告 ID；每条报告总长必须为 64 字节（不足补 0x00）。
                # 常规命令一包即可；超长行按 63 字节分片（固件端会忽略 0x00 并拼接）。
                for offset in range(0, len(payload), REPORT_LEN):
                    chunk = payload[offset:offset + REPORT_LEN]
                    buffer = bytes([REPORT_ID_DOWN]) + chunk
                    buffer += b"\x00" * (FEATURE_TOTAL - len(buffer))
                    device.send_feature_report(buffer)
        except Exception as error:
            self.error_occurred.emit(f"HID 设备发送失败：{error}")
            self.disconnect()
            return False
        self.message_sent.emit(command.strip())
        return True

    def send_stop(self) -> None:
        self.send("{STOP}")

    def request_device_state(self) -> None:
        self.send("{CFG_GET}")
        self.send("{SCR_GET}")

    def close(self) -> None:
        self.send_stop()
        self.disconnect()

    @staticmethod
    def _describe(port: str) -> str:
        """把设备路径转成更友好的描述，找不到时退回路径本身。"""
        for info in HidService.available_ports():
            if info.device == port:
                return info.description
        return port

    def _read_loop(self) -> None:
        buffer = bytearray()
        while not self._reader_stop.is_set():
            device = self._device
            if device is None:
                return
            try:
                report = device.read(FEATURE_TOTAL, READ_TIMEOUT_MS)
            except Exception as error:
                if not self._reader_stop.is_set():
                    self.error_occurred.emit(f"HID 设备读取失败：{error}")
                self.disconnect()
                return
            if not report:
                continue
            data = bytes(report)
            # 首字节是报告 ID（0x04），需要跳过；若底层未带报告 ID 则整体视为数据。
            payload = data[1:] if data and data[0] == REPORT_ID_UP else data
            for value in payload:
                if value == 0:  # 忽略 0x00 填充
                    continue
                if value == LINE_TERMINATOR:
                    line = bytes(buffer).decode("utf-8", "replace").strip()
                    buffer.clear()
                    if line:
                        self.message_received.emit(line)
                    continue
                buffer.append(value)
