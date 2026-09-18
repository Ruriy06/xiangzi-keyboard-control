#!/usr/bin/env bash
# 构建「HID Feature report 最小验证固件」（LYDR_auto6 去特征 · 阶段 C-1~C-3）。
#
# 形态：CDC 关闭 + 单一 HID 接口 + 厂商自定义 Feature(ID=3)/Input(ID=4) 报告。
#       PID 取 0x0001（CDC 关闭后是普通单一 HID 设备，见 build_firmware.sh 注释）。
#
# 产物：.build-tools/build_spike/hid_feature_test.ino.hex
# 烧录：source/tools/flash_via_bootloader.sh .build-tools/build_spike/hid_feature_test.ino.hex
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI="$ROOT/.build-tools/arduino-cli.exe"
SRC="$ROOT/source/experiments/hid_feature_test"
WORK="$ROOT/.build-tools/sketch/hid_feature_test"
BUILD="$ROOT/.build-tools/build_spike"
FQBN="arduino:avr:leonardo"

# 与 build_firmware.sh 保持一致的身份（VID=046A / Cherry / USB Keyboard）。
USB_VID="0x046A"
USB_PID="0x0001"            # CDC 关闭形态
USB_PRODUCT="USB Keyboard"
USB_MANUFACTURER="Cherry"

PROPS=(
  --build-property "build.vid=$USB_VID"
  --build-property "build.pid=$USB_PID"
  --build-property "build.usb_product=\"$USB_PRODUCT\""
  --build-property "build.usb_manufacturer=\"$USB_MANUFACTURER\""
  --build-property "compiler.cpp.extra_flags=-DCDC_DISABLED"
)

mkdir -p "$WORK"
shopt -s nullglob
sources=("$SRC"/*.ino "$SRC"/*.h)
shopt -u nullglob
cp "${sources[@]}" "$WORK/"

echo "[spike] 身份 ${USB_VID}:${USB_PID} 厂商=\"${USB_MANUFACTURER}\" 产品=\"${USB_PRODUCT}\"  CDC=off"
"$CLI" compile --fqbn "$FQBN" --build-path "$BUILD" "${PROPS[@]}" "$WORK"

echo "[spike] 产物："
ls -1 "$BUILD"/*.hex "$BUILD"/*.elf 2>/dev/null || true
