# Claude Continue

[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
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
- Python 3.10+

### Quick Install

```bash
git clone https://github.com/jens-krypto/claude-continue.git
cd claude-continue
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
