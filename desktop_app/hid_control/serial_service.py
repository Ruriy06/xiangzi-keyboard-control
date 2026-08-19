from __future__ import annotations

import threading
from dataclasses import dataclass

import serial
from PySide6.QtCore import QObject, Signal
from serial.tools import list_ports


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    hardware_id: str


class SerialService(QObject):
    message_received = Signal(str)
    message_sent = Signal(str)
    connection_changed = Signal(bool, str)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._serial: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._write_lock = threading.Lock()

    @staticmethod
    def available_ports() -> list[PortInfo]:
        return [PortInfo(port.device, port.description, port.hwid) for port in list_ports.comports()]

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def port_name(self) -> str:
        return self._serial.port if self.is_connected and self._serial else ""

    def connect(self, port: str, baud_rate: int = 115200) -> bool:
        self.disconnect()
        try:
            self._serial = serial.Serial(port=port, baudrate=baud_rate, timeout=0.15, write_timeout=1)
        except serial.SerialException as error:
            self._serial = None
            self.error_occurred.emit(f"无法打开 {port}：{error}")
            self.connection_changed.emit(False, "未连接")
            return False

        self._reader_stop.clear()
        self._reader = threading.Thread(target=self._read_loop, name="serial-reader", daemon=True)
        self._reader.start()
        self.connection_changed.emit(True, f"已连接：{port} @ {baud_rate}")
        return True

    def disconnect(self) -> None:
        self._reader_stop.set()
        serial_port = self._serial
        self._serial = None
        if serial_port is not None:
            try:
                serial_port.close()
            except serial.SerialException:
                pass
        if self._reader and self._reader.is_alive() and self._reader is not threading.current_thread():
            self._reader.join(timeout=0.5)
        self._reader = None
        self.connection_changed.emit(False, "未连接")

    def send(self, command: str) -> bool:
        if not self.is_connected or self._serial is None:
            self.error_occurred.emit("设备未连接，无法发送命令")
            return False
        try:
            payload = (command.strip() + "\n").encode("utf-8")
            with self._write_lock:
                self._serial.write(payload)
                self._serial.flush()
            self.message_sent.emit(command.strip())
            return True
        except (serial.SerialException, OSError) as error:
            self.error_occurred.emit(f"串口发送失败：{error}")
            self.disconnect()
            return False

    def send_stop(self) -> None:
        self.send("{STOP}")

    def request_device_state(self) -> None:
        self.send("{CFG_GET}")
        self.send("{SCR_GET}")

    def _read_loop(self) -> None:
        while not self._reader_stop.is_set():
            serial_port = self._serial
            if serial_port is None:
                return
            try:
                line = serial_port.readline().decode("utf-8", errors="replace").strip()
                if line:
                    self.message_received.emit(line)
            except (serial.SerialException, OSError) as error:
                if not self._reader_stop.is_set():
                    self.error_occurred.emit(f"串口读取失败：{error}")
                self.disconnect()
                return

    def close(self) -> None:
        self.send_stop()
        self.disconnect()
