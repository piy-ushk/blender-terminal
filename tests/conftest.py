"""
conftest.py — pytest configuration for Blender Agent Terminal

Installs a minimal bpy mock so that src.blender.* modules can be imported
outside Blender (for unit testing). Only the bare minimum is mocked;
actual bpy behavior is only available inside Blender.
"""

import sys
import types
from unittest.mock import MagicMock

# ─── Minimal bpy mock ─────────────────────────────────────────────────────────

def _make_bpy_mock():
    bpy = types.ModuleType("bpy")

    # bpy.types
    bpy_types = types.ModuleType("bpy.types")
    bpy_types.Panel = object
    bpy_types.Operator = object
    bpy_types.AddonPreferences = object
    bpy_types.WindowManager = MagicMock()
    bpy_types.SpaceTextEditor = MagicMock()
    bpy.types = bpy_types

    # bpy.props (return MagicMock for any property)
    bpy_props = types.ModuleType("bpy.props")
    for prop_name in (
        "StringProperty", "IntProperty", "FloatProperty",
        "BoolProperty", "EnumProperty", "CollectionProperty",
    ):
        setattr(bpy_props, prop_name, MagicMock(return_value=None))
    bpy.props = bpy_props

    # bpy.app
    bpy_app = types.ModuleType("bpy.app")
    bpy_app_timers = types.ModuleType("bpy.app.timers")
    bpy_app_timers.register = MagicMock()
    bpy_app_timers.unregister = MagicMock()
    bpy_app.timers = bpy_app_timers
    bpy.app = bpy_app

    # bpy.utils
    bpy_utils = types.ModuleType("bpy.utils")
    bpy_utils.register_class = MagicMock()
    bpy_utils.unregister_class = MagicMock()
    bpy_utils.user_resource = MagicMock(return_value="/tmp/bat_test")
    bpy.utils = bpy_utils

    # bpy.context
    bpy.context = MagicMock()

    # bpy.data
    bpy.data = MagicMock()
    bpy.data.filepath = ""

    # bpy.ops
    bpy.ops = MagicMock()

    return bpy


# Install mock before any src.* import happens
if "bpy" not in sys.modules:
    _bpy_mock = _make_bpy_mock()
    sys.modules["bpy"] = _bpy_mock
    sys.modules["bpy.types"] = _bpy_mock.types
    sys.modules["bpy.props"] = _bpy_mock.props
    sys.modules["bpy.app"] = _bpy_mock.app
    sys.modules["bpy.app.timers"] = _bpy_mock.app.timers
    sys.modules["bpy.utils"] = _bpy_mock.utils

# Also mock blf and gpu (Blender-only C extensions)
for mod_name in ("blf", "gpu", "gpu_extras", "gpu_extras.batch"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
