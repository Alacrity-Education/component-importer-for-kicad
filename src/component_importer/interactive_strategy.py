# Interactive symbol-reconstruction formatting strategy.
#
# This plugs into the SymbolFormattingStrategy hierarchy. For each named symbol
# in the merged library file it:
#   1. extracts the pins and their source side (from pin angles),
#   2. opens the Qt-free TUI editor so the user can re-arrange pins across the
#      four sides (and add blank spacers),
#   3. on accept, regenerates the symbol's body rectangle and pins on a proper
#      2.54 mm grid with an auto-sized body, preserving the symbol's properties,
#   4. on cancel, leaves the symbol exactly as merged.
#
# The module is Qt-free. All terminal interaction is delegated to key_source /
# interactive_editor, so the strategy itself stays testable with a
# ScriptedKeySource.

import math
import re
from pathlib import Path

from component_importer.formatting_strategy import SymbolFormattingStrategy
from component_importer.interactive_editor import (
    EditorState,
    Slot,
    TerminalRenderer,
    run_editor,
)
from component_importer.key_source import KeySource, TerminalKeySource
from component_importer.symbol_footprint_linker import (
    find_list_blocks_at_depth,
    find_symbol_blocks,
)
from component_importer.symbol_style import (
    SymbolStyle,
    build_rectangle_block,
    ceil_to_grid,
    clean_pin_direction_value,
    find_list_blocks,
    format_kicad_number,
    get_block_indent,
    parse_pin_at_block,
    parse_pin_length_block,
    parse_pin_name,
)


# Millimetres per character for KiCad's default font, using uppercase 'E' width
# as the reference glyph. Used for both horizontal name widths and, because top /
# bottom names are drawn vertically, for their stacked height as well.
CHAR_WIDTH_MM = 1.27

# 2.54 mm placement grid and default pin length
GRID_MM = 2.54
DEFAULT_PIN_LENGTH_MM = 2.54

# Minimum clear gap (mm) between the two opposing name zones inside the body
NAME_ZONE_GAP_MM = 2.54

# Minimum clearance (mm) between a corner and the nearest pin on a side
PIN_EDGE_MARGIN_MM = 2.54

# Never let the body get smaller than this half-extent (mm)
MIN_BODY_HALF_MM = 5.08

# angle -> side. 0 extends right (pin left of body), 180 left, 90 up, 270 down.
ANGLE_TO_SIDE = {0: "left", 180: "right", 90: "bottom", 270: "top"}
SIDE_TO_ANGLE = {"left": 0, "right": 180, "bottom": 90, "top": 270}


# Parse the electrical type from a pin block header: "(pin <etype> <shape> ..."
def parse_pin_electrical_type(pin_text: str) -> str:
    match = re.match(r"\(pin\s+([A-Za-z_]+)\s+([A-Za-z_]+)", pin_text)

    if not match:
        return "passive"

    return match.group(1)


# Parse the number token from a pin block
def parse_pin_number(pin_text: str) -> str:
    number_blocks = find_list_blocks_at_depth(
        text=pin_text,
        list_name="number",
        target_depth=1,
    )

    if not number_blocks:
        return ""

    match = re.match(r'\(number\s+"((?:[^"\\]|\\.)*)"', number_blocks[0]["text"])

    if not match:
        return ""

    return match.group(1)


# Normalise a pin angle to one of 0/90/180/270
def normalize_angle(angle: float) -> int:
    return int(round(angle)) % 360


# Extract one pin's geometry and identity from its block text
def parse_pin(pin_text: str) -> dict | None:
    at_blocks = find_list_blocks_at_depth(pin_text, "at", 1)
    length_blocks = find_list_blocks_at_depth(pin_text, "length", 1)

    if len(at_blocks) != 1 or len(length_blocks) != 1:
        return None

    parsed_at = parse_pin_at_block(at_blocks[0]["text"])
    length = parse_pin_length_block(length_blocks[0]["text"])

    if parsed_at is None or length is None:
        return None

    x, y, angle = parsed_at
    side = ANGLE_TO_SIDE.get(normalize_angle(angle))

    if side is None:
        return None

    return {
        "x": x,
        "y": y,
        "angle": normalize_angle(angle),
        "length": length,
        "side": side,
        "name": parse_pin_name(pin_text),
        "number": parse_pin_number(pin_text),
        "etype": parse_pin_electrical_type(pin_text),
        "source_text": pin_text,
    }


# Sort key so each side reads in its natural order:
#   left/right : top -> bottom  (descending y)
#   top/bottom : left -> right  (ascending x)
def _side_sort_key(side: str, pin: dict):
    if side in ("left", "right"):
        return -pin["y"]

    return pin["x"]


# Build an EditorState mirroring the source layout of one symbol block
def build_state_from_symbol(symbol_block_text: str) -> EditorState:
    pin_blocks = find_list_blocks(text=symbol_block_text, list_name="pin")
    parsed = []

    for block in pin_blocks:
        pin = parse_pin(block["text"])

        if pin is not None:
            parsed.append(pin)

    state = EditorState()

    for side in ("left", "right", "top", "bottom"):
        side_pins = [pin for pin in parsed if pin["side"] == side]
        side_pins.sort(key=lambda pin: _side_sort_key(side, pin))

        state.sides[side] = [
            Slot(
                is_blank=False,
                number=pin["number"],
                name=pin["name"],
                etype=pin["etype"],
                length=pin["length"],
                source_text=pin["source_text"],
            )
            for pin in side_pins
        ]

    # Start the cursor on the first non-empty side
    for side in ("left", "right", "top", "bottom"):
        if state.sides[side]:
            state.cursor_side = side
            state.cursor_index = 0
            break

    return state


# ---------------------------------------------------------------------------
# Geometry for regeneration
# ---------------------------------------------------------------------------


# Grid-snapped, centred positions for a run of slots (ascending order)
def _centered_positions(count: int, pitch: float) -> list[float]:
    if count <= 0:
        return []

    total = (count - 1) * pitch
    start = round((-total / 2) / pitch) * pitch

    return [start + index * pitch for index in range(count)]


# The uniform source pin length if every real pin shares one, else the default
def _resolve_pin_length(state: EditorState) -> float:
    lengths = {
        round(slot.length, 4)
        for side in state.sides.values()
        for slot in side
        if not slot.is_blank
    }

    if len(lengths) == 1:
        return lengths.pop()

    return DEFAULT_PIN_LENGTH_MM


# Longest real-pin name length (in characters) on a side
def _max_real_name_chars(slots: list) -> int:
    return max((len(slot.name) for slot in slots if not slot.is_blank), default=0)


# Compute body edges and per-slot pin coordinates for the final layout.
#
# Body sizing rule (documented):
#   * Width must fit the longest left name + gap + longest right name (each char
#     ~= CHAR_WIDTH_MM), and must also span the top/bottom pin columns with a
#     corner margin.
#   * Height must fit the left/right pin rows with a corner margin, and must also
#     fit the longest top name + gap + longest bottom name stacked vertically
#     (their names are drawn vertically, so they consume body height).
#   * Both half-extents are rounded outward to the grid, giving edges on-grid.
def compute_geometry(state: EditorState, pin_length: float) -> dict:
    left, right = state.sides["left"], state.sides["right"]
    top, bottom = state.sides["top"], state.sides["bottom"]

    # Vertical positions (top -> bottom) for the left/right columns
    left_ys = list(reversed(_centered_positions(len(left), GRID_MM)))
    right_ys = list(reversed(_centered_positions(len(right), GRID_MM)))

    # Horizontal positions (left -> right) for the top/bottom rows
    top_xs = _centered_positions(len(top), GRID_MM)
    bottom_xs = _centered_positions(len(bottom), GRID_MM)

    v_extent = max((abs(y) for y in left_ys + right_ys), default=0.0)
    h_extent = max((abs(x) for x in top_xs + bottom_xs), default=0.0)

    name_width = (
        _max_real_name_chars(left) + _max_real_name_chars(right)
    ) * CHAR_WIDTH_MM + NAME_ZONE_GAP_MM
    name_height = (
        _max_real_name_chars(top) + _max_real_name_chars(bottom)
    ) * CHAR_WIDTH_MM + NAME_ZONE_GAP_MM

    half_w = ceil_to_grid(
        max(h_extent + PIN_EDGE_MARGIN_MM, name_width / 2, MIN_BODY_HALF_MM),
        GRID_MM,
    )
    half_h = ceil_to_grid(
        max(v_extent + PIN_EDGE_MARGIN_MM, name_height / 2, MIN_BODY_HALF_MM),
        GRID_MM,
    )

    min_x, max_x = -half_w, half_w
    min_y, max_y = -half_h, half_h

    pins = []

    # Left pins: angle 0, connection point sits to the left of the body
    for slot, y in zip(left, left_ys):
        if slot.is_blank:
            continue
        pins.append((slot, min_x - pin_length, y, 0))

    # Right pins: angle 180, connection point to the right of the body
    for slot, y in zip(right, right_ys):
        if slot.is_blank:
            continue
        pins.append((slot, max_x + pin_length, y, 180))

    # Top pins: angle 270, connection point above the body
    for slot, x in zip(top, top_xs):
        if slot.is_blank:
            continue
        pins.append((slot, x, max_y + pin_length, 270))

    # Bottom pins: angle 90, connection point below the body
    for slot, x in zip(bottom, bottom_xs):
        if slot.is_blank:
            continue
        pins.append((slot, x, min_y - pin_length, 90))

    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "pin_length": pin_length,
        "pins": pins,
    }


# ---------------------------------------------------------------------------
# Symbol block regeneration
# ---------------------------------------------------------------------------


# Re-indent a captured s-expression block to a new base indentation
def _reindent_block(block_text: str, base_indent: str) -> str:
    lines = block_text.split("\n")

    if len(lines) == 1:
        return base_indent + block_text

    inner = [line for line in lines[1:] if line.strip()]
    min_indent = min((len(line) - len(line.lstrip()) for line in inner), default=0)

    out = [base_indent + lines[0]]

    for line in lines[1:]:
        if line.strip():
            out.append(base_indent + line[min_indent:])
        else:
            out.append("")

    return "\n".join(out)


# Rewrite a pin block's (at ...) and (length ...) for a new position and angle
def _rewrite_pin_block(pin_text: str, x: float, y: float, angle: int, length: float) -> str:
    at_blocks = find_list_blocks_at_depth(pin_text, "at", 1)
    length_blocks = find_list_blocks_at_depth(pin_text, "length", 1)

    replacements = []

    if len(at_blocks) == 1:
        new_at = (
            f"(at {format_kicad_number(x)} "
            f"{format_kicad_number(y)} "
            f"{format_kicad_number(angle)})"
        )
        replacements.append((at_blocks[0], new_at))

    if len(length_blocks) == 1:
        new_length = f"(length {format_kicad_number(length)})"
        replacements.append((length_blocks[0], new_length))

    for block, replacement in sorted(
        replacements, key=lambda item: item[0]["start"], reverse=True
    ):
        pin_text = (
            pin_text[: block["start"]] + replacement + pin_text[block["end"] + 1 :]
        )

    return pin_text


# Build a fresh pin block from scratch (used only if a source_text is missing)
def _build_pin_block(slot: Slot, x: float, y: float, angle: int, length: float) -> str:
    name = slot.name.replace("\\", "\\\\").replace('"', '\\"')

    return (
        f"(pin {slot.etype} line "
        f"(at {format_kicad_number(x)} {format_kicad_number(y)} {format_kicad_number(angle)}) "
        f"(length {format_kicad_number(length)})\n"
        f'  (name "{name}" (effects (font (size 1.27 1.27))))\n'
        f'  (number "{slot.number}" (effects (font (size 1.27 1.27)))))'
    )


# Regenerate one symbol block from the edited state, preserving header/properties
def regenerate_symbol_block(
    symbol_block_text: str,
    symbol_name: str,
    state: EditorState,
) -> str:
    pin_length = _resolve_pin_length(state)
    geometry = compute_geometry(state, pin_length)

    # Determine indentation from the original nested unit sub-symbols
    unit_blocks = find_list_blocks_at_depth(symbol_block_text, "symbol", 1)

    if unit_blocks:
        unit_indent = get_block_indent(symbol_block_text, unit_blocks[0]["start"])
    else:
        unit_indent = "    "

    content_indent = unit_indent + "  "

    # Strip the old unit sub-symbols, leaving the header and properties
    base = symbol_block_text

    for block in sorted(unit_blocks, key=lambda item: item["start"], reverse=True):
        base = base[: block["start"]] + base[block["end"] + 1 :]

    insert_at = base.rfind(")")
    head = base[:insert_at].rstrip()
    closing_indent = unit_indent[:-2] if len(unit_indent) >= 2 else ""

    # Graphics unit: a single auto-sized body rectangle, theme-adaptive colours
    rectangle = build_rectangle_block(
        style=SymbolStyle(),
        min_x=geometry["min_x"],
        max_x=geometry["max_x"],
        min_y=geometry["min_y"],
        max_y=geometry["max_y"],
        indent=content_indent,
    )
    unit0 = (
        f'{unit_indent}(symbol "{symbol_name}_0_1"\n'
        f"{rectangle}\n"
        f"{unit_indent})"
    )

    # Pins unit
    pin_lines = []

    for slot, x, y, angle in geometry["pins"]:
        if slot.source_text:
            pin_text = _rewrite_pin_block(slot.source_text, x, y, angle, pin_length)
        else:
            pin_text = _build_pin_block(slot, x, y, angle, pin_length)

        pin_lines.append(_reindent_block(pin_text, content_indent))

    unit1_body = "\n".join(pin_lines)
    unit1 = (
        f'{unit_indent}(symbol "{symbol_name}_1_1"\n'
        f"{unit1_body}\n"
        f"{unit_indent})"
    )

    return f"{head}\n{unit0}\n{unit1}\n{closing_indent})"


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class InteractiveReconstructionStrategy(SymbolFormattingStrategy):
    """Interactively reconstruct symbol pin layouts before writing them back."""

    def __init__(self, key_source: KeySource | None = None, renderer=None):
        # Real terminal input by default; tests inject a ScriptedKeySource
        self.key_source = key_source if key_source is not None else TerminalKeySource()
        # Optional renderer; when None a TerminalRenderer is used per symbol
        self.renderer = renderer

    # Run the editor for one symbol and return the accepted state, or None
    def _edit_symbol(self, symbol_block_text: str) -> EditorState | None:
        state = build_state_from_symbol(symbol_block_text)

        if self.renderer is not None:
            accepted = run_editor(state, self.key_source, on_render=self.renderer.render)
        else:
            with TerminalRenderer() as renderer:
                accepted = run_editor(state, self.key_source, on_render=renderer.render)

        return state if accepted else None

    def format_symbol_library_file(
        self,
        symbol_library_path: str | Path,
        symbol_names: list[str],
    ) -> dict | None:
        symbol_library_path = Path(symbol_library_path)
        content = symbol_library_path.read_text(encoding="utf-8", errors="ignore")

        requested = [name for name in dict.fromkeys(symbol_names) if name]
        requested_set = set(requested)

        reconstructed = []
        cancelled = []

        symbol_blocks = find_symbol_blocks(content)

        # Rewrite from the end so earlier block offsets stay valid
        for block in sorted(symbol_blocks, key=lambda item: item["start"], reverse=True):
            name = block.get("name", "")

            if requested_set and name not in requested_set:
                continue

            accepted_state = self._edit_symbol(block["text"])

            if accepted_state is None:
                cancelled.append(name)
                continue

            new_block = regenerate_symbol_block(block["text"], name, accepted_state)
            content = content[: block["start"]] + new_block + content[block["end"] + 1 :]
            reconstructed.append(name)

        updated = bool(reconstructed)

        if updated:
            symbol_library_path.write_text(content, encoding="utf-8")

        # A run where every symbol was cancelled makes no changes.
        if not updated:
            return None

        reconstructed.reverse()

        return {
            "symbol_library": str(symbol_library_path),
            "updated": updated,
            "reconstructed_symbol_names": reconstructed,
            "cancelled_symbol_names": cancelled,
            "styled_symbol_names": reconstructed,
        }


# Pin direction vector for an angle, matching the symbol_style convention
def pin_direction(angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    return (
        clean_pin_direction_value(math.cos(radians)),
        clean_pin_direction_value(math.sin(radians)),
    )
