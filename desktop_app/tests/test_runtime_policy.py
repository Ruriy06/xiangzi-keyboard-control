"""CPU-only 运行时策略与依赖审计测试。

这些测试守护一条硬约束：桌面软件必须在 CPU 上完成全部渲染，不加载 GPU 图形或
GPU 计算后端，也不引入视觉/AI 运行时依赖。
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "hid_control"


class SoftwareRenderEnvironmentTests(unittest.TestCase):
    """环境变量策略必须早于 Qt 生效，且能被外部环境覆盖后重新强制写回。"""

    def test_environment_is_forced_even_if_pre_set_to_hardware(self) -> None:
        # 模拟外部 shell 已经指向硬件后端：策略必须覆盖它，而不是继承。
        script = (
            "import os;"
            "os.environ['QT_OPENGL']='desktop';"
            "os.environ['QT_QUICK_BACKEND']='opengl';"
            "os.environ['QT_WIDGETS_RHI']='1';"
            "import hid_control;"
            "print(os.environ['QT_OPENGL']);"
            "print(os.environ['QT_QUICK_BACKEND']);"
            "print(os.environ['QSG_RHI_BACKEND']);"
            "print(os.environ['QT_WIDGETS_RHI']);"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        values = result.stdout.strip().splitlines()
        self.assertEqual(values, ["software", "software", "software", "0"])

    def test_environment_applied_before_pyside_import(self) -> None:
        # 关键顺序：导入 hid_control 之后、导入 PySide6 之前，环境变量就应已就位。
        script = (
            "import os;"
            "import hid_control;"
            "assert os.environ['QT_OPENGL']=='software', 'QT_OPENGL 未在导入 Qt 前设置';"
            "import PySide6;"
            "print('ok');"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_software_render_environment_is_idempotent(self) -> None:
        from hid_control import runtime_policy

        runtime_policy.apply_software_render_environment()
        first = dict(os.environ)
        runtime_policy.apply_software_render_environment()
        for name, value in runtime_policy.SOFTWARE_RENDER_ENVIRONMENT.items():
            self.assertEqual(os.environ[name], value)
            self.assertEqual(first[name], value)

    def test_cleared_environment_removes_forced_backend_override(self) -> None:
        from hid_control import runtime_policy

        os.environ["QSG_RHI_BACKEND_FORCE"] = "vulkan"
        try:
            runtime_policy.apply_software_render_environment()
            self.assertNotIn("QSG_RHI_BACKEND_FORCE", os.environ)
        finally:
            os.environ.pop("QSG_RHI_BACKEND_FORCE", None)

    def test_widgets_rhi_compositor_is_disabled(self) -> None:
        # Widget 的 RHI 后备存储合成器会创建 D3D11/D3D12/Vulkan 设备，
        # 必须显式关闭，窗口才会走纯 CPU 栅格路径。
        from hid_control import runtime_policy

        self.assertEqual(runtime_policy.SOFTWARE_RENDER_ENVIRONMENT["QT_WIDGETS_RHI"], "0")
        runtime_policy.apply_software_render_environment()
        self.assertEqual(os.environ["QT_WIDGETS_RHI"], "0")

    def test_packaging_hook_matches_runtime_policy(self) -> None:
        # 打包前置钩子必须在应用代码之前写入同一组策略，否则冻结版会漏掉设置。
        import ast

        from hid_control import runtime_policy

        hook_path = PROJECT_ROOT / "runtime_hook_cpu_only.py"
        tree = ast.parse(hook_path.read_text(encoding="utf-8"))
        hook_values: dict[str, str] | None = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_SOFTWARE_RENDER_ENVIRONMENT"
                for target in node.targets
            ):
                hook_values = ast.literal_eval(node.value)
        self.assertIsNotNone(hook_values, msg="打包钩子缺少 _SOFTWARE_RENDER_ENVIRONMENT")
        self.assertEqual(hook_values, runtime_policy.SOFTWARE_RENDER_ENVIRONMENT)


class QtAttributeTests(unittest.TestCase):
    """两个 Qt 属性必须存在，且在 QApplication 构造前被设置。"""

    def test_attribute_names_exist_in_qt(self) -> None:
        from hid_control.runtime_policy import qt_application_attributes

        from PySide6.QtCore import Qt

        for name in qt_application_attributes():
            self.assertTrue(
                hasattr(Qt.ApplicationAttribute, name),
                msg=f"Qt 缺少 ApplicationAttribute.{name}",
            )

    def test_attributes_are_set_before_qapplication_construction(self) -> None:
        # 用 QApplication 的构造做探针：记录构造瞬间两个属性是否已经为 True。
        script = (
            "from PySide6.QtCore import Qt;"
            "from PySide6.QtWidgets import QApplication;"
            "from hid_control.app import _enforce_software_rendering;"
            "_enforce_software_rendering();"
            "attrs=[Qt.ApplicationAttribute.AA_UseSoftwareOpenGL,"
            "Qt.ApplicationAttribute.AA_ForceRasterWidgets];"
            "print(all(QApplication.testAttribute(a) for a in attrs));"
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "True")


class DependencyAuditTests(unittest.TestCase):
    """源码与依赖清单不得引入 GPU 计算、GPU 图形或视觉/AI 运行时。"""

    FORBIDDEN_MODULES = (
        "torch",
        "tensorflow",
        "cv2",
        "numpy",
        "onnxruntime",
        "sklearn",
        "paddle",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtWebEngine",
        "PySide6.Qt3D",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtMultimedia",
    )

    def _python_sources(self) -> list[Path]:
        return sorted(PACKAGE_ROOT.rglob("*.py")) + [PROJECT_ROOT / "main.py"]

    def test_no_forbidden_runtime_imports(self) -> None:
        violations: list[str] = []
        for path in self._python_sources():
            if path.name == "runtime_policy.py":
                # 策略文件按名字提及 OpenGL 是预期行为（它负责关闭 GPU 路径）。
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("*"):
                    continue
                for module in self.FORBIDDEN_MODULES:
                    if stripped.startswith(f"import {module}") or stripped.startswith(f"from {module}"):
                        violations.append(f"{path.name}:{number}: {stripped}")
        self.assertEqual(violations, [], msg="发现被禁止的运行时导入：\n" + "\n".join(violations))

    def test_requirements_are_minimal_and_cpu_only(self) -> None:
        requirements_path = PROJECT_ROOT / "requirements.txt"
        entries = [
            line.strip()
            for line in requirements_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        names = {entry.split("==")[0].split(">=")[0].strip().lower() for entry in entries}
        self.assertEqual(names, {"pyside6", "pyserial", "hidapi"}, msg=f"依赖清单出现非预期项：{sorted(names)}")

    def test_no_opengl_widget_usage_in_ui(self) -> None:
        # Widget 界面不应创建任何 GPU 渲染表面。
        forbidden_widgets = ("QOpenGLWidget", "QGLWidget", "QQuickWidget", "QWebEngineView")
        violations: list[str] = []
        for path in (PACKAGE_ROOT / "ui").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for widget in forbidden_widgets:
                if widget in text:
                    violations.append(f"{path.name}: {widget}")
        self.assertEqual(violations, [], msg="UI 出现 GPU 渲染控件：\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
