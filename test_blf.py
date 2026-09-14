import bpy
import blf
try:
    font_id = 0
    blf.size(font_id, 13, 144)
    print("SUCCESS: blf.size(font_id, 13, 144)")
except Exception as e:
    import traceback
    traceback.print_exc()
