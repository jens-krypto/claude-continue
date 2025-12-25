#!/usr/bin/env python3
"""
Setup wizard for claude-continue daemon.
Runs on first launch to configure the daemon interactively.
"""
import os
import sys
import json
from pathlib import Path

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def color(text: str, c: str) -> str:
    return f"{c}{text}{Colors.END}"

def header(text: str) -> str:
    return color(text, Colors.BOLD + Colors.CYAN)

def success(text: str) -> str:
    return color(text, Colors.GREEN)

def warning(text: str) -> str:
    return color(text, Colors.YELLOW)

def error(text: str) -> str:
    return color(text, Colors.RED)


# Config file location
CONFIG_DIR = Path.home() / ".config" / "claude-continue"
CONFIG_FILE = CONFIG_DIR / "settings.json"
PROJECT_DIR = Path(__file__).parent.parent


def is_first_run() -> bool:
    """Check if this is the first run (no saved config)."""
    return not CONFIG_FILE.exists()


def load_config() -> dict:
    """Load saved configuration."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """Save configuration to file with secure permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Set restrictive umask before creating file
    old_umask = os.umask(0o077)
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    finally:
        os.umask(old_umask)

    # Ensure file is only readable by owner (0600)
    os.chmod(CONFIG_FILE, 0o600)
    print(success(f"\nConfiguration saved to {CONFIG_FILE}"))


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        response = input(prompt + suffix).strip().lower()
        if not response:
            return default
        if response in ('y', 'yes'):
            return True
        if response in ('n', 'no'):
            return False
        print("Please answer 'y' or 'n'")


def ask_choice(prompt: str, choices: list, default: int = 0) -> int:
    """Ask user to choose from a list."""
    print(prompt)
    for i, choice in enumerate(choices):
        marker = ">" if i == default else " "
        print(f"  {marker} {i + 1}. {choice}")

    while True:
        response = input(f"\nChoice [1-{len(choices)}] (default: {default + 1}): ").strip()
        if not response:
            return default
        try:
            idx = int(response) - 1
            if 0 <= idx < len(choices):
                return idx
        except ValueError:
            pass
        print(f"Please enter a number between 1 and {len(choices)}")


def print_banner():
    """Print the welcome banner."""
    banner = """
╔═════════════════════════════════════════════════════════════════════╗
║                                                                     ║
║    ██████╗██╗      █████╗ ██╗   ██╗██████╗ ███████╗                 ║
║   ██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██╔════╝                 ║
║   ██║     ██║     ███████║██║   ██║██║  ██║█████╗                   ║
║   ██║     ██║     ██╔══██║██║   ██║██║  ██║██╔══╝                   ║
║   ╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝███████╗                 ║
║    ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝                 ║
║                                                                     ║
║   ██████╗ ██████╗ ███╗   ██╗████████╗██╗███╗   ██╗██╗   ██╗███████╗ ║
║  ██╔════╝██╔═══██╗████╗  ██║╚══██╔══╝██║████╗  ██║██║   ██║██╔════╝ ║
║  ██║     ██║   ██║██╔██╗ ██║   ██║   ██║██╔██╗ ██║██║   ██║█████╗   ║
║  ██║     ██║   ██║██║╚██╗██║   ██║   ██║██║╚██╗██║██║   ██║██╔══╝   ║
║  ╚██████╗╚██████╔╝██║ ╚████║   ██║   ██║██║ ╚████║╚██████╔╝███████╗ ║
║   ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚══════╝ ║
║                                                                     ║
║                        by Anomaly Alpha                             ║
║                iTerm2 Automation for Claude Code                    ║
║                        addicted.bot                                 ║
╚═════════════════════════════════════════════════════════════════════╝
"""
    print(color(banner, Colors.CYAN))


def run_wizard() -> dict:
    """Run the interactive setup wizard."""
    print_banner()

    print(header("Welcome to Claude Continue Setup!\n"))
    print("This wizard will help you configure the daemon.")
    print("Press Enter to accept defaults shown in [brackets].\n")
    print("-" * 60)

    config = {}

    # Step 1: Behavior mode
    print(header("\n📋 Step 1: Behavior Mode\n"))
    print("How should the daemon handle Claude Code prompts?\n")

    mode = ask_choice(
        "Select automation level:",
        [
            "Full Auto - Approve everything, answer questions automatically",
            "Semi Auto - Approve permissions, but don't answer questions",
            "Cautious - Only auto-continue, ask for permissions",
            "Monitor Only - Just log prompts, never respond automatically",
        ],
        default=0
    )

    if mode == 0:  # Full Auto
        config['auto_approve'] = True
        config['auto_continue'] = True
        config['answer_questions'] = True
    elif mode == 1:  # Semi Auto
        config['auto_approve'] = True
        config['auto_continue'] = True
        config['answer_questions'] = False
    elif mode == 2:  # Cautious
        config['auto_approve'] = False
        config['auto_continue'] = True
        config['answer_questions'] = False
    else:  # Monitor Only
        config['auto_approve'] = False
        config['auto_continue'] = False
        config['answer_questions'] = False

    print(success(f"✓ Mode: {['Full Auto', 'Semi Auto', 'Cautious', 'Monitor Only'][mode]}"))

    # Step 2: Timing settings
    print(header("\n⏱️  Step 2: Timing Settings\n"))

    cooldown = ask_choice(
        "How fast should the daemon respond?",
        [
            "Instant (0.5s) - Fastest, may occasionally double-respond",
            "Normal (1.0s) - Recommended balance",
            "Careful (2.0s) - More deliberate, safer",
        ],
        default=1
    )
    config['cooldown'] = [0.5, 1.0, 2.0][cooldown]
    print(success(f"✓ Cooldown: {config['cooldown']}s"))

    # Step 3: Logging
    print(header("\n📝 Step 3: Logging\n"))

    if ask_yes_no("Enable debug logging?", default=False):
        config['log_level'] = 'DEBUG'
        config['debug'] = True
    else:
        config['log_level'] = 'INFO'
        config['debug'] = False

    print(success(f"✓ Log level: {config['log_level']}"))

    # Step 4: Installation
    print(header("\n🚀 Step 4: Installation\n"))

    if sys.platform == 'darwin':  # macOS
        if ask_yes_no("Install to iTerm2 AutoLaunch? (starts automatically with iTerm2)"):
            config['install_autolaunch'] = True
            install_to_iterm2()
        else:
            config['install_autolaunch'] = False
            print(warning("Skipped - you can run manually with: ./scripts/run.sh"))
    else:
        print(warning("Not on macOS - iTerm2 AutoLaunch not available"))
        config['install_autolaunch'] = False

    # Summary
    print(header("\n" + "=" * 60))
    print(header("✅ Setup Complete!\n"))

    print("Configuration summary:")
    print(f"  • Auto-approve permissions: {success('Yes') if config.get('auto_approve') else warning('No')}")
    print(f"  • Auto-continue: {success('Yes') if config.get('auto_continue') else warning('No')}")
    print(f"  • Answer questions: {success('Yes (Smart Regex)') if config.get('answer_questions') else warning('No')}")
    print(f"  • Response cooldown: {config.get('cooldown', 1.0)}s")
    print(f"  • Debug mode: {success('Yes') if config.get('debug') else 'No'}")

    if config.get('install_autolaunch'):
        print(f"\n{success('The daemon will start automatically when you open iTerm2.')}")
        print("Make sure to enable Python API in iTerm2:")
        print("  Preferences → General → Magic → Enable Python API")
    else:
        print(f"\nTo start manually: {header('./scripts/run.sh')}")

    print("\nTo reconfigure later, run: " + header("python src/wizard.py"))
    print()

    return config


def install_to_iterm2():
    """Install the daemon to iTerm2 AutoLaunch."""
    iterm_scripts = Path.home() / "Library" / "Application Support" / "iTerm2" / "Scripts" / "AutoLaunch"
    iterm_scripts.mkdir(parents=True, exist_ok=True)

    link_path = iterm_scripts / "claude-continue"

    # Remove existing link/dir
    if link_path.is_symlink():
        link_path.unlink()
    elif link_path.is_dir():
        import shutil
        shutil.rmtree(link_path)

    # Create symlink
    link_path.symlink_to(PROJECT_DIR)
    print(success(f"✓ Installed to {link_path}"))


def apply_config(config: dict):
    """Apply saved config to environment variables."""
    mappings = {
        'auto_approve': 'CLAUDE_CONTINUE_AUTO_APPROVE',
        'auto_continue': 'CLAUDE_CONTINUE_AUTO_CONTINUE',
        'answer_questions': 'CLAUDE_CONTINUE_ANSWER_QUESTIONS',
        'cooldown': 'CLAUDE_CONTINUE_COOLDOWN',
        'log_level': 'CLAUDE_CONTINUE_LOG_LEVEL',
        'debug': 'CLAUDE_CONTINUE_DEBUG',
    }

    for key, env_var in mappings.items():
        if key in config:
            value = config[key]
            if isinstance(value, bool):
                value = 'true' if value else 'false'
            os.environ[env_var] = str(value)


def main():
    """Main entry point."""
    if '--reset' in sys.argv:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print(success("Configuration reset. Run wizard again to reconfigure."))
        else:
            print("No configuration to reset.")
        return

    if is_first_run() or '--setup' in sys.argv:
        config = run_wizard()
        save_config(config)
    else:
        config = load_config()
        print(f"Loaded configuration from {CONFIG_FILE}")
        print("Run with --setup to reconfigure, or --reset to start fresh.")

    apply_config(config)
    return config


if __name__ == "__main__":
    main()
