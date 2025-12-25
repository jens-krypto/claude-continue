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
FOLLOWUP_PROMPTS = [
    # Plan-focused
    "What's the next step in our plan? Execute it!",
    "Are there any remaining tasks in the todo list? Complete them.",
    "Check if there are pending items and continue with the next one.",

    # Testing-focused
    "How's the test coverage? Run the tests and show me the results.",
    "Are there integration tests? If not, should we add some?",
    "Run the test suite and fix any failures.",

    # Quality-focused
    "Review the code for any improvements or cleanup needed.",
    "Are there any TODO comments in the code that should be addressed?",
    "Check for any error handling that might be missing.",

    # Security-focused
    "How's the security? Have you reviewed it for vulnerabilities?",
    "Check for any security issues - input validation, injection risks, etc.",
    "Review the code for OWASP top 10 vulnerabilities.",

    # Architecture-focused
    "Is the architecture sound? Any improvements needed?",
    "Review the code structure and suggest architectural improvements.",
    "Check if the separation of concerns is properly maintained.",

    # Documentation-focused
    "Does README.md exist and is it up to date?",
    "Is there anything that should be documented?",
    "Check if the documentation matches the current implementation.",

    # Verification
    "Verify that everything works by running a quick test.",
    "Double-check the implementation against the requirements.",
    "Do a final review before we wrap up.",

    # Deep thinking
    "Use ultrathink to deeply analyze the problem and solution.",
    "Think step by step about potential edge cases we might have missed.",
    "Consider using extended thinking to review the implementation.",

    # Agent delegation
    "Is this task complex enough to benefit from using agents?",
    "Consider delegating parts of this to specialized agents for better results.",
    "Would breaking this into subtasks for agents improve the outcome?",

    # Out of ideas
    "If you've run out of ideas, what would be the best next step?",
    "What else could we improve or add to this implementation?",
    "Are there any features or edge cases we haven't considered yet?",
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
LOG_TO_CONSOLE = os.getenv("CLAUDE_CONTINUE_LOG_CONSOLE", "true").lower() == "true"

# =============================================================================
# DEBUG MODE
# =============================================================================
DEBUG = os.getenv("CLAUDE_CONTINUE_DEBUG", "false").lower() == "true"
