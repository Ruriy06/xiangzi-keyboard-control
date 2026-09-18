#!/usr/bin/env bash
# 手动进入 bootloader 后直接烧录固件（关闭 CDC 后唯一可行的烧录方式）。
#
# 背景：
#   Leonardo 平时靠 CDC 虚拟串口的 1200bps 触摸自动复位进 bootloader。
#   一旦固件不含 CDC，设备就没有 COM 口，只能手动双击 RESET。
#   Caterina bootloader 只驻留约 8 秒，所以必须先启动本脚本等端口出现，
#   不能先按键再来运行命令。
#
# 为什么不用 `arduino-cli upload`：
#   它的上传流程会先对给定端口再做一次 1200bps 触摸复位，然后重新等待
#   "upload port"。但我们检测到的端口**本来就是 bootloader 端口**，那次
#   多余的触摸会让 bootloader 提前退出，8 秒窗口耗尽，最后以
#   "cannot open port COMx" 收场。因此这里绕开 arduino-cli，直接用
#   avrdude 连上 bootloader 端口并写入 + 校验。
#
# 用法：
#   source/tools/flash_via_bootloader.sh [hex路径] [等待秒数] [尝试次数]
#
# 默认：烧 .build-tools/build/LYDR_auto6.ino.hex，等 900s，最多 3 次尝试。
# 若一次没成功，可以再次双击 RESET，脚本会继续等在下一个窗口。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HEX="${1:-$ROOT/.build-tools/build/LYDR_auto6.ino.hex}"
WAIT="${2:-900}"
TRIES="${3:-3}"

# ⚠ 关键坑：avrdude 是原生 Windows 程序（ANSI/CP936），无法读取含中文的绝对路径
# ——Git Bash 传过去的 UTF-8 字节会被它按 GBK 解释成乱码，报 "cannot open input file"。
# 规避：改为先 cd 到 hex 所在目录，只传纯 ASCII 的相对文件名（cwd 由系统按宽字符维护，
# 不经 argv 编码转换，因此中文目录名无影响）。
HEX_DIR="$(cd "$(dirname "$HEX")" 2>/dev/null && pwd || true)"
HEX_BASE="$(basename "$HEX")"

MCU="atmega32u4"
AVRDUDE_ROOT="$HOME/AppData/Local/Arduino15/packages/arduino/tools/avrdude"
AVRDUDE_BIN="$(ls -1 "$AVRDUDE_ROOT"/*/bin/avrdude.exe 2>/dev/null | head -1 || true)"
AVRDUDE_CONF="$(ls -1 "$AVRDUDE_ROOT"/*/etc/avrdude.conf 2>/dev/null | head -1 || true)"

if [[ ! -f "$HEX" ]]; then
  echo "[flash] 找不到 hex：$HEX" >&2
  exit 2
fi
if [[ -z "$AVRDUDE_BIN" || -z "$AVRDUDE_CONF" ]]; then
  echo "[flash] 找不到 avrdude（$AVRDUDE_ROOT）" >&2
  exit 2
fi

# Caterina bootloader 的 USB 身份固定为 VID_2341&PID_0036，它自带一个
# usbser 端口，所以即使 app 侧 CDC 已关闭，这个端口依然会出现。
boot_port() {
  powershell -NoProfile -Command 'Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -like "*VID_2341&PID_0036*" } |
    ForEach-Object {
      $f = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName "DEVPKEY_Device_FriendlyName" -ErrorAction SilentlyContinue).Data
      if ($f -match "\((COM\d+)\)") { $Matches[1] }
    }' 2>/dev/null | tr -d '\r' | head -1
}

wait_port() {
  local deadline=$(( SECONDS + WAIT )) p
  while (( SECONDS < deadline )); do
    p="$(boot_port)"
    if [[ -n "$p" ]]; then printf '%s\n' "$p"; return 0; fi
    sleep 0.2
  done
  return 1
}

echo "[flash] 等待 bootloader 端口（请双击 Leonardo 的 RESET），最多 ${WAIT}s ..."
for (( attempt = 1; attempt <= TRIES; attempt++ )); do
  if ! PORT="$(wait_port)"; then
    echo "[flash] 超时：未检测到 bootloader 端口。" >&2
    exit 1
  fi
  echo "[flash] 第 $attempt 次尝试：检测到 bootloader 端口 $PORT，立即烧录"
  # 检测到就立刻握手：avrdude 开头的 sync 会拖住 Caterina，使它保持驻留。
  # 在 hex 所在目录里用相对文件名调用，绕开中文绝对路径的编码问题（见上方说明）。
  if ( cd "$HEX_DIR" && "$AVRDUDE_BIN" "-C$AVRDUDE_CONF" -v -p"$MCU" -cavr109 -P"$PORT" -b57600 -D \
       "-Uflash:w:$HEX_BASE:i" "-Uflash:v:$HEX_BASE:i" ); then
    echo "[flash] 烧录并校验成功"
    exit 0
  fi
  echo "[flash] 第 $attempt 次失败（多为 bootloader 已超时退出）。" >&2
  # 等这个端口从系统消失，避免下一轮拿到的是同一个已失效的端口号。
  for (( w = 0; w < 60; w++ )); do
    [[ -z "$(boot_port)" ]] && break
    sleep 0.2
  done
done

echo "[flash] 全部尝试失败。" >&2
exit 1
