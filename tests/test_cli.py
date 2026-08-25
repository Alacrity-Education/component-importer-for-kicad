import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

from component_importer import cli


SYMBOL_LIBRARY = """(kicad_symbol_lib
  (version 20231120)
  (generator "test")
  (symbol "TEST_PART"
    (property "Reference" "U" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "TEST_PART" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "TEST_PART_0_1"
      (rectangle (start -2.54 1.27) (end 2.54 -1.27)
        (stroke (width 0) (type default)) (fill (type background))))
    (symbol "TEST_PART_1_1"
      (pin input line (at -5.08 0 0) (length 2.54)
        (name "IN" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
)"""

FOOTPRINT = """(footprint "TEST_FP"
  (version 20240108)
  (generator "test")
  (model "old.step"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0)))
)"""


@contextmanager
def chdir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CliTest(unittest.TestCase):
    def create_component_zip(self, zip_path: Path, symbol_name: str = "TEST_PART") -> None:
        symbol = SYMBOL_LIBRARY.replace("TEST_PART", symbol_name)
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(f"{symbol_name}.kicad_sym", symbol)
            archive.writestr("TEST_FP.kicad_mod", FOOTPRINT)
            archive.writestr("TEST_FP.step", "STEP MODEL")

    def create_empty_zip(self, zip_path: Path) -> None:
        with ZipFile(zip_path, "w") as archive:
            archive.writestr("readme.txt", "not a component")

    def make_project(self, root: Path) -> None:
        (root / "demo.kicad_pro").write_text("{}", encoding="utf-8")

    def test_find_config_walks_up_from_nested_subfolder(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            (root / cli.CONFIG_FILENAME).write_text(
                "[kicad-importer]\nlibrary = MyParts\n", encoding="utf-8"
            )
            nested = root / "a" / "b" / "c"
            nested.mkdir(parents=True)

            found = cli.find_config_file(nested)
            self.assertEqual(found, root / cli.CONFIG_FILENAME)

    def test_init_creates_config_next_to_kicad_pro(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)
            nested = root / "hardware"
            nested.mkdir()

            with chdir(nested):
                code = cli.main(["init", "--library", "MyParts"])

            self.assertEqual(code, 0)
            config_path = root / cli.CONFIG_FILENAME
            self.assertTrue(config_path.exists())
            self.assertEqual(cli.read_config(config_path)["library"], "MyParts")

    def test_init_merges_single_flags_on_rerun(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)

            with chdir(root):
                cli.main(["init", "--library", "MyParts"])
                downloads = root / "dl"
                downloads.mkdir()
                cli.main(["init", "--downloads", str(downloads)])

            config = cli.read_config(root / cli.CONFIG_FILENAME)
            self.assertEqual(config["library"], "MyParts")
            self.assertEqual(config["downloads"], str(downloads.resolve()))

    def test_init_errors_without_kicad_pro_or_config(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()

            with chdir(root):
                code = cli.main(["init", "--library", "MyParts"])

            self.assertEqual(code, 1)

    def test_init_first_time_requires_library(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)

            with chdir(root):
                code = cli.main(["init"])

            self.assertEqual(code, 1)
            self.assertFalse((root / cli.CONFIG_FILENAME).exists())

    def test_import_single_zip_end_to_end(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)
            self.create_component_zip(root / "part.zip")

            with chdir(root):
                cli.main(["init", "--library", "MyParts"])
                code = cli.main(["import", "part.zip"])

            self.assertEqual(code, 0)
            self.assertTrue((root / "libraries" / "MyParts.kicad_sym").exists())
            self.assertTrue((root / "libraries" / "MyParts.pretty").is_dir())
            self.assertTrue((root / "sym-lib-table").exists())
            self.assertTrue((root / "fp-lib-table").exists())

    def test_import_missing_filename_errors(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)

            with chdir(root):
                cli.main(["init", "--library", "MyParts"])
                code = cli.main(["import", "does_not_exist.zip"])

            self.assertEqual(code, 1)

    def test_import_without_config_errors(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()

            with chdir(root):
                code = cli.main(["import", "part.zip"])

            self.assertEqual(code, 1)

    def test_eligibility_partitioning(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            good = root / "good.zip"
            bad = root / "bad.zip"
            self.create_component_zip(good)
            self.create_empty_zip(bad)

            self.assertTrue(cli.is_eligible_zip(good))
            self.assertFalse(cli.is_eligible_zip(bad))

    def test_import_all_delete_on_full_success(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)
            self.create_component_zip(root / "one.zip", "PART_ONE")
            self.create_component_zip(root / "two.zip", "PART_TWO")
            self.create_empty_zip(root / "ignore.zip")

            with chdir(root):
                cli.main(["init", "--library", "MyParts"])
                code = cli.main(["import", "--all", "--delete"])

            self.assertEqual(code, 0)
            self.assertFalse((root / "one.zip").exists())
            self.assertFalse((root / "two.zip").exists())
            # Ineligible zip is never a candidate, so it is left untouched
            self.assertTrue((root / "ignore.zip").exists())

    def test_import_all_delete_skipped_when_one_fails(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir).resolve()
            self.make_project(root)
            self.create_component_zip(root / "good.zip", "GOOD_PART")

            # Eligible by extension, but an unsafe member path makes the
            # importer reject the archive during scanning
            broken = root / "broken.zip"
            with ZipFile(broken, "w") as archive:
                archive.writestr("../BROKEN.kicad_sym", SYMBOL_LIBRARY)

            with chdir(root):
                cli.main(["init", "--library", "MyParts"])
                code = cli.main(["import", "--all", "--delete"])

            self.assertEqual(code, 1)
            # Any failure skips the entire delete phase
            self.assertTrue((root / "good.zip").exists())
            self.assertTrue((root / "broken.zip").exists())

    def test_import_all_conflicts_with_file_argument(self):
        with self.assertRaises(SystemExit):
            cli.main(["import", "--all", "part.zip"])


if __name__ == "__main__":
    unittest.main()
