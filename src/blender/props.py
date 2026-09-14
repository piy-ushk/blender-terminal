"""
Blender Agent Terminal — WindowManager Custom Properties

These properties live on the WindowManager so they persist for the
lifetime of a Blender session but are not saved to .blend files.
They act as fast inter-operator communication channels.
"""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty


def register_props() -> None:
    wm = bpy.types.WindowManager

    # Whether the terminal panel is currently active/rendered
    wm.bat_terminal_active = BoolProperty(
        name="Terminal Active",
        default=False,
    )  # type: ignore

    # ID of the currently displayed session
    wm.bat_session_id = StringProperty(
        name="Session ID",
        default="",
    )  # type: ignore

    # Current text being typed into the input bar
    wm.bat_input_line = StringProperty(
        name="Input",
        description="Command input line",
        default="",
    )  # type: ignore

    # Whether the input modal is running
    wm.bat_input_active = BoolProperty(
        name="Input Active",
        default=False,
    )  # type: ignore


def unregister_props() -> None:
    wm = bpy.types.WindowManager
    for attr in ("bat_terminal_active", "bat_session_id", "bat_input_line", "bat_input_active"):
        try:
            delattr(wm, attr)
        except AttributeError:
            pass
