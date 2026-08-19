from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QHBoxLayout, QSizePolicy, QWidget


UNITS = (("毫秒", 1), ("秒", 1_000), ("分钟", 60_000))


def format_duration(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    if milliseconds and milliseconds % 60_000 == 0:
        return f"{milliseconds / 60_000:g} 分钟"
    if milliseconds and milliseconds % 1_000 == 0:
        return f"{milliseconds / 1_000:g} 秒"
    return f"{milliseconds} 毫秒"


class DurationInput(QWidget):
    value_changed = Signal(int)

    def __init__(self, maximum_milliseconds: int = 86_400_000, allow_zero: bool = True) -> None:
        super().__init__()
        self._maximum_milliseconds = maximum_milliseconds
        self._allow_zero = allow_zero
        self._last_milliseconds = 0 if allow_zero else 1
        self.amount = QDoubleSpinBox()
        self.amount.setDecimals(6)
        self.amount.setSingleStep(1)
        self.amount.setMinimumWidth(92)
        self.amount.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.unit = QComboBox()
        self.unit.setMinimumWidth(72)
        self.unit.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        for name, multiplier in UNITS:
            self.unit.addItem(name, multiplier)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.amount, 1)
        layout.addWidget(self.unit)
        self.amount.valueChanged.connect(self._emit_value)
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self.set_milliseconds(0 if allow_zero else 1)

    def milliseconds(self) -> int:
        return int(round(self.amount.value() * int(self.unit.currentData())))

    def set_milliseconds(self, milliseconds: int) -> None:
        milliseconds = max(0 if self._allow_zero else 1, min(self._maximum_milliseconds, int(milliseconds)))
        self._last_milliseconds = milliseconds
        if milliseconds and milliseconds % 60_000 == 0:
            unit_index = 2
        elif milliseconds and milliseconds % 1_000 == 0:
            unit_index = 1
        else:
            unit_index = 0
        multiplier = UNITS[unit_index][1]
        self.amount.blockSignals(True)
        self.unit.blockSignals(True)
        self.unit.setCurrentIndex(unit_index)
        self.amount.setRange(0 if self._allow_zero else 0.001, self._maximum_milliseconds / multiplier)
        self.amount.setValue(milliseconds / multiplier)
        self.unit.blockSignals(False)
        self.amount.blockSignals(False)

    def _unit_changed(self) -> None:
        multiplier = int(self.unit.currentData())
        self.amount.blockSignals(True)
        self.amount.setRange(0 if self._allow_zero else 0.001, self._maximum_milliseconds / multiplier)
        self.amount.setValue(min(self._maximum_milliseconds / multiplier, self._last_milliseconds / multiplier))
        self.amount.blockSignals(False)
        self._emit_value()

    def _emit_value(self) -> None:
        self._last_milliseconds = self.milliseconds()
        self.value_changed.emit(self._last_milliseconds)
