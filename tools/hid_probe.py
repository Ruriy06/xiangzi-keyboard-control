#!/usr/bin/env python3
"""HID Feature report 通道探针（LYDR_auto6 去特征）

验证「主机 ↔ 设备」双向通道在 HID 上真的能跑通。

用法：
    python source/tools/hid_probe.py --list
    python source/tools/hid_probe.py                       # 发 {PING}（按最终固件长度 63）
    python source/tools/hid_probe.py "{CFG_GET}"           # 发自定义行
    python source/tools/hid_probe.py --len 32 "{PING}"     # 早期 spike 固件（报告 32 字节）
    python source/tools/hid_probe.py --pid 0x0002 "{PING}" # 指定 PID

协议（与固件一致）：
    下行 = HID Feature report(ID=3)：长度 = 1 + 报告长度（首字节为报告 ID），NUL 填充
    上行 = HID 输入报告(ID=4)：主机轮询读取；忽略 0x00 填充字节，按 '\n' 切行

报告长度：
    最终固件 source/hid_link.h 用 63；早期 spike 用 32（用 --len 指定）。

依赖：pip install hidapi
"""
import sys
import time

VID = 0x046A
REPORT_ID_DOWN = 3
REPORT_ID_UP = 4
# 报告数据长度（不含报告 ID 字节），可用 --len 覆盖。
DEFAULT_REPORT_LEN = 63


def load_hid():
    try:
        import hid  # hidapi
        return hid
    except ImportError:
        print("缺少 hidapi，请先安装：pip install hidapi", file=sys.stderr)
        raise SystemExit(2)


def candidates(hid, pid):
    out = []
    for d in hid.enumerate():
        if d.get("vendor_id") != VID:
            continue
        if pid is not None and d.get("product_id") != pid:
            continue
        out.append(d)
    return out


def show(devs):
    if not devs:
        print("未发现 VID=0x%04X 的 HID 设备。" % VID)
        return
    for d in devs:
        print(
            "  VID=0x%04X PID=0x%04X iface=%s usage_page=0x%04X usage=0x%04X\n"
            "    product=%r manufacturer=%r\n    path=%s"
            % (
                d.get("vendor_id", 0),
                d.get("product_id", 0),
                d.get("interface_number"),
                d.get("usage_page", 0),
                d.get("usage", 0),
                d.get("product_string"),
                d.get("manufacturer_string"),
                d.get("path"),
            )
        )


def main(argv):
    hid = load_hid()

    pid = 0x0001
    report_len = DEFAULT_REPORT_LEN
    args = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--list":
            show(candidates(hid, None))
            return 0
        if a == "--pid":
            i += 1
            pid = int(argv[i], 0)
        elif a.startswith("--pid="):
            pid = int(a.split("=", 1)[1], 0)
        elif a == "--len":
            i += 1
            report_len = int(argv[i], 0)
        elif a.startswith("--len="):
            report_len = int(a.split("=", 1)[1], 0)
        else:
            args.append(a)
        i += 1

    line = args[0] if args else "{PING}"
    if not line.endswith("\n"):
        line += "\n"

    devs = candidates(hid, pid)
    print("枚举 VID=0x%04X PID=0x%04X 的 HID 设备（报告长度 %d）：" % (VID, pid, report_len))
    show(devs)
    if not devs:
        print("\n[HINT] 设备未出现：确认固件已烧入、设备已插好、Windows 已绑定 HID 驱动。")
        return 1

    # 优先选「厂商自定义集合」(usage_page=0xFF00)。最终固件是单接口 + 3 个顶层集合
    # （Mouse/Keyboard/vendor），三个节点的 interface_number 都是 0，若不按 usage_page
    # 区分，会随机打开鼠标或键盘集合，导致下行 Feature report 失败。
    dev_info = sorted(
        devs,
        key=lambda d: (
            0 if d.get("usage_page") == 0xFF00 else 1,
            d.get("interface_number") or 0,
        ),
    )[0]
    dev = hid.device()
    dev.open_path(dev_info["path"])
    try:
        dev.set_nonblocking(0)
    except Exception:
        pass

    print("\n已打开：%s" % dev_info["path"])

    # ── 下行：Feature report（长度必须是 1 + report_len，首字节为报告 ID）──
    payload = line.encode("ascii", "replace")[:report_len]
    buf = bytes([REPORT_ID_DOWN]) + payload + b"\x00" * (report_len - len(payload))
    print("下行 send_feature_report(%d 字节, %r) ..." % (len(buf), line.strip()))
    try:
        n = dev.send_feature_report(buf)
        print("  -> 返回 %s" % n)
    except Exception as e:
        print("  -> 异常：%r" % (e,))

    # ── 上行：输入报告（忽略 NUL 填充，按 '\n' 切行）────────────────
    print("上行 轮询输入报告（最多 2 秒）...")
    got = False
    acc = bytearray()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            data = dev.read(report_len + 1, 300)
        except Exception as e:
            print("  read 异常：%r" % (e,))
            break
        if not data:
            continue
        b = bytes(data)
        rid = b[0] if b else -1
        print("  收到 %d 字节，report_id=%d" % (len(b), rid))
        body = b[1:] if (b and b[0] == REPORT_ID_UP) else b
        acc.extend(x for x in body if x != 0)
        while 0x0A in acc:
            k = acc.index(0x0A)
            text = bytes(acc[:k])
            del acc[: k + 1]
            got = True
            print("    文本行 = %r" % text.decode("ascii", "replace"))
    if not got:
        print("  （2 秒内没有解析出完整文本行）")

    # ── 对照：Get_Report(Feature) 预期被 HID 库拦下（HID_::setup 对 GET_REPORT
    #    返回 true 但不发数据），用来确认链路确实落在了 HID 接口上 ──
    try:
        r = dev.get_feature_report(REPORT_ID_DOWN, 1 + report_len)
        print("对照 get_feature_report(ID=%d) -> %d 字节 %r"
              % (REPORT_ID_DOWN, len(r), bytes(r)[:16]))
    except Exception as e:
        print("对照 get_feature_report 异常：%r" % (e,))

    dev.close()
    return 0 if got else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
