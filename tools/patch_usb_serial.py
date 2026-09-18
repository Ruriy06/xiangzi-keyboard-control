#!/usr/bin/env python3
"""让固件不再声明 USB 序列号（iSerial=0），抹掉 "HIDFG" 指纹。

背景
----
核心 ``USBCore.cpp`` 的设备描述符把 iSerial 写死为 ``ISERIAL``(=3)，而 Arduino 的
HID 组件用 ``getShortName()`` 生成固定串（``libraries/HID/src/HID.cpp:65``）：

    name[3] = 'A' + (descriptorSize & 0x0F);
    name[4] = 'A' + ((descriptorSize >> 4) & 0x0F);

``descriptorSize == 0x65`` → ``'A'+5='F'``、``'A'+6='G'`` → **``HIDFG``**。
于是所有跑 Keyboard+Mouse 的 Leonardo 序列号完全相同，是一枚公开指纹。

把描述符里的 iSerial 改成 ``0`` 后，设备不声明序列号，Windows 退回基于物理位置的
实例 ID（``USB\\VID_xxxx&PID_xxxx\\7&xxxxxxxx&0&N``），与绝大多数真实键盘一致。

幂等性
------
重复执行不会重复改动；脚本先备份原文件到 ``.build-tools/backup/USBCore.cpp.orig``。
Arduino 核心升级覆盖掉此文件后，重新执行本脚本即可再次生效。

用法
----
    python source/tools/patch_usb_serial.py            # 应用补丁
    python source/tools/patch_usb_serial.py --check     # 只检查，不改动
    python source/tools/patch_usb_serial.py --revert    # 从备份还原
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

CORE_DIR = Path(
    r"C:\Users\21915\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\cores\arduino"
)
TARGET = CORE_DIR / "USBCore.cpp"
BACKUP = Path(r"F:\祥子的宝贝\.build-tools\backup\USBCore.cpp.orig")

#: 只替换 D_DEVICE(...) 同一行内的 ISERIAL；
#: GET_DESCRIPTOR 里的 `setup.wValueL == ISERIAL` 不受影响（iSerial=0 后该分支不再被访问）。
PATTERN = re.compile(r"(D_DEVICE\([^\n]*?,)ISERIAL(,)")
REPLACEMENT = r"\g<1>0\g<2>"


def read() -> str:
    with TARGET.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write(text: str) -> None:
    with TARGET.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def ensure_backup(text: str) -> bool:
    if BACKUP.exists():
        return False
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    with BACKUP.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return True


def locate(text: str) -> list[int]:
    """返回所有 D_DEVICE 行内 ISERIAL 的行号（1 起）。"""
    return [
        index
        for index, line in enumerate(text.splitlines(), start=1)
        if PATTERN.search(line)
    ]


def main() -> int:
    if not TARGET.exists():
        print(f"[错误] 找不到核心文件：{TARGET}", file=sys.stderr)
        return 1

    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "--revert":
        if not BACKUP.exists():
            print(f"[错误] 没有备份可还原：{BACKUP}", file=sys.stderr)
            return 1
        shutil.copyfile(BACKUP, TARGET)
        print(f"[还原] 已从备份恢复 {TARGET}")
        return 0

    text = read()
    lines = locate(text)

    if not lines:
        print("[跳过] 已是目标状态（描述符未声明序列号），无需改动。")
        return 0

    print(f"[发现] 需修改 {len(lines)} 处，行号：{', '.join(map(str, lines))}")
    for number in lines:
        print(f"  改前 L{number}: {text.splitlines()[number - 1].strip()}")

    if mode == "--check":
        print("[检查] 仅检查模式，未改动文件。")
        return 0

    if ensure_backup(text):
        print(f"[备份] 原文件已备份到 {BACKUP}")
    else:
        print(f"[备份] 备份已存在，保留既有副本 {BACKUP}")

    patched, count = PATTERN.subn(REPLACEMENT, text)
    assert count == len(lines), f"替换数 {count} 与预期 {len(lines)} 不一致"

    for number in lines:
        print(f"  改后 L{number}: {patched.splitlines()[number - 1].strip()}")

    write(patched)
    print(f"[完成] 已写回 {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
