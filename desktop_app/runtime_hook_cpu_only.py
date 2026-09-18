"""打包运行时的 CPU-only 前置钩子。

PyInstaller 会在执行应用脚本之前运行本钩子，因此它比应用内的任何 import 都更早，
可以保证 Qt 平台插件与图形后端在加载时看到的就是软件渲染策略。
"""

import os

_SOFTWARE_RENDER_ENVIRONMENT = {
    "QT_OPENGL": "software",
    "QT_QUICK_BACKEND": "software",
    "QSG_RHI_BACKEND": "software",
    "QT_WIDGETS_RHI": "0",
    "QT_DISABLE_SHADER_DISK_CACHE": "1",
}

for _name, _value in _SOFTWARE_RENDER_ENVIRONMENT.items():
    os.environ[_name] = _value

os.environ.pop("QSG_RHI_BACKEND_FORCE", None)
