#!/usr/bin/env python3
"""
Claude Continue Daemon
======================

A daemon that monitors iTerm2 sessions running Claude Code and automatically:
1. Presses 1 or 2 to approve/deny permission prompts
2. Sends "continue" when Claude stops
3. Uses smart regex patterns to answer questions

This daemon is designed to run as an iTerm2 AutoLaunch script.

Usage:
    python daemon.py              # Run as standalone daemon
    python daemon.py --test       # Run in test mode (no iTerm2)
    python daemon.py --debug      # Run with debug logging

Installation:
    Copy to ~/Library/Application Support/iTerm2/Scripts/AutoLaunch/
    Restart iTerm2

Requirements:
    - macOS with iTerm2
    - Python 3.10+
    - iterm2 Python package
"""

import asyncio
import logging
import argparse
import sys
import os
import signal
import socket
import subprocess
import webbrowser

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    LOG_LEVEL,
    LOG_FILE,
    LOG_TO_CONSOLE,
    DEBUG,
)


def open_browser_tab(url: str) -> bool:
    """Open URL in browser, reusing existing tab if possible.

    Uses AppleScript to check if Chrome has a tab with the URL already open.
    If yes, switches to that tab. If no, opens a new tab.
    Falls back to webbrowser.open() if AppleScript fails.

    Returns True if successful.
    """
    # AppleScript to find and switch to existing tab, or open new one
    applescript = f'''
    tell application "Google Chrome"
        set found to false
        set targetURL to "{url}"

        repeat with w in windows
            set tabIndex to 0
            repeat with t in tabs of w
                set tabIndex to tabIndex + 1
                if URL of t starts with targetURL then
                    set found to true
                    set active tab index of w to tabIndex
                    set index of w to 1
                    activate
                    return "found"
                end if
            end repeat
        end repeat

        if not found then
            if (count of windows) = 0 then
                make new window
            end if
            tell front window
                make new tab with properties {{URL:targetURL}}
            end tell
            activate
            return "opened"
        end if
    end tell
    '''

    try:
        result = subprocess.run(
            ['osascript', '-e', applescript],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    # Fallback to default browser
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


class NoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("aiohttp.access"):
            return False
        return True

# Setup logging
def setup_logging():
    """Configure logging for the daemon."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    handlers = []

    if LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        console_handler.addFilter(NoiseFilter())
        handlers.append(console_handler)

    # Create log directory if needed
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    try:
        # Set restrictive umask for log file creation
        old_umask = os.umask(0o077)
        try:
            file_handler = logging.FileHandler(LOG_FILE)
        finally:
            os.umask(old_umask)

        # Ensure log file has secure permissions (0600)
        try:
            os.chmod(LOG_FILE, 0o600)
        except Exception:
            pass  # May fail if file doesn't exist yet

        file_handler.setFormatter(logging.Formatter(log_format))
        file_handler.addFilter(NoiseFilter())
        handlers.append(file_handler)
    except Exception as e:
        print(f"Warning: Could not create log file {LOG_FILE}: {e}")

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers,
    )

    # Reduce noise from other loggers
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.web").setLevel(logging.WARNING)
    access_logger = logging.getLogger("aiohttp.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.setLevel(logging.CRITICAL)
    access_logger.disabled = True


logger = logging.getLogger(__name__)


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('localhost', port)) == 0


async def main_iterm2(connection, start_web=True):
    """Main entry point for iTerm2 daemon mode."""
    import iterm2
    from src.session_monitor import SessionManager
    from web.server import start_web_server, stop_web_server, WEB_PORT

    logger.info("Claude Continue daemon starting...")

    app = await iterm2.async_get_app(connection)
    manager = SessionManager(app)
    web_runner = None
    web_url = f"http://localhost:{WEB_PORT}"

    # Handle shutdown signals
    shutdown_event = asyncio.Event()
    shutdown_triggered = False

    def signal_handler():
        nonlocal shutdown_triggered
        if shutdown_triggered:
            # Force exit on second signal
            logger.info("Force exit")
            import os
            os._exit(0)
        shutdown_triggered = True
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # Start web GUI if enabled
        if start_web:
            # Check if port is already in use
            if is_port_in_use(WEB_PORT):
                logger.warning(f"Port {WEB_PORT} already in use - web GUI disabled")
                logger.info(f"Another Claude Continue instance may be running. Visit {web_url}")
                print(f"Web GUI already running at {web_url}")
                open_browser_tab(web_url)
                start_web = False
            else:
                try:
                    web_runner = await start_web_server()
                    logger.info(f"Web GUI available at {web_url}")
                    print(f"Web GUI running at {web_url}")
                    # Auto-open browser (reuses existing tab if open)
                    open_browser_tab(web_url)
                except Exception as e:
                    logger.warning(f"Could not start web GUI: {e}")
                    print(f"Web GUI failed to start: {e}")

        await manager.start()
        logger.info("Claude Continue daemon is running")
        logger.info("Monitoring all iTerm2 sessions for Claude Code prompts")

        # Wait for shutdown
        await shutdown_event.wait()

    finally:
        logger.info("Shutting down Claude Continue daemon...")
        try:
            await manager.stop()
        except Exception as e:
            logger.error(f"Error stopping session manager: {e}")

        if web_runner:
            try:
                await stop_web_server(web_runner)
            except Exception as e:
                logger.error(f"Error stopping web server: {e}")

        logger.info("Claude Continue daemon stopped")

        # Cancel any remaining tasks for clean shutdown
        try:
            loop = asyncio.get_event_loop()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                if task is not asyncio.current_task():
                    task.cancel()
        except Exception:
            pass

        # Use sys.exit for cleaner shutdown than os._exit
        # This allows Python to run cleanup handlers
        sys.exit(0)


def main_test():
    """Test mode without iTerm2 connection."""
    from src.pattern_detector import PatternDetector
    from src.smart_responder import SmartResponder

    logger.info("Running in test mode (no iTerm2 connection)")

    detector = PatternDetector()
    responder = SmartResponder()

    # Test pattern detection
    test_screens = [
        """
        Claude wants to edit file.py

        1. Yes
        2. Yes, and don't ask again for similar commands
        3. No, and tell Claude what to do differently (esc)
        """,
        """
        The operation completed successfully.
        Would you like me to continue?
        """,
        """
        What file should I create for the tests?
        Please provide the filename.
        """,
    ]

    print("\n=== Pattern Detection Tests ===\n")

    for i, screen in enumerate(test_screens, 1):
        print(f"--- Test {i} ---")
        print(f"Screen content:\n{screen[:200]}...")

        prompt = detector.detect(screen)
        if prompt:
            print(f"Detected: {prompt.prompt_type.value}")
            print(f"Text: {prompt.text}")
            print(f"Suggested: {prompt.suggested_response}")
            print(f"Confidence: {prompt.confidence:.2f}")

            # Get smart regex response
            response = responder.get_response(prompt.text, prompt.context)
            print(f"Smart Regex response: {response}")
        else:
            print("No prompt detected")
        print()

    logger.info("Test mode completed")


def print_startup_banner(show_web: bool = True):
    """Print the startup banner."""
    BORDER = '\033[94m'
    TEXT = '\033[97m'
    ACCENT = '\033[92m'
    RESET = '\033[0m'
    def center_line(text: str) -> str:
        return f"║{text.center(69)}║"

    web_gui_line = center_line("Web GUI: http://localhost:7777") if show_web else center_line("")
    copyright_line = center_line("Copyright Anomaly Alpha Labs 2025")
    tagline_line = center_line("iTerm2 Automation for Claude Code")
    site_line = center_line("addicted.bot")
    banner = f"""
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
{web_gui_line}
{copyright_line}
{tagline_line}
{site_line}
╚═════════════════════════════════════════════════════════════════════╝
"""
    print()
    for line in banner.strip("\n").splitlines():
        if line.startswith(("╔", "╚")):
            print(f"{BORDER}{line}{RESET}")
            continue
        if line.startswith("║") and line.endswith("║"):
            inner = line[1:-1]
            if any(token in inner for token in ("Web GUI", "Copyright", "addicted.bot")):
                inner_color = ACCENT
            else:
                inner_color = TEXT
            print(f"{BORDER}║{inner_color}{inner}{BORDER}║{RESET}")
            continue
        print(f"{TEXT}{line}{RESET}")

    # Print disclaimer
    WARNING = '\033[93m'
    DIM = '\033[2m'
    print()
    print(f"{WARNING}⚠️  DISCLAIMER: This software is provided as-is.{RESET}")
    print(f"{WARNING}   You run this service at your own risk.{RESET}")
    print(f"{WARNING}   Auto-approving commands can be dangerous.{RESET}")
    print()
    print(f"{DIM}Press Ctrl+C to stop the daemon.{RESET}")
    print()


def run_daemon(start_web=True):
    """Run the daemon with iTerm2 integration."""

    try:
        import iterm2
    except ImportError:
        print("ERROR: iterm2 package not found.")
        print("Install with: pip install iterm2")
        print("")
        print("Note: The iterm2 package only works on macOS with iTerm2 installed.")
        print("Run with --test flag to test without iTerm2.")
        sys.exit(1)

    logger.info("Starting Claude Continue daemon with iTerm2...")
    # Wrap main_iterm2 to pass the web flag
    async def main_with_web(connection):
        await main_iterm2(connection, start_web=start_web)

    iterm2.run_forever(main_with_web)


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Claude Continue - iTerm2 automation daemon for Claude Code"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run in test mode without iTerm2 connection"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the setup wizard"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset configuration and run setup wizard"
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Disable the web GUI (runs on port 7777)"
    )

    args = parser.parse_args()

    print_startup_banner(show_web=not args.no_web)

    if args.version:
        from src import __version__
        print(f"claude-continue v{__version__}")
        sys.exit(0)

    # Import wizard for config handling
    from src.wizard import is_first_run, run_wizard, save_config, load_config, apply_config, CONFIG_FILE

    # Handle reset
    if args.reset:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print("Configuration reset.")

    # Run wizard on first run or if explicitly requested
    if is_first_run() or args.setup or args.reset:
        config = run_wizard()
        save_config(config)
        apply_config(config)

        # If just setting up, don't run the daemon
        if args.setup or args.reset:
            print("\nSetup complete! Run without --setup to start the daemon.")
            sys.exit(0)
    else:
        # Load and apply saved config
        config = load_config()
        apply_config(config)

    # Override debug setting if flag provided
    if args.debug:
        os.environ["CLAUDE_CONTINUE_DEBUG"] = "true"
        os.environ["CLAUDE_CONTINUE_LOG_LEVEL"] = "DEBUG"

    setup_logging()

    if args.test:
        main_test()
    else:
        run_daemon(start_web=not args.no_web)


if __name__ == "__main__":
    main()
