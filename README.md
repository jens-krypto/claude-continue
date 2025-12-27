# Claude Continue

[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)

An iTerm2 daemon that monitors Claude Code sessions and automatically handles prompts, permissions, and continuations using smart regex patterns.

## What It Does

When you run Claude Code in iTerm2, this daemon:

1. **Auto-approves permission prompts** - When Claude asks "Do you want to allow this operation?", automatically approves safe operations
2. **Sends continuation commands** - When Claude stops and asks "Continue?", automatically sends `continue`
3. **Answers questions intelligently** - Uses smart regex patterns to handle common prompts

## Features

- **Fast & Offline** - No API calls, instant local responses
- **Lightweight** - Only requires iTerm2 Python API + aiohttp for web GUI
- **Smart Patterns** - Handles common Claude Code prompts intelligently
- **Safe Defaults** - Blocks dangerous operations (rm -rf, etc.)
- **Web Control Panel** - Monitor and control sessions via browser

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    iTerm2                           │
│  ┌─────────────────────────────────────────────┐   │
│  │  Tab 1: Claude Code    Tab 2: Claude Code   │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                         │
                         │ Screen Streaming (iTerm2 Python API)
                         ▼
┌─────────────────────────────────────────────────────┐
│              SessionManager                          │
│  ┌─────────────────────────────────────────────┐   │
│  │  SessionMonitor 1   SessionMonitor 2   ...  │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              PatternDetector                         │
│  ┌─────────────────────────────────────────────┐   │
│  │  PERMISSION │ CONTINUATION │ QUESTION       │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     Auto "1"       Auto "continue"   Smart Regex
     (approve)                         Response
```

## Installation

### Requirements

- macOS
- iTerm2 (with Python API enabled)
- Python 3.12
- `claudeContinue.sh` requires a Python 3.12 venv named `venv` in the repo root

### Quick Install

```bash
git clone https://github.com/jens-krypto/claude-continue.git
cd claude-continue
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/daemon.py --setup
```

The interactive wizard will guide you through:
1. **Behavior Mode** - Full Auto, Semi Auto, Cautious, or Monitor Only
2. **Timing Settings** - Response speed configuration
3. **Logging** - Debug mode toggle
4. **iTerm2 Installation** - Optional AutoLaunch setup

### Alternative: Script Install

```bash
./scripts/install.sh
```

### Manual Install

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Enable iTerm2 Python API:
   - Open iTerm2 Preferences (Cmd+,)
   - Go to "General" > "Magic"
   - Enable "Enable Python API"

3. Create AutoLaunch symlink:
```bash
mkdir -p ~/Library/Application\ Support/iTerm2/Scripts/AutoLaunch
ln -s $(pwd) ~/Library/Application\ Support/iTerm2/Scripts/AutoLaunch/claude-continue
```

4. Restart iTerm2

## Usage

### Automatic Mode (Recommended)

After installation, the daemon starts automatically when iTerm2 launches. It monitors all terminal sessions for Claude Code activity.

### Manual Mode

```bash
# Run with iTerm2 integration
./scripts/run.sh

# Test without iTerm2 (pattern detection only)
./scripts/run.sh --test

# Debug mode
./scripts/run.sh --debug

# Re-run setup wizard
./scripts/run.sh --setup

# Reset config and re-run wizard
./scripts/run.sh --reset

# Run without web GUI
./scripts/run.sh --no-web
```

## Web Control Panel

The daemon includes a web GUI for controlling sessions:

**http://localhost:7777**

### Features

- **Session Overview** - See all active Claude sessions in iTerm2
- **Toggle Automation** - Enable/disable automation per session
- **Live Settings** - Change auto-approve, auto-continue, answer questions on the fly
- **Action Tracking** - See how many prompts have been handled per session

### Disabling the Web GUI

```bash
python src/daemon.py --no-web
```

## Configuration

Edit `config/config.py` or set environment variables:

### Behavior
```bash
export CLAUDE_CONTINUE_AUTO_APPROVE="true"      # Auto-approve all permissions
export CLAUDE_CONTINUE_AUTO_CONTINUE="true"     # Auto-send continue
export CLAUDE_CONTINUE_ANSWER_QUESTIONS="true"  # Auto-answer questions
export CLAUDE_CONTINUE_COOLDOWN="1.0"           # Seconds between actions
```

### Logging
```bash
export CLAUDE_CONTINUE_LOG_LEVEL="INFO"         # DEBUG, INFO, WARNING, ERROR
export CLAUDE_CONTINUE_LOG_FILE="~/Library/Logs/claude-continue.log"
export CLAUDE_CONTINUE_DEBUG="false"            # Extra verbose logging
```

## macOS Permissions

### iTerm2 Python API

The daemon requires iTerm2's Python API to be enabled:

1. Open **iTerm2 Preferences** (Cmd+,)
2. Go to **General** → **Magic**
3. Check **Enable Python API**
4. Restart iTerm2

### Chrome Tab Reuse (Optional)

When the daemon starts, it opens the web GUI in your browser. To reuse an existing tab instead of opening a new one:

1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **Privacy & Security** → **Automation**
3. Find **iTerm** in the list
4. Enable **Google Chrome** ✅

Without this permission, a new browser tab will open each time.

### Accessibility (If Needed)

If you encounter issues with the daemon detecting or sending keystrokes:

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Add **iTerm** to the list and enable it

## File Structure

```
claude-continue/
├── README.md                 # This file
├── LICENSE                   # GPL v3
├── requirements.txt          # Python dependencies
├── config/
│   ├── __init__.py
│   └── config.py             # Configuration settings
├── src/
│   ├── __init__.py
│   ├── daemon.py             # Main entry point
│   ├── session_monitor.py    # iTerm2 session monitoring
│   ├── pattern_detector.py   # Prompt pattern detection
│   ├── smart_responder.py    # Regex-based response logic
│   └── wizard.py             # Setup wizard
├── web/
│   ├── __init__.py
│   └── server.py             # Web GUI server (port 7777)
├── scripts/
│   ├── install.sh            # Install to iTerm2
│   ├── uninstall.sh          # Remove from iTerm2
│   └── run.sh                # Run manually
└── tests/
    ├── test_pattern_detector.py
    └── test_smart_responder.py
```

## Security Risks & Considerations

```
╔═══════════════════════════════════════════════════════════════════════════╗
║  ⚠️  WARNING: This software automates command execution.                  ║
║      You run this service entirely at your own risk.                      ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

Before enabling any automation level, please understand the implications:

### Risk Overview

```
┌─────────────────────┬────────────────┬──────────────────────────────────────┐
│ Setting             │ Risk Level     │ What Could Go Wrong                  │
├─────────────────────┼────────────────┼──────────────────────────────────────┤
│ Auto-Approve        │ HIGH           │ Unintended file changes/deletions    │
│ Auto-Continue       │ MEDIUM         │ Operations continue without review   │
│ Answer Questions    │ HIGH           │ Wrong answers to important decisions │
│ Auto Follow-up      │ MEDIUM-HIGH    │ Unwanted actions in idle sessions    │
└─────────────────────┴────────────────┴──────────────────────────────────────┘
```

### Auto-Approve Permissions

**What it does:** Automatically presses "1" (Yes) when Claude asks for permission to run commands.

**Real risks:**
- Claude might delete files you didn't want deleted
- Could modify code in unexpected ways
- May execute shell commands with unintended side effects
- Git operations (commits, pushes) happen without review

**When to enable:** Only when working on non-critical code where you're comfortable with Claude having full autonomy. Never use on production systems.

**Recommendation:** Start with this OFF. Review the patterns in `smart_responder.py` and the dangerous command blocklist before enabling.

### Auto-Continue

**What it does:** Sends "continue" when Claude pauses or asks if you want it to proceed.

**Real risks:**
- Long refactoring operations continue without checkpoints
- May continue down a wrong path without your course correction
- Resource-intensive operations run to completion

**When to enable:** When you trust Claude's current direction and want uninterrupted work sessions.

**Recommendation:** Generally safer than Auto-Approve, but review Claude's plan before enabling.

### Answer Questions

**What it does:** Uses regex patterns to automatically answer Claude's questions (like "Which option?" → "1").

**Real risks:**
- May choose wrong options for important decisions
- Could provide incorrect file names or paths
- Answers are based on simple pattern matching, not understanding

**When to enable:** Only for very routine tasks where the questions are predictable.

**Recommendation:** Keep OFF. This is disabled by default for good reason.

### Auto Follow-up

**What it does:** Sends prompts to Claude when it appears idle (e.g., "What's next?").

**Real risks:**
- May trigger unwanted actions when you stepped away
- Could start new tasks you didn't intend
- May confuse Claude's context

**When to enable:** Only during active pair-programming sessions where you're monitoring.

**Recommendation:** Keep OFF unless actively working.

### General Safety Tips

1. **Start conservative** - Begin with all settings OFF, enable one at a time
2. **Monitor the logs** - Check `~/Library/Logs/claude-continue.log` regularly
3. **Use per-session controls** - Disable automation for sensitive sessions via the web GUI
4. **Review the blocklist** - Check `src/smart_responder.py` for blocked dangerous commands
5. **Keep backups** - Use git and don't auto-approve in repos without commits
6. **Test first** - Run with `--test` flag to see pattern matching without actions

### What We Block

The daemon attempts to block obviously dangerous commands like:
- `rm -rf /` and similar destructive operations
- `curl ... | bash` (remote code execution)
- SQL DROP/DELETE statements
- Fork bombs and reverse shells
- Git force pushes

However, **no blocklist is perfect**. Novel dangerous commands may slip through.

---

## Smart Responder Patterns

### Safe Operations (Auto-Approved)
- Read operations: `read file.py`
- Edit code files: `edit main.py`, `edit component.tsx`
- Git status/diff/log
- Running tests: `pytest`, `npm test`

### Dangerous Operations (Auto-Denied)
- `rm -rf /` or `rm -rf ~`
- `curl ... | bash`
- Editing `.env` files
- SQL DROP/DELETE statements

### Question Responses
- "Would you like me to continue?" → `continue`
- "Do you want to create the file?" → `yes`
- "Which option?" → `1`

## Troubleshooting

### Daemon not starting

1. Check if Python API is enabled in iTerm2 preferences
2. Check logs: `tail -f ~/Library/Logs/claude-continue.log`
3. Run manually: `./scripts/run.sh --debug`

### Not detecting prompts

1. Run test mode: `./scripts/run.sh --test`
2. Check pattern detector output
3. Adjust patterns in `src/pattern_detector.py`

## Uninstall

```bash
./scripts/uninstall.sh
```

## About Anomaly Alpha

This project is brought to you by [Anomaly Alpha](https://addicted.bot), an AI-focused crypto project building tools and infrastructure for the intersection of artificial intelligence and blockchain technology.

We've open-sourced Claude Continue to share it with the developer community. If you find it useful, feel free to check out what else we're building.

- Website: [addicted.bot](https://addicted.bot)
- X: [@AddictedAnomaly](https://x.com/AddictedAnomaly)
- Telegram: [t.me/AnomalyAlpha](https://t.me/AnomalyAlpha)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GPL v3 License - see the [LICENSE](LICENSE) file for details.
