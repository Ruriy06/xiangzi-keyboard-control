#!/usr/bin/env python3
"""从 Intel HEX 固件镜像里提取并校验 USB 描述符。

用途：不插设备也能确认"烧进去的到底是什么身份、暴露了几个接口"。
直接解析 .hex 还原真实烧录字节（比在 .elf 上乱搜可靠，.elf 里混着 DWARF 调试信息）。

用法：
    python source/tools/inspect_usb_descriptors.py <file.hex> [<file2.hex> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

# 描述符类型
DT_DEVICE = 0x01
DT_CONFIG = 0x02
DT_STRING = 0x03
DT_INTERFACE = 0x04
DT_ENDPOINT = 0x05
DT_IAD = 0x0B
DT_CS_INTERFACE = 0x24
DT_HID = 0x21

IF_CLASS_NAMES = {
    0x00: "reserved",
    0x01: "Audio",
    0x02: "CDC-COMM",
    0x03: "HID",
    0x07: "Printer",
    0x08: "MassStorage",
    0x0A: "CDC-DATA",
    0x0B: "SmartCard",
    0x0E: "Video",
    0xDC: "Diagnostic",
    0xE0: "Wireless",
    0xEF: "Misc/IAD",
    0xFE: "AppSpecific",
}


def parse_intel_hex(path: Path) -> bytes:
    """Intel HEX -> 扁平镜像（按地址放置，未覆盖处为 0xFF）。"""
    image = bytearray(b"\xff" * 65536)
    base = 0
    for raw in path.read_text(encoding="ascii", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith(":"):
            continue
        rec = bytes.fromhex(line[1:])
        count, addr, rtype = rec[0], (rec[1] << 8) | rec[2], rec[3]
        data = rec[4:4 + count]
        if rtype == 0x00:  # 数据
            start = base + addr
            image[start:start + count] = data
        elif rtype == 0x04:  # 扩展线性地址
            base = ((data[0] << 8) | data[1]) << 16
    return bytes(image)


def classify(blob: bytes) -> str:
    """按 USB 描述符链校验一段字节是否构成完整、合法的配置描述符。"""
    if len(blob) < 9 or blob[0] != 9 or blob[1] != DT_CONFIG:
        return ""
    total = blob[2] | (blob[3] << 8)
    num_if = blob[4]
    if not (9 <= total <= 200) or len(blob) < total:
        return ""
    # 逐条遍历描述符链，长度字段必须自洽
    i, interfaces, endpoints = 2, [], []
    while i < total:
        blen = blob[i]
        if blen < 2 or i + blen > total:
            return ""
        btype = blob[i + 1]
        if btype == DT_INTERFACE:
            if blen != 9:
                return ""
            interfaces.append((blob[i + 2], blob[i + 5], blob[i + 6], blob[i + 7]))
        elif btype == DT_ENDPOINT:
            endpoints.append((blob[i + 2], blob[i + 3]))
        elif btype not in (DT_IAD, DT_CS_INTERFACE, DT_HID):
            return ""
        i += blen
    if i != total or len(interfaces) != num_if:
        return ""
    lines = [f"    总长={total}  接口数={num_if}  bmAttr=0x{blob[7]:02x}  bMaxPower={blob[8] * 2}mA"]
    for num, cls, sub, proto in interfaces:
        lines.append(
            f"      接口{num}: class=0x{cls:02x} ({IF_CLASS_NAMES.get(cls, '?')}) sub=0x{sub:02x} proto=0x{proto:02x}"
        )
    for addr, attr in endpoints:
        direction = "IN " if addr & 0x80 else "OUT"
        lines.append(f"        端点 0x{addr:02x} {direction} type={(attr & 0x03)}")
    return "\n".join(lines)


def report(path: Path) -> None:
    img = parse_intel_hex(path)
    print(f"── {path.name} " + "─" * max(0, 46 - len(path.name)))

    # 设备描述符
    dev_pat = bytes([0x12, 0x01, 0x00, 0x02])
    n_dev = n_cfg = 0
    off = 0
    while True:
        off = img.find(dev_pat, off)
        if off < 0:
            break
        blk = img[off:off + 18]
        if len(blk) == 18 and blk[17] == 1:  # bNumConfigurations == 1
            vid = blk[8] | (blk[9] << 8)
            pid = blk[10] | (blk[11] << 8)
            print(f"  设备描述符 @0x{off:04x}")
            print(f"    VID=0x{vid:04X}  PID=0x{pid:04X}")
            print(f"    bDeviceClass=0x{blk[4]:02x} sub=0x{blk[5]:02x} proto=0x{blk[6]:02x} "
                  f"({'IAD 复合' if blk[4] == 0xEF else '非复合'})")
            print(f"    iManufacturer={blk[14]}  iProduct={blk[15]}  iSerial={blk[16]}"
                  + ("   <- 无序列号" if blk[16] == 0 else ""))
            n_dev += 1
        off += 1

    # 配置描述符：全镜像扫描 + 链校验（用链自洽过滤掉 .rodata 噪声）
    for off in range(len(img) - 9):
        if img[off] == 9 and img[off + 1] == DT_CONFIG:
            desc = classify(img[off:off + 200])
            if desc:
                print(f"  配置描述符 @0x{off:04x}")
                print(desc)
                n_cfg += 1

    # 字符串描述符
    for pat in (b"Cherry", b"USB Keyboard", b"Arduino Leonardo", b"Arduino LLC",
                b"SiGma Micro", b"HIDFG"):
        if pat in img:
            print(f"  字符串: {pat.decode('ascii')!r} 出现 {img.count(pat)} 次")

    print(f"  → 设备描述符 {n_dev} 个, 合法配置描述符 {n_cfg} 个")
    print()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.is_file():
            print(f"跳过（不存在）: {arg}")
            continue
        report(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
