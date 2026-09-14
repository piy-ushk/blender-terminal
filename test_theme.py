import bpy

try:
    theme = bpy.context.preferences.themes[0]
    te = theme.text_editor
    print("BACK:", list(te.space.back))
    print("TEXT:", list(te.space.text))
    print("CURSOR:", list(te.cursor))
    print("HEADER:", list(te.space.header))
except Exception as e:
    import traceback
    traceback.print_exc()
