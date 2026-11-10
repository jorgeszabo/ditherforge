import copy
import unittest
from indx import color_tools, palette_mapping, gcode_tools


class ToolMappingTests(unittest.TestCase):
    def setUp(self):
        self.tools = [{"tool": i, "label": f"Test spool {i}", "role": "color", "type": "PLA", "color": f"#{i:02X}2244", "td": None} for i in range(1, 9)]

    def test_eight_tools_survive_reordered_palette(self):
        palette = [{"color": t["color"]} for t in reversed(self.tools)]
        mapping = palette_mapping(palette, color_tools({"tools": self.tools}))
        self.assertEqual(list(mapping["map"].values()), list(range(8, 0, -1)))

    def test_sparse_tool_numbers_are_not_compacted(self):
        mapping = palette_mapping([{"color": self.tools[7]["color"]}, {"color": self.tools[1]["color"]}], self.tools)
        self.assertEqual(mapping["map"], {"1": 8, "2": 2})

    def test_reserved_support_tool_cannot_enter_colour_mix(self):
        tools = copy.deepcopy(self.tools)
        tools[7].update(role="support", type="PETG")
        self.assertEqual(len(color_tools({"tools": tools})), 7)
        with self.assertRaisesRegex(ValueError, "reserved"):
            color_tools({"tools": tools}, [8])

    def test_unexpected_export_colour_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected"):
            palette_mapping([{"color": "#ABCDEF"}], self.tools)

    def test_duplicate_tools_and_ambiguous_swatches_are_rejected(self):
        tools = copy.deepcopy(self.tools)
        tools[7]["tool"] = 1
        with self.assertRaises(ValueError):
            color_tools({"tools": tools})
        tools = copy.deepcopy(self.tools)
        tools[7]["color"] = tools[0]["color"]
        with self.assertRaisesRegex(ValueError, "Duplicate swatches"):
            color_tools({"tools": tools})

    def test_indented_indx_tool_commands_and_actual_filament_use(self):
        text = "T0 S1 L2 D0\n  T7 S1 L0 D0\nM204 T7000\n; T4 example\n; filament used [mm] = 2, 0, 0, 0, 0, 0, 0, 3\n"
        self.assertEqual(gcode_tools(text), ([1, 8], [1, 8]))


if __name__ == "__main__":
    unittest.main()
