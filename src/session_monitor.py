"""
iTerm2 session monitoring for Claude Code.
Watches terminal sessions and detects prompts that need responses.
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Set
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    ACTION_COOLDOWN_SECONDS,
    SCREEN_POLL_INTERVAL,
    AUTO_APPROVE_ALL,
    AUTO_CONTINUE,
    CONTINUE_MESSAGE,
    CONTINUE_DELAY,
    ANSWER_QUESTIONS,
    AUTO_FOLLOWUP,
    FOLLOWUP_DELAY,
    FOLLOWUP_COOLDOWN,
    FOLLOWUP_PROMPTS,
    DEBUG,
)
import random
from src.pattern_detector import PatternDetector, PromptType, DetectedPrompt
from src.smart_responder import SmartResponder
from web.server import (
    update_session,
    remove_session,
    increment_prompt_count,
    is_session_enabled,
    get_session_state,
    is_force_monitored,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """State tracking for a single session."""
    session_id: str
    last_action_time: float = 0.0
    last_screen_hash: str = ""
    action_count: int = 0
    is_claude_session: bool = False
    last_followup_time: float = 0.0  # Track follow-up cooldown
    followup_index: int = 0  # Rotate through follow-up prompts


class SessionMonitor:
    """Monitors a single iTerm2 session for Claude Code prompts."""

    def __init__(
        self,
        session,  # iterm2.Session
        detector: PatternDetector,
        responder: SmartResponder,
    ):
        self.session = session
        self.detector = detector
        self.responder = responder
        self.state = SessionState(session_id=session.session_id)
        self.running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start monitoring this session."""
        self.running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.debug(f"Started monitoring session {self.state.session_id}")

    async def stop(self):
        """Stop monitoring this session."""
        self.running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.debug(f"Stopped monitoring session {self.state.session_id}")

    async def _monitor_loop(self):
        """Main monitoring loop using screen streaming."""
        try:
            # Try to use screen streamer for real-time updates
            async with self.session.get_screen_streamer(want_contents=True) as streamer:
                while self.running:
                    try:
                        contents = await asyncio.wait_for(
                            streamer.async_get(),
                            timeout=SCREEN_POLL_INTERVAL * 2
                        )
                        if contents:
                            await self._process_screen(contents)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logger.error(f"Error in screen streamer: {e}")
                        await asyncio.sleep(1)

        except Exception as e:
            # Fallback to polling if streaming fails
            logger.warning(f"Screen streaming failed, falling back to polling: {e}")
            await self._polling_loop()

    async def _polling_loop(self):
        """Fallback polling loop for screen content."""
        while self.running:
            try:
                contents = await self.session.async_get_screen_contents()
                if contents:
                    await self._process_screen(contents)
                await asyncio.sleep(SCREEN_POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Error polling screen: {e}")
                await asyncio.sleep(1)

    async def _process_screen(self, contents):
        """Process screen contents and respond to prompts."""
        # Get text content from screen
        screen_text = self._extract_text(contents)
        if not screen_text:
            return

        # Check if screen has changed
        screen_hash = hash(screen_text)
        if screen_hash == self.state.last_screen_hash:
            return
        self.state.last_screen_hash = screen_hash

        # Check cooldown
        now = time.time()
        if now - self.state.last_action_time < ACTION_COOLDOWN_SECONDS:
            return

        # Detect prompts
        prompt = self.detector.detect(screen_text)
        if not prompt:
            return

        # Skip if we already handled this prompt
        if self.detector.is_same_prompt(prompt):
            return

        # Log detection
        if DEBUG:
            logger.debug(f"Detected {prompt.prompt_type.value}: {prompt.text[:100]}")

        # Handle the prompt
        await self._handle_prompt(prompt)

    def _extract_text(self, contents) -> str:
        """Extract text from iTerm2 screen contents."""
        try:
            lines = []
            for i in range(contents.number_of_lines):
                line = contents.line(i)
                if line:
                    lines.append(line.string)
            return '\n'.join(lines)
        except Exception as e:
            logger.error(f"Error extracting screen text: {e}")
            return ""

    async def _handle_prompt(self, prompt: DetectedPrompt):
        """Handle a detected prompt."""
        # Check if this session is enabled in web GUI
        if not is_session_enabled(self.state.session_id):
            return

        # Get dynamic settings from web GUI
        web_state = get_session_state()
        auto_approve = web_state.get("auto_approve", AUTO_APPROVE_ALL)
        auto_continue = web_state.get("auto_continue", AUTO_CONTINUE)
        answer_questions = web_state.get("answer_questions", ANSWER_QUESTIONS)

        response: Optional[str] = None
        action_type: Optional[str] = None

        if prompt.prompt_type == PromptType.PERMISSION:
            if auto_approve:
                response = "1"  # Approve
                action_type = "approved"
                logger.debug(f"Auto-approving: {prompt.text[:50]}")
            else:
                # Use smart regex to decide
                response = self.responder.get_response(prompt.text, prompt.context)
                action_type = f"regex: {response}"
                logger.debug(f"Smart regex decided: {response}")

        elif prompt.prompt_type == PromptType.CONTINUATION:
            if auto_continue:
                await asyncio.sleep(CONTINUE_DELAY)
                response = CONTINUE_MESSAGE
                action_type = "continue"
                logger.debug("Sending continuation")

        elif prompt.prompt_type == PromptType.QUESTION:
            if answer_questions:
                response = self.responder.get_response(prompt.text, prompt.context)
                action_type = f"answered: {response[:20] if response else 'None'}"
                logger.debug(f"Smart regex answered: {response[:50] if response else 'None'}")

        elif prompt.prompt_type == PromptType.COMPLETED:
            # Get auto_followup from web state or config
            auto_followup = web_state.get("auto_followup", AUTO_FOLLOWUP)

            if auto_followup:
                # Check followup cooldown (separate from action cooldown)
                now = time.time()
                if now - self.state.last_followup_time < FOLLOWUP_COOLDOWN:
                    logger.debug(f"Skipping follow-up - cooldown active ({FOLLOWUP_COOLDOWN}s)")
                    return

                # Wait before sending follow-up
                await asyncio.sleep(FOLLOWUP_DELAY)

                # Get next follow-up prompt (rotate through list)
                if FOLLOWUP_PROMPTS:
                    # Shuffle on first use, then rotate
                    if self.state.followup_index == 0:
                        random.shuffle(FOLLOWUP_PROMPTS)

                    response = FOLLOWUP_PROMPTS[self.state.followup_index % len(FOLLOWUP_PROMPTS)]
                    self.state.followup_index += 1
                    action_type = f"followup: {response[:30]}..."
                    logger.debug(f"Sending follow-up prompt: {response}")

                    # Update followup time
                    self.state.last_followup_time = time.time()

        # Send response if we have one
        if response:
            await self._send_response(response)
            self.detector.mark_handled(prompt)
            self.state.last_action_time = time.time()
            self.state.action_count += 1
            # Update web GUI
            increment_prompt_count(self.state.session_id, action_type)

    async def _send_response(self, text: str):
        """Send text to the session."""
        try:
            # Add newline if not present (to submit the response)
            if not text.endswith('\n') and text not in ['1', '2', '3']:
                text = text + '\n'
            await self.session.async_send_text(text)
            logger.debug(f"Sent to session {self.state.session_id}: {text[:50]}")
        except Exception as e:
            logger.error(f"Error sending response: {e}")


class SessionManager:
    """Manages multiple iTerm2 session monitors."""

    def __init__(self, app):  # app: iterm2.App
        self.app = app
        self.monitors: Dict[str, SessionMonitor] = {}
        self.detector = PatternDetector()
        self.responder = SmartResponder()
        self._discovery_task: Optional[asyncio.Task] = None

        logger.debug("Using Smart Regex for fast offline responses")

    async def start(self):
        """Start session discovery and monitoring."""
        self._discovery_task = asyncio.create_task(self._discovery_loop())
        logger.debug("Session manager started")

    async def stop(self):
        """Stop all monitors and cleanup."""
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass

        # Stop all monitors
        for monitor in self.monitors.values():
            if monitor is not None:
                await monitor.stop()
        self.monitors.clear()

        logger.debug("Session manager stopped")

    async def _discovery_loop(self):
        """Periodically discover and monitor new sessions."""
        from config import SESSION_POLL_INTERVAL

        while True:
            try:
                await self._discover_sessions()
                await asyncio.sleep(SESSION_POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session discovery: {e}")
                await asyncio.sleep(5)

    async def _discover_sessions(self):
        """Find all sessions and start monitoring new ones."""
        current_session_ids: Set[str] = set()

        # Get all windows and tabs
        windows = self.app.windows
        for window in windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    current_session_ids.add(session.session_id)

                    if session.session_id not in self.monitors:
                        # New session - start monitoring
                        await self._start_monitoring(session)
                    elif self.monitors[session.session_id] is None:
                        # Non-Claude session - re-check if Claude started
                        is_claude = await self._is_claude_session(session)
                        if is_claude:
                            logger.debug("Claude Code detected in session - starting monitor")
                            await self._start_monitoring(session)

        # Remove monitors for closed sessions
        closed_sessions = set(self.monitors.keys()) - current_session_ids
        for session_id in closed_sessions:
            monitor = self.monitors.pop(session_id)
            if monitor is not None:
                await monitor.stop()
            remove_session(session_id)  # Update web GUI
            logger.debug(f"Removed monitor for closed session {session_id}")

    async def _is_claude_session(self, session) -> bool:
        """Check if a session appears to be running Claude Code.

        STRICT detection - only truly unique Claude Code patterns to avoid
        false positives with other terminals like tmux, Python REPL, etc.
        """
        try:
            # Get screen contents
            contents = await session.async_get_screen_contents()
            if not contents:
                return False

            # Get all text from screen
            lines = []
            for i in range(contents.number_of_lines):
                line = contents.line(i)
                if line:
                    lines.append(line.string)
            screen_text = '\n'.join(lines)

            # ===== DEFINITIVE INDICATORS (100% Claude Code) =====

            # Claude Code specific Unicode characters - UNIQUE to Claude
            # ⏺ (U+23FA) - Claude's action bullet point
            # ⎿ (U+23BF) - Claude's output marker
            if '⏺' in screen_text or '⎿' in screen_text:
                return True

            # Claude Code permission dialog - EXACT format required
            # Must have the specific "don't ask again for similar" text
            if "Yes, and don't ask again for similar" in screen_text:
                return True
            if "No, and tell Claude what to do" in screen_text:
                return True

            # Claude Code status messages - EXACT text
            exact_indicators = [
                'Claude is thinking',
                'Claude stopped',
                'Claude wants to',
                'Allow Claude to',
            ]
            for indicator in exact_indicators:
                if indicator in screen_text:
                    return True

            # ===== HIGH CONFIDENCE INDICATORS =====

            # Tool calls WITH the bullet point prefix (⏺ Read, ⏺ Bash, etc.)
            # Without the bullet, "Read(" could appear anywhere
            tool_with_bullet = [
                '⏺ Read', '⏺ Write', '⏺ Edit', '⏺ Bash',
                '⏺ Glob', '⏺ Grep', '⏺ Task', '⏺ Update',
            ]
            for pattern in tool_with_bullet:
                if pattern in screen_text:
                    return True

            # Check for claude> prompt at START of a line
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('claude>') or stripped.startswith('> claude'):
                    return True

            # Also check terminal title/name for explicit "claude"
            try:
                name = await session.async_get_variable("name") or ""
                # Must be explicit "claude" not just containing letters
                name_lower = name.lower()
                if 'claude' in name_lower and 'code' in name_lower:
                    return True
                if name_lower.startswith('claude'):
                    return True
            except Exception:
                pass

            return False

        except Exception as e:
            logger.debug(f"Error checking session for Claude: {e}")
            return False

    async def _start_monitoring(self, session):
        """Start monitoring a new session if it's running Claude Code."""
        # Get session name for web GUI
        try:
            name = await session.async_get_variable("name") or f"Session {session.session_id[:8]}"
        except Exception:
            name = f"Session {session.session_id[:8]}"

        # Check if force monitored first
        if is_force_monitored(session.session_id):
            is_claude = True
            status = "forced"
            logger.debug(f"Force monitoring session: {name}")
        else:
            # Register as scanning first
            update_session(session.session_id, name, is_claude_session=False, status="scanning")

            # Check if this looks like a Claude Code session
            is_claude = await self._is_claude_session(session)
            status = "detected" if is_claude else "not_detected"

        # Update with final status
        update_session(session.session_id, name, is_claude_session=is_claude, status=status)

        # Only actively monitor Claude Code sessions
        if not is_claude:
            logger.debug(f"Session {name} doesn't appear to be Claude Code - skipping")
            # Still track it so we can detect if Claude starts later
            self.monitors[session.session_id] = None  # Placeholder
            return

        logger.debug(f"Claude Code {'detected' if status == 'detected' else 'forced'} in session: {name}")

        monitor = SessionMonitor(
            session=session,
            detector=self.detector,
            responder=self.responder,
        )
        self.monitors[session.session_id] = monitor
        await monitor.start()
