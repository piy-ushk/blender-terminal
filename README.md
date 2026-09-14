# Blender Agent Terminal

**An integrated, interactive terminal inside Blender's UI.**

Run Claude Code, Gemini CLI, OpenAI Codex, npm, git, bash — any CLI tool — in a real terminal panel embedded inside Blender, while your 3D viewport stays fully responsive.

```
┌─────────────────────────────────────────────────────────────┐
│ Blender                                                     │
│                     3D VIEWPORT                             │
├─────────────────────────────────────────────────────────────┤
│ BLENDER AGENT TERMINAL                      [N-panel]       │
│                                                             │
│ $ claude                                                    │
│ > Create a futuristic sci-fi spaceship                      │
│                                                             │
│ Claude:                                                     │
│ ✓ Inspecting Blender scene                                  │
│ ✓ Creating hull                                             │
│ → Adding engines...                                         │
│                                                             │
│ ❯ _                                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Requirements

- **Blender 4.2+** (Extension system with wheel bundling support)
- **macOS** (Apple Silicon or Intel) or **Linux x86_64**
- **Windows** x64: supported, requires pywinpty (see Windows notes below)

---

## Installation

1. Download the `.zip` release from GitHub (or build from source below).
2. In Blender: **Edit → Preferences → Extensions → Install from Disk**.
3. Select the `.zip` file.
4. Enable **Blender Agent Terminal** in the Extensions list.

### Build from Source

```bash
git clone https://github.com/piyushk/blender-terminal
cd blender-terminal

# Download wheels (already included in releases)
python3 -m pip download pyte==0.8.0 --no-deps -d ./wheels/
python3 -m pip download wcwidth --no-deps -d ./wheels/

# Package as zip
zip -r blender_agent_terminal.zip . \
  --exclude "*.git*" --exclude "__pycache__/*" --exclude "*.pyc" \
  --exclude "tests/*" --exclude "docs/*"
```

---

## Usage

1. **Split an area** in Blender and change it to **Text Editor**.
2. Press **N** to open the sidebar.
3. Click the **Terminal** tab.
4. Click **▶ Open Terminal**.
5. The terminal panel opens — type any command and press Enter.

### Quick Launch

The sidebar shows quick-launch buttons for detected AI agents:
- **claude** — Claude Code (Anthropic)
- **gemini** — Gemini CLI (Google)
- **codex** — OpenAI Codex CLI
- **aider** — Aider

Greyed-out buttons indicate the tool isn't installed on your PATH.

### Keyboard Shortcuts (inside terminal area)

| Key | Action |
|-----|--------|
| Any text | Sends input to process |
| Enter | Submit command |
| ↑ / ↓ | Command history / PTY scroll |
| Ctrl+C | Interrupt process (SIGINT) |
| Ctrl+D | Send EOF |
| Ctrl+L | Clear screen |
| Ctrl+Z | Suspend process |
| Ctrl+A | Beginning of line |
| Ctrl+E | End of line |
| Ctrl+K | Kill to end of line |
| Ctrl+U | Kill to beginning |
| Scroll wheel | Scroll terminal output |

---

## Architecture

```
PTY Master FD
    │
    ▼
Reader Thread (daemon)     ← never touches bpy
    │
    ▼
OutputQueue (deque + lock)
    │
    ▼
bpy.app.timers (33ms)      ← main thread only
    │
    ▼
pyte.ByteStream.feed()
    │
    ▼
pyte.Screen buffer
    │
    ▼
draw_handler_add (POST_PIXEL)
    │
    ▼
blf.draw() per row/col     ← JetBrains Mono font
```

---

## Configuration

In **Preferences → Extensions → Blender Agent Terminal**:
- **Font Size** — terminal font size (8–32pt)
- **Color Theme** — Dark / Dracula / Solarized Dark / Light
- **Default Shell** — override auto-detected shell
- **Scrollback Lines** — max lines in scrollback buffer
- **Blink Cursor** — toggle cursor blink

---

## Security

This extension executes real external processes as you (the Blender user).

- **No command is executed without your explicit input.**
- **No network connections are made by this extension.**
- **No scene data is uploaded anywhere.**
- **No hidden telemetry.**
- Standard subprocess security caveats apply. Treat the terminal like any terminal.

---

## License

GNU General Public License v3.0 or later — see [LICENSE](LICENSE).

Bundled dependencies:
- **pyte** — LGPL-3.0 — [github.com/selectel/pyte](https://github.com/selectel/pyte)
- **wcwidth** — MIT — [github.com/jquast/wcwidth](https://github.com/jquast/wcwidth)
- **JetBrains Mono** — OFL-1.1 — [jetbrains.com/lp/mono](https://www.jetbrains.com/lp/mono/)

---

## Roadmap

- [x] **MVP #1** — Basic terminal, PTY, pyte emulation, async architecture
- [ ] **MVP #2** — Persistent sessions, multiple tabs, copy/paste, themes
- [ ] **Stage 3** — Agent convenience (1-click Claude/Gemini launch, scene context)
