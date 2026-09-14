import bpy
import blf
try:
    font_id = 0
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    print("SUCCESS: blf.color(fontid, r, g, b, a)")
except Exception as e:
    import traceback
    traceback.print_exc()
