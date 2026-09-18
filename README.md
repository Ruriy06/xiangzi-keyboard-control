# 祥子的宝贝 · 键鼠自动化控制台（无 AI 精简版）

Arduino Leonardo 固件 + Windows 桌面软件，通过 HID 接口向单片机发送键盘/鼠标指令，
实现可复用的按键操作、AB/自定义流程自动化。

> 本分支为「无 AI 精简版」，已移除素材库 / 自定义 AI 识别 / 钓鱼（OpenCV 模板识别与色块追踪）。
> 完整版（含 AI 识别）见 `main` 分支。

## 项目组成

```text
LYDR_auto6.ino              Arduino Leonardo 固件源码（需 MouseTo 库）
hid_link.h                  固件使用的 HID 链路层（从串口切换到 HID 时保持上层无感）
MouseTo-master.zip          固件依赖的 Arduino 鼠标绝对坐标库
tools/build_firmware.sh     固件编译脚本（CDC 开关、可选烧录）
tools/flash_via_bootloader.sh   手动进 bootloader 后烧录（关闭 CDC 后唯一可行方式）
tools/hid_probe.py          设备枚举与 HID 报文调试
tools/inspect_usb_descriptors.py    USB 描述符检查
tools/patch_usb_serial.py   修改 Arduino 核心的 USB 描述符（VID/PID/串号）
experiments/hid_feature_test/   HID 通道特性验证 sketch
desktop_app/                Windows 桌面软件（Python 3.14 + PySide6）
├─ main.py                  软件入口
├─ hid_control/             核心模块
│  ├─ ui/                   界面页面（控制台、操作编辑、AB流程、自定义流程、设置）
│  ├─ workflow.py           流程执行器
│  ├─ protocol.py           软件动作到固件命令的映射
│  ├─ hid_service.py        HID 设备枚举与通信（对上层保持与串口一致的接口）
│  ├─ privilege.py          管理员权限检测与提权重启
│  ├─ runtime_policy.py     CPU-only 软件渲染策略（须早于 PySide6 导入执行）
│  └─ storage.py            配置读写
├─ tests/                   单元测试
├─ requirements.txt         Python 依赖
├─ xiangzi.spec             PyInstaller 打包配置
├─ version_info.txt         exe 版本资源（版本号需与 APP_VERSION 保持一致）
├─ runtime_hook_cpu_only.py PyInstaller 运行时钩子（打包后同样锁定软件渲染）
└─ 启动软件.bat / .vbs      双击启动入口
```

> `desktop_app/data/config.json` 保存运行配置（操作、流程、设备与全局控制设置），随版本库共享。

## 硬件

- 开发板：Arduino Leonardo，目标核心 `arduino:avr:leonardo`
- 通信方式：HID，设备身份 VID `0x046A` / PID `0x0001`
- 最终形态固件为**单一 HID 接口、不含 CDC**，设备**不会出现 COM 口**；上位机按 VID/PID 枚举，
  并只保留厂商自定义集合（Col03），避免同 VID/PID 下的鼠标 / 键盘集合被误选
- 开发期可编译带虚拟串口的固件（PID `0x0002`），便于反复烧录

> ⚠️ Windows 内置驱动 `input.inf` 中硬编码了 `USB\VID_046A&PID_0001 -> HID_Inst`。
> 若设备带 CDC 却使用 PID `0x0001`，Windows 会把 HidUsb 直接挂到整个复合设备节点上，
> 设备将以 Code 10 无法启动，且完全不会生成 CDC 接口。因此带 CDC 的开发固件必须用 PID `0x0002`。

## 快速开始

### 1. 编译并烧录固件

1. 下载 arduino-cli（https://github.com/arduino/arduino-cli/releases ），
   放到**仓库目录的上一级**的 `.build-tools/arduino-cli.exe`（见下方「目录约定」）。
2. 用 Arduino IDE 导入 `MouseTo-master.zip`：`项目 → 加载库 → 添加 .ZIP 库`
   （会安装到 `文档/Arduino/libraries`，arduino-cli 默认从该目录查找库）。
3. 编译并烧录，具体命令见「固件构建与烧录」。

### 2. 运行桌面软件

1. 安装 Python 3.14 并创建虚拟环境：
   ```text
   cd desktop_app
   python -m venv .venv
   .venv/Scripts/pip install -r requirements.txt
   ```
2. 运行 `启动软件.bat`（或 `.venv/Scripts/pythonw.exe main.py`）。
3. 在控制台从设备下拉框选择 Leonardo 设备连接，随后即可读取设备配置。

## 固件构建与烧录

### 目录约定

构建脚本以脚本自身位置反推工作区根：`source/tools/*.sh` 的上一级为仓库目录，
再上一级为工作区根，`.build-tools/` 就放在工作区根下（**不在版本库内**）。
因此仓库目录不一定叫 `source`，但必须位于工作区根的直接下级：

```text
<工作区根>/
├─ source/                     本仓库
└─ .build-tools/               工具链与构建目录（需自行创建，不入库）
   ├─ arduino-cli.exe          需自行下载
   ├─ sketch/LYDR_auto6/       脚本自动把 source/*.ino 与 source/*.h 复制到这里
   └─ build/                   编译产物
```

### 编译

```text
source/tools/build_firmware.sh                  # 保留 CDC（PID 0x0002），便于反复烧录
CDC_MODE=off source/tools/build_firmware.sh     # 关闭 CDC（PID 0x0001），最终形态
source/tools/build_firmware.sh --upload COM3    # 编译后用串口顺带烧录（仅保留 CDC 时可用）
```

产物位于 `.build-tools/build/`：

- `LYDR_auto6.ino.hex` —— 应用区镜像，烧录用这个
- `LYDR_auto6.ino.with_bootloader.hex` —— 含 bootloader 的完整镜像

### 烧录

- **保留 CDC 时**（设备有 COM 口）：`source/tools/build_firmware.sh --upload COMx`
- **关闭 CDC 后**（设备无 COM 口，只能手动进 bootloader）：

  1. 先运行脚本，让它开始等待端口出现：
     ```text
     source/tools/flash_via_bootloader.sh
     ```
  2. 再**双击 Leonardo 板上的 RESET**（Caterina bootloader 只驻留约 8 秒）
  3. 脚本检测到 bootloader 端口后，直接用 avrdude 写入并校验

  几个关键点：

  - **顺序不能反**：先按 RESET 再运行命令会白白错过 8 秒窗口，脚本必须提前等着。
  - 脚本直接调用 Arduino IDE 自带的 avrdude
    （`~/AppData/Local/Arduino15/packages/arduino/tools/avrdude`），绕开 `arduino-cli upload`：
    后者会再对指定端口做一次 1200bps 触摸复位，而这里检测到的本来就是 bootloader 端口，
    多余的触摸会让 bootloader 提前退出。
  - 一次没成功可以再双击 RESET，脚本会继续等待下一个窗口。
  - 烧入不含 CDC 的固件后设备不再有 COM 口，之后每次烧录都要重复本流程。

## 测试

```text
cd desktop_app
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

## 注意事项

- 单片机绝对坐标依赖 `MouseTo` 的软件位置记录；手动移动实体鼠标、多显示器或
  分辨率切换可能导致偏差。
- 软件端流程等待不修改单片机基础按键/鼠标延迟。
- 启动时若当前不是管理员，程序会弹窗提示，默认按钮为「以管理员模式启动」；
  管理员模式可改善与管理员权限窗口交互时的兼容性（普通模式下 HID 设备与鼠标侧键同样可用）。
