"""
Blender Agent Terminal — Add-on Preferences

Stored in Blender's user preferences (auto-saved with .blend).
Access: context.preferences.addons[__package__].preferences
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty


def get_addon_name() -> str:
    pkg = __package__
    if pkg and pkg.startswith("bl_ext."):
        return ".".join(pkg.split(".")[:3])
    return pkg.split(".")[0] if pkg else "blender_agent_terminal"


class BATAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = get_addon_name()

    font_size: IntProperty(
        name="Font Size",
        description="Terminal font size in points",
        default=13,
        min=8,
        max=32,
    )  # type: ignore

    theme: EnumProperty(
        name="Color Theme",
        description="Terminal color scheme",
        items=[
            ("BLENDER",   "Blender Native", "Adapt to Blender's UI Theme"),
            ("DARK",      "Dark",           "Classic dark terminal"),
            ("DRACULA",   "Dracula",        "Dracula color scheme"),
            ("SOLARIZED", "Solarized Dark", "Solarized Dark scheme"),
            ("LIGHT",     "Light",          "Light background terminal"),
        ],
        default="BLENDER",
    )  # type: ignore

    shell: StringProperty(
        name="Default Shell",
        description="Shell to use when no command is specified (leave blank for auto-detect)",
        default="",
        subtype="FILE_PATH",
    )  # type: ignore

    max_scrollback: IntProperty(
        name="Scrollback Lines",
        description="Maximum number of scrollback lines to keep in memory",
        default=2000,
        min=100,
        max=10000,
    )  # type: ignore

    cursor_blink: BoolProperty(
        name="Blink Cursor",
        description="Enable terminal cursor blinking",
        default=True,
    )  # type: ignore

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.prop(self, "font_size")
        col.prop(self, "theme")
        col.prop(self, "shell")
        col.prop(self, "max_scrollback")
        col.prop(self, "cursor_blink")


def get_prefs(context: bpy.types.Context) -> BATAddonPreferences:
    """Convenience accessor for preferences."""
    addon = context.preferences.addons.get(get_addon_name())
    return addon.preferences if addon else None


CLASSES = [BATAddonPreferences]
