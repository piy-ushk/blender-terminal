import bpy
import sys

for key, addon in bpy.context.preferences.addons.items():
    if "blender_agent" in key:
        print("FOUND ADDON:", key)
        print("HAS PREFS:", hasattr(addon, "preferences") and addon.preferences is not None)
