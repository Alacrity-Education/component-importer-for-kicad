import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from component_importer import app_paths


class GuiConfigFilePathTests(unittest.TestCase):
    def test_frozen_app_uses_user_data_dir(self):
        with mock.patch.object(app_paths, "is_frozen_app", return_value=True):
            path = app_paths.gui_config_file_path()

        self.assertEqual(path, app_paths.user_data_dir() / "gui_config.json")

    def test_source_checkout_uses_repository_root(self):
        with (
            mock.patch.object(app_paths, "is_frozen_app", return_value=False),
            mock.patch.object(app_paths, "is_source_checkout", return_value=True),
        ):
            path = app_paths.gui_config_file_path()

        self.assertEqual(path, app_paths.source_root_dir() / "gui_config.json")

    def test_package_install_uses_user_data_dir(self):
        with (
            mock.patch.object(app_paths, "is_frozen_app", return_value=False),
            mock.patch.object(app_paths, "is_source_checkout", return_value=False),
        ):
            path = app_paths.gui_config_file_path()

        self.assertEqual(path, app_paths.user_data_dir() / "gui_config.json")

    def test_site_packages_layout_is_not_a_source_checkout(self):
        # Simulate an installed layout: <root>/lib/component_importer with no
        # pyproject.toml two levels above the package, like site-packages.
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            package_dir = fake_root / "lib" / "component_importer"
            source_dir = Path(app_paths.__file__).resolve().parent
            shutil.copytree(source_dir, package_dir)

            script = (
                "from component_importer import app_paths\n"
                "print(app_paths.is_source_checkout())\n"
                "print(app_paths.gui_config_file_path())\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=fake_root,
                env={"PYTHONPATH": str(fake_root / "lib"), "HOME": tmp},
                capture_output=True,
                text=True,
                check=True,
            )

            checkout_flag, config_path = result.stdout.strip().splitlines()
            self.assertEqual(checkout_flag, "False")
            self.assertTrue(
                config_path.startswith(tmp),
                f"config path escapes the fake home: {config_path}",
            )
            self.assertNotIn("/lib/", config_path)


if __name__ == "__main__":
    unittest.main()
