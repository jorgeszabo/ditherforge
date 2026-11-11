import copy
import unittest
from indx import color_tools, palette_mapping, gcode_tools, support_interface, check_support_gcode


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

    def test_specific_material_preset_survives_palette_reordering(self):
        tools = copy.deepcopy(self.tools)
        tools[0]["materialPreset"] = "Prusament PLA ColorMix Cyan"
        mapping = palette_mapping([{"color": tools[1]["color"]}, {"color": tools[0]["color"]}], tools)
        self.assertEqual(mapping["materials"]["1"], "Prusament PLA ColorMix Cyan")

    def test_petg_interface_requires_explicit_reserved_tool_and_matching_profile(self):
        doc = {"_indx": {"supportInterfaceTool": 8, "tools": [{"tool": 8, "role": "support", "type": "PETG", "materialPreset": "Test PETG"}]}}
        profiles = {"materials": {"Test PETG": {"type": "PETG"}}}
        self.assertEqual(support_interface(doc, profiles)["tool"], 8)
        doc["_indx"]["tools"][0]["role"] = "color"
        with self.assertRaisesRegex(ValueError, "reserved"):
            support_interface(doc, profiles)
        doc["_indx"]["tools"][0]["role"] = "support"
        with self.assertRaisesRegex(ValueError, "installed"):
            support_interface(doc, {"materials": {}})

    def test_support_paths_require_pla_foundation_and_keep_petg_out_of_model(self):
        text = "T3\n;Z:0.2\n;TYPE:Support material\nG1 X10 E1\nT7\n;Z:0.8\n;TYPE:Support material interface\nG1 Y10 E1\nT0\n;Z:1.55\n;TYPE:External perimeter\nG1 X11 E1\n"
        self.assertEqual(check_support_gcode(text, 4, 8)["firstPETGInterfaceZ"], 0.8)
        with self.assertRaisesRegex(ValueError, "foundation"):
            check_support_gcode(text.replace(";Z:0.8", ";Z:0.2"), 4, 8)
        with self.assertRaisesRegex(ValueError, "model feature"):
            check_support_gcode(text.replace("T0\n", "T7\n"), 4, 8)

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
