import urllib.request
import json

req = urllib.request.Request(
    "http://127.0.0.1:0/exec",
    data=json.dumps({"code": "print('hello world')"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)
print("This test should be run inside Blender context since it relies on bpy.app.timers")
