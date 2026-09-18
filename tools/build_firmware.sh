#!/usr/bin/env bash
# 构建（并可选烧录）LYDR_auto6 固件。
#
# 设备身份（VID/PID/厂商串/产品串）与 CDC 开关都集中在下方常量，
# 只改这一处即可整体替换，不会污染共享的 Arduino 核心安装。
#
# 用法：
#   source/tools/build_firmware.sh                # 只编译（CDC 默认保留）
#   CDC_MODE=off source/tools/build_firmware.sh   # 编译并关闭 CDC（最终形态）
#   source/tools/build_firmware.sh --upload COM3  # 编译后烧录到 COM3
#
# 注意：烧入 CDC_MODE=off 的固件后设备不再有虚拟串口，
#       后续烧录需要手动进入 bootloader（Leonardo 双击 RESET）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI="$ROOT/.build-tools/arduino-cli.exe"
WORK="$ROOT/.build-tools/sketch/LYDR_auto6"
BUILD="$ROOT/.build-tools/build"
FQBN="arduino:avr:leonardo"

# ── 设备身份（USB 描述符）────────────────────────────────
# ⚠ 已实测的关键坑：Windows 内置驱动 input.inf 里硬编码了一条 USB 级记录
#     USB\VID_046A&PID_0001 -> HID_Inst   （显示名 "Cherry GmbH USB Keyboard"）
#   硬件 ID 的匹配优先级高于 usb.inf 的兼容 ID USB\COMPOSITE。所以只要设备带
#   CDC（即复合设备）而 PID 取 0x0001，Windows 就会把 HidUsb 直接挂到整个复合
#   设备节点上：设备无法启动（Code 10），并且根本不会生成 usbccgp 父节点和 CDC
#   接口（表现为：无 COM 口、无 MI_xx 子接口、只有单个 HID 节点）。
#   拔插、换 USB 口、重烧固件都无法改变这一点——它是纯粹的驱动匹配问题。
#   usb.inf 另占用 USB\VID_046A&PID_0003（Cherry USB-Hub），同样要避开。
#   → 因此按 CDC 形态选 PID：
#       带 CDC 的开发固件  用 0x0002（未被任何 inf 收录）
#       最终关闭 CDC 的形态 用 0x0001（那时设备本来就是普通单一 HID 键盘，
#                                    HidUsb 正是正确的驱动，冲突无害，还能
#                                    顺带得到 "Cherry GmbH USB Keyboard" 显示名）
USB_VID="0x046A"            # Cherry GmbH 的厂商 ID
USB_PRODUCT="USB Keyboard"
USB_MANUFACTURER="Cherry"

# ── CDC 虚拟串口开关：on 保留 / off 彻底移除 ─────────────
CDC_MODE="${CDC_MODE:-on}"

if [[ "$CDC_MODE" == "off" ]]; then
  USB_PID="0x0001"          # 最终形态：单一 HID 接口，见上方说明
else
  USB_PID="0x0002"          # 开发形态：必须避开 input.inf 的 0x0001
fi

PROPS=(
  --build-property "build.vid=$USB_VID"
  --build-property "build.pid=$USB_PID"
  --build-property "build.usb_product=\"$USB_PRODUCT\""
  --build-property "build.usb_manufacturer=\"$USB_MANUFACTURER\""
)

if [[ "$CDC_MODE" == "off" ]]; then
  # -DCDC_DISABLED 会让整个 CDC.cpp 退出构建，Serial 对象随之消失。
  # 此时若 sketch 仍在引用 Serial，链接会以 "undefined reference to `Serial'"
  # 失败；那种报错很难看出根因，所以在这里提前拦下并给出明确指引。
  if grep -qE '\bSerial\.' "$ROOT/source/LYDR_auto6.ino" 2>/dev/null; then
    echo "[build] 错误：CDC_MODE=off 会移除 Serial 对象，但 LYDR_auto6.ino 仍在使用 Serial。" >&2
    echo "[build]       请先完成阶段 C（用 hid_link.h 替换全部 Serial 收发），再关闭 CDC。" >&2
    exit 3
  fi
  PROPS+=(--build-property "compiler.cpp.extra_flags=-DCDC_DISABLED")
  echo "[build] CDC 已关闭（设备将不再出现 COM 口，后续只能手动进 bootloader 烧录）"
else
  echo "[build] CDC 保留（便于反复烧录）"
fi

# Arduino 要求 sketch 目录名与 .ino 同名，故复制到工作目录再编译；
# 一并复制 .h，供 hid_link.h 等本地头文件使用。
mkdir -p "$WORK"
shopt -s nullglob
sources=("$ROOT/source/"*.ino "$ROOT/source/"*.h)
shopt -u nullglob
if (( ${#sources[@]} )); then
  cp "${sources[@]}" "$WORK/"
fi

echo "[build] 身份 ${USB_VID}:${USB_PID} 厂商=\"${USB_MANUFACTURER}\" 产品=\"${USB_PRODUCT}\""
"$CLI" compile --fqbn "$FQBN" --build-path "$BUILD" "${PROPS[@]}" "$WORK"

echo "[build] 产物："
ls -1 "$BUILD"/*.hex "$BUILD"/*.elf 2>/dev/null || true

if [[ "${1:-}" == "--upload" ]]; then
  PORT="${2:-}"
  if [[ -z "$PORT" ]]; then
    echo "用法: build_firmware.sh --upload <COMx>" >&2
    exit 2
  fi
  # Leonardo 靠 1200bps 触摸复位进 bootloader，之后会换一个新端口，
  # 因此必须给足端口发现时间（bootloader 只等待约 8 秒）。
  echo "[build] 烧录到 $PORT ..."
  "$CLI" upload -p "$PORT" --fqbn "$FQBN" \
    --input-dir "$BUILD" \
    --discovery-timeout 20s \
    "$WORK"
  echo "[build] 烧录完成"
fi
