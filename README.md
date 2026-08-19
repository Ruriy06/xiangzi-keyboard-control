# 祥子的宝贝 · 键鼠自动化控制台

Arduino Leonardo 固件 + Windows 桌面软件，通过串口向单片机发送 HID 键盘/鼠标指令，
实现可复用的按键操作、AB/自定义流程、OpenCV 模板识别与色块追踪钓鱼。

## 项目组成

```text
LYDR_auto6.ino              Arduino Leonardo 固件源码（需 MouseTo 库）
MouseTo-master.zip          固件依赖的 Arduino 鼠标绝对坐标库
desktop_app/                Windows 桌面软件（Python 3.14 + PySide6）
├─ main.py                  软件入口
├─ hid_control/             核心模块
│  ├─ ui/                   界面页面（控制台、操作编辑、流程、AI识别、设置）
│  ├─ workflow.py           流程执行器
│  ├─ vision.py             模板识别服务
│  ├─ fishing.py            色块追踪服务
│  ├─ protocol.py           软件动作到固件命令的映射
│  ├─ serial_service.py     COM 串口通信
│  └─ storage.py            配置读写
├─ tests/                   单元测试
├─ requirements.txt         Python 依赖
└─ 启动软件.bat / .vbs      双击启动入口
```

> `desktop_app/data/` 保存运行配置、素材与识别模板，属用户数据，不进入版本库。

## 硬件

- 开发板：Arduino Leonardo
- 串口：默认 COM5，波特率 115200
- 目标核心：`arduino:avr:leonardo`

## 快速开始

1. Arduino IDE 导入 `MouseTo-master.zip` 库，打开 `LYDR_auto6.ino` 编译上传。
2. 安装 Python 3.14 并创建虚拟环境：
   ```text
   cd desktop_app
   python -m venv .venv
   .venv/Scripts/pip install -r requirements.txt
   ```
3. 运行 `启动软件.bat`（或 `.venv/Scripts/pythonw.exe main.py`）。
4. 在控制台选择 COM 端口连接 Leonardo，读取设备配置后即可使用。

## 测试

```text
cd desktop_app
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

## 注意事项

- 单片机绝对坐标依赖 `MouseTo` 的软件位置记录；手动移动实体鼠标、多显示器或
  分辨率切换可能导致偏差。
- 软件端流程等待不修改单片机基础按键/鼠标延迟。
- 识别区域越小，截图、颜色转换与模板匹配的开销越低。
