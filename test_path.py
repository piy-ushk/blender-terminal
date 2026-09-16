import subprocess
import os

shell = os.environ.get("SHELL", "/bin/zsh")
print("SHELL:", shell)
result = subprocess.run([shell, "-ilc", "env"], capture_output=True, text=True, timeout=2.0)
for line in result.stdout.splitlines():
    if line.startswith("PATH="):
        print("FOUND PATH:", line[5:])
