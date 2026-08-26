import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from component_importer.gui_config_manager import (
    GuiConfig,
    build_symbol_style_from_config,
    config_from_dict,
    load_gui_config,
    save_gui_config,
)
from component_importer.symbol_style import (
    SymbolStyle,
    apply_symbol_style_to_library_content,
    normalize_symbol_style,
    symbol_style_to_dict,
)


# A minimal library whose body carries hardcoded colors the styler would rewrite
STYLED_LIBRARY = """(kicad_symbol_lib
  (version 20231120)
  (generator "test")
  (symbol "PART"
    (property "Reference" "U" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (symbol "PART_0_1"
      (rectangle (start -2.54 1.27) (end 2.54 -1.27)
        (stroke (width 0.1) (type default) (color 10 20 30 1))
        (fill (type color) (color 200 200 200 1))))
    (symbol "PART_1_1"
      (pin input line (at -5.08 0 0) (length 2.54)
        (name "IN" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
)"""


class SymbolStyleRoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_use_default_colors(self):
        style = SymbolStyle(use_default_colors=True)
        data = symbol_style_to_dict(style)

        self.assertIn("use_default_colors", data)
        self.assertTrue(data["use_default_colors"])

        restored = normalize_symbol_style(data)
        self.assertTrue(restored.use_default_colors)

    def test_default_flag_is_false(self):
        self.assertFalse(SymbolStyle().use_default_colors)
        self.assertFalse(symbol_style_to_dict(SymbolStyle())["use_default_colors"])

    def test_normalize_defaults_flag_when_absent(self):
        restored = normalize_symbol_style({"line_width_mm": 0.3})
        self.assertFalse(restored.use_default_colors)


class StylerOutputTest(unittest.TestCase):
    def test_default_colors_emit_theme_adaptive_nodes(self):
        style = SymbolStyle(
            line_width_mm=0.3,
            fill_mode="color",
            font_size_mm=1.5,
            use_default_colors=True,
        )
        content, names = apply_symbol_style_to_library_content(STYLED_LIBRARY, style)

        self.assertIn("PART", names)
        # Stroke color is unset (alpha 0), no hardcoded RGB stroke
        self.assertIn("(color 0 0 0 0)", content)
        # Fill follows the theme background
        self.assertIn("(fill (type background))", content)
        self.assertNotIn("(fill (type color)", content)
        # No hardcoded default colors leaked in
        self.assertNotIn("(color 132 0 0 1)", content)
        self.assertNotIn("(color 255 255 194 1)", content)
        self.assertNotIn("(color 200 200 200 1)", content)
        # Line width still applied
        self.assertIn("(width 0.3)", content)
        # Text size still applied
        self.assertIn("(size 1.5 1.5)", content)

    def test_hardcoded_colors_preserved_when_flag_false(self):
        style = SymbolStyle(
            line_width_mm=0.3,
            fill_mode="kicad_default",
            font_size_mm=1.5,
            use_default_colors=False,
        )
        content, names = apply_symbol_style_to_library_content(STYLED_LIBRARY, style)

        self.assertIn("PART", names)
        # Old behavior: hardcoded default line and fill colors
        self.assertIn("(color 132 0 0 1)", content)
        self.assertIn("(fill (type color) (color 255 255 194 1))", content)
        self.assertNotIn("(color 0 0 0 0)", content)
        self.assertNotIn("(fill (type background))", content)


class GuiConfigDefaultColorsTest(unittest.TestCase):
    def test_field_defaults_false(self):
        self.assertFalse(GuiConfig().symbol_use_default_colors)

    def test_flag_survives_kicad_default_preset_override(self):
        config = GuiConfig(
            symbol_style_preset="kicad_default",
            symbol_use_default_colors=True,
        )
        self.assertTrue(config.symbol_use_default_colors)

    def test_build_symbol_style_carries_flag(self):
        config = GuiConfig(
            symbol_style_enabled=True,
            symbol_use_default_colors=True,
        )
        style = build_symbol_style_from_config(config)
        self.assertIsNotNone(style)
        self.assertTrue(style.use_default_colors)

    def test_migration_from_old_config_without_field(self):
        # Old configs never wrote this key; it must default to False
        old_data = {
            "library_name": "MyParts",
            "symbol_style_enabled": True,
            "symbol_style_preset": "custom",
            "symbol_line_color": "#123456",
        }
        config = config_from_dict(old_data)
        self.assertFalse(config.symbol_use_default_colors)

    def test_persistence_round_trip(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            path = Path(temp_dir) / "config.json"
            config = GuiConfig(
                library_name="MyParts",
                symbol_use_default_colors=True,
            )
            save_gui_config(config, path)
            loaded = load_gui_config(path)
            self.assertTrue(loaded.symbol_use_default_colors)
            self.assertIn("symbol_use_default_colors", asdict(loaded))


@unittest.skipUnless(
    os.environ.get("QT_QPA_PLATFORM") == "offscreen",
    "GUI smoke test requires QT_QPA_PLATFORM=offscreen",
)
class SymbolStyleTabSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_checkbox_disables_color_controls(self):
        from component_importer.gui_symbol_style_tab import SymbolStyleTab

        tab = SymbolStyleTab(GuiConfig(symbol_use_default_colors=False))
        self.assertFalse(tab.use_default_colors_checkbox.isChecked())
        self.assertTrue(tab.symbol_line_color_button.isEnabled())
        self.assertTrue(tab.symbol_fill_color_button.isEnabled())

        tab.use_default_colors_checkbox.setChecked(True)
        self.assertFalse(tab.symbol_line_color_button.isEnabled())
        self.assertFalse(tab.symbol_fill_color_button.isEnabled())
        self.assertFalse(tab.symbol_line_color_label.isEnabled())
        self.assertFalse(tab.symbol_fill_color_label.isEnabled())

        # The flag flows into the saved config
        config = tab.build_config_from_fields()
        self.assertTrue(config.symbol_use_default_colors)


if __name__ == "__main__":
    unittest.main()
