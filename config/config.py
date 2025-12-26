"""
Configuration for claude-continue daemon.
Monitors iTerm2 sessions running Claude Code and auto-responds to prompts.
"""
import os

# =============================================================================
# DAEMON BEHAVIOR
# =============================================================================

# Auto-approve all permission requests (use with caution!)
AUTO_APPROVE_ALL = os.getenv("CLAUDE_CONTINUE_AUTO_APPROVE", "true").lower() == "true"

# Cooldown between actions to prevent rapid-fire responses (seconds)
ACTION_COOLDOWN_SECONDS = float(os.getenv("CLAUDE_CONTINUE_COOLDOWN", "1.0"))

# How often to poll for new sessions (seconds)
SESSION_POLL_INTERVAL = float(os.getenv("CLAUDE_CONTINUE_POLL_INTERVAL", "2.0"))

# Session name filter (regex pattern) - matches iTerm2 tab/window titles
SESSION_NAME_FILTER = os.getenv("CLAUDE_CONTINUE_SESSION_FILTER", r".*")

# Screen polling interval (how often to check for new content, seconds)
SCREEN_POLL_INTERVAL = float(os.getenv("CLAUDE_CONTINUE_SCREEN_POLL", "0.5"))

# =============================================================================
# CONTINUATION BEHAVIOR
# =============================================================================

# Whether to automatically continue when Claude stops
AUTO_CONTINUE = os.getenv("CLAUDE_CONTINUE_AUTO_CONTINUE", "true").lower() == "true"

# Message to send when Claude needs to continue
CONTINUE_MESSAGE = os.getenv("CLAUDE_CONTINUE_MESSAGE", "continue")

# How long to wait before sending continue (seconds)
CONTINUE_DELAY = float(os.getenv("CLAUDE_CONTINUE_DELAY", "2.0"))

# =============================================================================
# IDLE/COMPLETION BEHAVIOR
# =============================================================================

# Whether to send follow-up prompts when Claude finishes a task
# DISABLED BY DEFAULT - can send unwanted prompts to wrong sessions
AUTO_FOLLOWUP = os.getenv("CLAUDE_CONTINUE_AUTO_FOLLOWUP", "false").lower() == "true"

# How long to wait after Claude finishes before sending follow-up (seconds)
# This should be longer than CONTINUE_DELAY to avoid overlap
FOLLOWUP_DELAY = float(os.getenv("CLAUDE_CONTINUE_FOLLOWUP_DELAY", "5.0"))

# Minimum time between follow-up prompts (seconds) to avoid spamming
FOLLOWUP_COOLDOWN = float(os.getenv("CLAUDE_CONTINUE_FOLLOWUP_COOLDOWN", "30.0"))

# Follow-up prompts to send when Claude is idle (rotated randomly)
# NOTE: These are marked [AUTO] to indicate automated messages
# Be cautious - these can trigger unwanted actions!
FOLLOWUP_PROMPTS = [
    # Gentle continuation prompts (safest)
    "[AUTO] What's the current status? Please summarize without taking action.",
    "[AUTO] Are there any pending tasks? List them but wait for confirmation before proceeding.",
    "[AUTO] What would be the next logical step? Describe it but don't execute yet.",

    # Status checks (read-only, safe)
    "[AUTO] Can you show me the current todo list status?",
    "[AUTO] What files have been modified in this session?",
    "[AUTO] Summarize what we've accomplished so far.",

    # Deep thinking (safe - just asks to think)
    "[AUTO] Think step by step about potential edge cases we might have missed.",
    "[AUTO] What are the risks or potential issues with the current approach?",

    # Clarification (safe - asks for info)
    "[AUTO] Is there anything unclear that needs clarification before continuing?",
    "[AUTO] What assumptions are we making that should be verified?",
]

# =============================================================================
# QUESTION ANSWERING
# =============================================================================

# Whether to answer questions (uses smart regex patterns)
# DISABLED BY DEFAULT - too risky, can send "yes" to wrong prompts
ANSWER_QUESTIONS = os.getenv("CLAUDE_CONTINUE_ANSWER_QUESTIONS", "false").lower() == "true"

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = os.getenv("CLAUDE_CONTINUE_LOG_LEVEL", "INFO")
LOG_FILE = os.path.expanduser(os.getenv(
    "CLAUDE_CONTINUE_LOG_FILE",
    "~/Library/Logs/claude-continue.log"
))
# Default to file-only logging to keep the terminal clean.
LOG_TO_CONSOLE = os.getenv("CLAUDE_CONTINUE_LOG_CONSOLE", "false").lower() == "true"

# =============================================================================
# DEBUG MODE
# =============================================================================
DEBUG = os.getenv("CLAUDE_CONTINUE_DEBUG", "false").lower() == "true"
