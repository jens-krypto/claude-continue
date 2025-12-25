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
import webbrowser

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    LOG_LEVEL,
    LOG_FILE,
    LOG_TO_CONSOLE,
    DEBUG,
)


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
        file_handler = logging.FileHandler(LOG_FILE)
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
                logger.info(f"Another Claude Continue instance may be running. Visit http://localhost:{WEB_PORT}")
                start_web = False
            else:
                try:
                    web_runner = await start_web_server()
                    logger.info(f"Web GUI available at http://localhost:{WEB_PORT}")
                    # Auto-open browser
                    webbrowser.open(f"http://localhost:{WEB_PORT}")
                except Exception as e:
                    logger.warning(f"Could not start web GUI: {e}")

        await manager.start()
        logger.info("Claude Continue daemon is running")
        logger.info("Monitoring all iTerm2 sessions for Claude Code prompts")

        # Wait for shutdown
        await shutdown_event.wait()

    finally:
        await manager.stop()
        if web_runner:
            await stop_web_server(web_runner)
        logger.info("Claude Continue daemon stopped")
        # Force exit since iterm2.run_forever doesn't stop cleanly
        import os
        os._exit(0)


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


def print_startup_banner():
    """Print the startup banner."""
    BLUE_BG = '\033[44m'
    YELLOW_BG = '\033[43m'
    BLUE_FG = '\033[97m'
    YELLOW_FG = '\033[30m'
    RESET = '\033[0m'
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
    lines = banner.strip("\n").splitlines()
    height = len(lines)
    width = max(len(line) for line in lines)
    v_start = int(width * 5 / 16)
    v_width = max(2, int(width * 2 / 16))
    h_start = int(height * 4 / 10)
    h_height = max(1, int(height * 2 / 10))

    print()
    for row, line in enumerate(lines):
        padded = line.ljust(width)
        if h_start <= row < h_start + h_height:
            print(f"{YELLOW_BG}{YELLOW_FG}{padded}{RESET}")
            continue
        left = padded[:v_start]
        mid = padded[v_start:v_start + v_width]
        right = padded[v_start + v_width:]
        print(f"{BLUE_BG}{BLUE_FG}{left}{YELLOW_BG}{YELLOW_FG}{mid}{BLUE_BG}{BLUE_FG}{right}{RESET}")


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

    print_startup_banner()

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
