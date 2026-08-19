# 项目工作日志与重建交接

更新日期：2026-07-22

## 项目目标

本项目由两部分组成：

1. **Arduino Leonardo 固件**：通过串口接收命令，并由 Leonardo 以 USB HID 键盘/鼠标方式输出。
2. **Windows 桌面软件**：使用 Python 3.14 + PySide6 配置操作、流程、串口和全局控制，再把命令发送给单片机。

## 关键文件

```text
LYDR_auto6.ino
    当前已烧录的 Leonardo 固件源码。

backup/LYDR_auto6.before-config-display.ino
    最初固件备份。

backup/LYDR_auto6.before-keyboard-layout.ino
    扩展 75% 键盘命名键前的固件备份。

CHANGELOG.md
    每一轮固件和桌面软件改动记录。

desktop_app/
    Windows 桌面软件工程。

desktop_app/启动软件.bat
    桌面软件启动入口。

desktop_app/data/config.json
    当前本地操作、流程、设备和全局控制配置。

desktop_app/data/config.before-simple-workflow.json
    旧节点式流程配置备份。

desktop_app/data/config.before-duration-custom-flow.json
    旧秒/分钟流程字段配置备份。
```

## 已确认的硬件与烧录状态

```text
开发板：Arduino Leonardo
串口：COM5
目标核心：arduino:avr:leonardo
串口波特率：115200
```

当前根目录的 `LYDR_auto6.ino` 已成功编译并上传到 Leonardo。

## 固件能力摘要

### 键盘和鼠标

- 普通按键、组合键、按住键、松开键；
- 常用 75% 键盘按键、功能键、导航键和符号键；
- 左/右/中键、后退/前进侧键；
- 相对移动、像素坐标移动、比例坐标移动、滚轮；
- `{STOP}` 和无指令超时释放。

### 配置和显示

```text
{CFG_GET}
{CFG_KEY_PRESS_毫秒}
{CFG_KEY_RELEASE_毫秒}
{CFG_COMBO_HOLD_毫秒}
{CFG_MOUSE_PRESS_毫秒}
{CFG_MOUSE_CLICK_毫秒}
{CFG_MOUSE_MOVE_毫秒}
{CFG_MAX_JUMP_像素}
{CFG_RESET}

{SCR_宽_高}
{SCR_GET}
{MOVE_NORM_X_Y}
{MC_NORM_X_Y}
```

注意：`KEY_DOWN_*` 和 `KEY_UP_*` 是立即按下/松开；若需要按住一段时间，应由软件在两者之间插入等待步骤。

## 桌面软件当前架构

```text
desktop_app/
├─ main.py
├─ 启动软件.bat
├─ requirements.txt
├─ .venv/                         Python 3.14 虚拟环境
├─ hid_control/
│  ├─ models.py                   数据模型
│  ├─ protocol.py                 软件动作到固件命令的映射
│  ├─ serial_service.py           COM 串口通信
│  ├─ workflow.py                 A/B 和自定义流程执行器
│  ├─ hotkeys.py                  Windows 全局热键及备用组合
│  ├─ mouse_hook.py               鼠标侧键监听钩子
│  ├─ storage.py                  JSON 配置迁移与保存
│  └─ ui/
│     ├─ main_window.py
│     ├─ action_editor.py         操作编辑
│     ├─ step_input.py            按类型显示的键鼠步骤输入控件
│     ├─ ab_flow_page.py          AB流程
│     ├─ custom_flow_page.py      自定义流程
│     ├─ settings.py
│     └─ duration_input.py        毫秒/秒/分钟控件
└─ tests/
```

## 当前桌面软件功能

### 操作编辑

- 可复用操作；
- 操作步骤可拖动排序；
- 单击、组合、按住、松开键；
- 鼠标按钮使用下拉选择，不需填写 `LEFT`、`RIGHT` 协议字符串；
- 鼠标移动、滚轮、等待和高级命令；
- 每一步支持“步骤后等待”，单位为毫秒、秒或分钟。

### AB流程

- A：主要循环操作；
- B：到指定时间插入执行一次的操作；
- B 执行期间，A 在当前一轮结束后暂停；B 完成后 A 恢复；
- 可配置运行总时长、休息时长、周期次数；
- 页面会生成当前流程文字说明。

### 自定义流程

可拖动排序的线性流程，支持：

```text
执行已保存操作
直接输入键鼠步骤
等待
```

可配置每个操作重复次数、流程运行总时长、休息时长和周期次数。

### 全局控制

- 首选启动/恢复：`Ctrl+Alt+F8`；
- 首选停止：`Ctrl+Alt+F9`；
- 若被占用，会自动尝试备用组合；
- 鼠标后退侧键：启动/恢复；
- 鼠标前进侧键：停止；
- 设置页显示实际启用状态。

已在当前 Windows 环境实际验证：默认全局快捷键注册成功，鼠标侧键监听钩子已成功启动。

## 运行和测试

启动软件：

```text
desktop_app/启动软件.bat
```

在 `desktop_app` 下运行测试：

```text
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

当前自动测试数量：18 项，最近一次全部通过。

## 重建时的顺序

1. 安装 Arduino IDE，并安装/导入 `MouseTo` 库；
2. 打开 `LYDR_auto6.ino`，选择 Arduino Leonardo 和正确 COM 端口；
3. 编译、上传固件；
4. 安装 Python 3.14；
5. 在 `desktop_app` 创建虚拟环境并安装 `requirements.txt`；
6. 启动 `启动软件.bat`；
7. 选择 Leonardo 对应 COM 端口，连接后读取设备配置；
8. 在操作编辑、AB流程或自定义流程中重新配置或恢复 `data/config.json`。

## 已知工程注意事项

- 单片机绝对坐标依赖 `MouseTo` 的软件位置记录；手动移动实体鼠标、多显示器、分辨率切换可能造成偏差。
- 软件端流程等待不修改单片机基础按键/鼠标延迟。
- 目前未实现单片机 EEPROM 断电保存配置。
- 当前未改动固件中的可中断 WAIT、PING/ACK 协议和物理急停；见 `CHANGELOG.md`。
