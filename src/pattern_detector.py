"""
Pattern detection for Claude Code prompts.
Identifies permission prompts, questions, and continuation needs.
"""
import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)


class PromptType(Enum):
    """Types of prompts that can be detected."""
    PERMISSION = "permission"           # Yes/No permission request (press 1 or 2)
    QUESTION = "question"               # Open-ended question needing answer
    CONTINUATION = "continuation"       # Claude stopped/waiting for continue
    COMPLETED = "completed"             # Claude finished task, idle and waiting
    USER_INPUT = "user_input"           # Waiting for user text input
    IDLE = "idle"                       # No action needed


@dataclass
class DetectedPrompt:
    """A detected prompt with metadata."""
    prompt_type: PromptType
    text: str                           # The actual prompt text
    context: str                        # Surrounding context
    suggested_response: Optional[str]   # Pre-determined response if obvious
    confidence: float                   # 0.0 to 1.0 confidence score


class PatternDetector:
    """Detects Claude Code prompts and determines appropriate responses."""

    # Permission prompt patterns (numbered options)
    PERMISSION_PATTERNS = [
        # Tool permission dialogs - detect the "Claude wants to" pattern
        r"Claude wants to (edit|write|read|run|execute|delete|create|use|call)",
        r"Allow (Claude|this)?\s*(to)?\s*(edit|write|read|run|execute|delete|create)",

        # Numbered options indicating permission dialog
        r"^\s*[1-3]\.\s*(Yes|No|Allow|Deny|Approve|Cancel|Ja|Nej)",
        r"^\s*\[?[1-3]\]?\s*[:\-]?\s*(Yes|No|Allow|Ja|Nej)",

        # Direct permission questions (must be at start of line to avoid matching inside questions)
        r"^Do you want (to|Claude to)",
        r"^Would you like (to|Claude to)",
        r"^Should (I|Claude|we)",
        r"^Can (I|Claude|we)",
        r"^Is it (ok|okay|fine) (to|if)",

        # Swedish permission patterns
        r"^Vill du (att|att jag|att Claude)",
        r"^Ska (jag|vi|Claude)",
        r"^Får (jag|vi|Claude)",
        r"^Kan (jag|vi|Claude)",
        r"^Tillåt",

        # Tool-specific patterns
        r"(Bash|Edit|Read|Write|Glob|Grep|Task|WebFetch).*\?",
    ]

    # Patterns that indicate Claude is waiting for continuation
    # Be specific but allow natural phrasing
    CONTINUATION_PATTERNS = [
        # Claude Code specific - "Stopped" on its own line or with icon
        r"^\s*Stopped\s*$",  # "Stopped" on its own line (with optional whitespace)
        r"^\s*⏹\s*Stopped",  # With stop icon
        r"Waiting for (input|response)",
        r"Press (any key|Enter) to continue",
        r"Continue\?\s*$",  # Ends with Continue?
        r"Do you want me to continue",
        r"Shall I (continue|proceed|go on)",
        r"Would you like me to (continue|proceed)",

        # Swedish continuation patterns
        r"Vill du att jag fortsätter",
        r"Ska jag fortsätta",
    ]

    # Patterns that indicate Claude has completed a task and is idle
    COMPLETED_PATTERNS = [
        # Explicit completion messages
        r"Let me know if you (need|want|have) (anything|something) else",
        r"Is there anything else",
        r"Let me know if (that|this) works",
        r"Let me know (if|when) you('re| are) ready",
        r"Feel free to (ask|let me know)",

        # Task completion indicators
        r"I('ve| have) (finished|completed|done)",
        r"(All|Everything) (is )?done",
        r"(Task|Work|Changes?) (is |are )?(completed?|finished|done)",
        r"(Successfully|Done)!?\s*$",
        r"(Changes|Updates?) (have been |were )?(made|applied|committed|pushed)",

        # Summary indicators (Claude often summarizes when done)
        r"^(In summary|To summarize|Summary):?",
        r"^That('s| is) (it|all|everything)",
        r"should (now )?work",

        # Ready for next task
        r"Ready (for|to start) (the )?next",
        r"What('s| is|'s| would be) next\??",
        r"Anything else (you('d| would) like|I (can|should) (do|help))",

        # Swedish completion patterns
        r"Säg till om du (behöver|vill ha) (något|mer)",
        r"(Finns det|Är det) något (annat|mer)",
        r"Jag är (klar|färdig)",
        r"(Klart|Färdigt|Gjort)!?\s*$",
        r"Nu (fungerar|funkar) det",
        r"Vad vill du göra (härnäst|nu)",
    ]

    # Patterns indicating a question that needs a text answer
    QUESTION_PATTERNS = [
        r"What .+\?",                         # What ... ? questions
        r"Which .+\?",                        # Which ... ? questions
        r"How .+\?",                          # How ... ? questions
        r"Where .+\?",                        # Where ... ? questions
        r"When .+\?",                         # When ... ? questions
        r"Why .+\?",                          # Why ... ? questions
        r"Please (specify|provide|enter|type)",
        r"Enter (the|a|your)",
        r"Type (the|a|your)",
        r"Provide (the|a|your)",

        # Swedish question patterns
        r"Vad .+\?",                          # What ... ? questions
        r"Vilken .+\?",                       # Which ... ? questions
        r"Vilket .+\?",                       # Which ... ? questions
        r"Hur .+\?",                          # How ... ? questions
        r"Var .+\?",                          # Where ... ? questions
        r"När .+\?",                          # When ... ? questions
        r"Varför .+\?",                       # Why ... ? questions
        r"(Ange|Skriv in|Fyll i) (din|ditt|en|ett)",
    ]

    # Patterns to IGNORE (normal output, not prompts)
    IGNORE_PATTERNS = [
        r"^\s*$",                          # Empty lines
        r"^[-=]{3,}$",                     # Separator lines
        r"^\s*#",                          # Comments
        r"^\s*//",                         # Comments
        r"^(import|from|def|class|function|const|let|var)\s",  # Code
        r"^\d{4}-\d{2}-\d{2}",             # Timestamps
        r"^\[\d{2}:\d{2}:\d{2}\]",         # Log timestamps
        r"Pondering",                      # Claude is thinking
        r"\* Pondering\.\.\.",             # Full pondering indicator
    ]

    def __init__(self):
        self._compile_patterns()
        self._last_detected: Optional[DetectedPrompt] = None
        self._detection_count = 0

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance."""
        self._permission_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.PERMISSION_PATTERNS]
        self._continuation_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.CONTINUATION_PATTERNS]
        self._completed_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.COMPLETED_PATTERNS]
        self._question_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.QUESTION_PATTERNS]
        self._ignore_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.IGNORE_PATTERNS]

    def detect(self, screen_content: str) -> Optional[DetectedPrompt]:
        """
        Analyze screen content and detect any prompts.

        Args:
            screen_content: The current terminal screen content

        Returns:
            DetectedPrompt if a prompt is found, None otherwise
        """
        if not screen_content or not screen_content.strip():
            return None

        # Get the last few lines (most recent output)
        lines = screen_content.strip().split('\n')
        recent_lines = lines[-20:]  # Last 20 lines
        recent_text = '\n'.join(recent_lines)

        # Check for permission prompts first (highest priority)
        if prompt := self._check_permission(recent_text, screen_content):
            return prompt

        # Check for continuation prompts
        if prompt := self._check_continuation(recent_text, screen_content):
            return prompt

        # Check for questions
        if prompt := self._check_question(recent_text, screen_content):
            return prompt

        # Check for completion (lowest priority - only if nothing else matches)
        if prompt := self._check_completed(recent_text, screen_content):
            return prompt

        return None

    def _check_permission(self, recent_text: str, full_context: str) -> Optional[DetectedPrompt]:
        """Check for permission prompts (Yes/No dialogs).

        Claude Code permission prompts look like:
        ⏺ Claude wants to run this Bash command:
          ls -la

        1. Yes, and auto-approve all Bash
        2. Yes
        3. No

        We need to be strict to avoid false positives from numbered lists in output.
        """
        # Look for the last few lines to find the actual prompt area
        lines = recent_text.strip().split('\n')
        last_lines = '\n'.join(lines[-10:])  # Focus on last 10 lines

        # STRICT CHECK: Must have numbered options with Yes/No/Allow/Reject at START of line
        # Pattern: "1. Yes" or "2. No" or "3. Reject" etc at line start
        # Note: Claude Code uses ❯ selector before active option, so we need to handle that
        # Also match "1. Allow" style prompts
        yes_no_options = re.findall(
            r'^[\s❯]*[1-3]\.\s*(Yes|No|Ja|Nej|Allow|Reject|Deny|Accept|Cancel)',
            last_lines, re.MULTILINE | re.IGNORECASE
        )

        if len(yes_no_options) >= 2:  # Need at least 2 options to be a real prompt
            # This looks like a real permission dialog
            # Also check for permission header patterns
            has_permission_header = any(p.search(last_lines) for p in self._permission_re[:2])  # First 2 patterns are headers

            # DEBUG: Log what we matched
            logger.info(f"Permission detected! Matched options: {yes_no_options}")
            logger.debug(f"Context (last 10 lines):\n{last_lines}")

            return DetectedPrompt(
                prompt_type=PromptType.PERMISSION,
                text="Permission prompt detected",
                context=last_lines,
                suggested_response="1",  # Default to approve
                confidence=0.95 if has_permission_header else 0.85,
            )

        return None

    def _check_continuation(self, recent_text: str, full_context: str) -> Optional[DetectedPrompt]:
        """Check for continuation prompts."""
        for pattern in self._continuation_re:
            if match := pattern.search(recent_text):
                return DetectedPrompt(
                    prompt_type=PromptType.CONTINUATION,
                    text=match.group(0),
                    context=recent_text,
                    suggested_response="continue",
                    confidence=0.8,
                )
        return None

    def _check_question(self, recent_text: str, full_context: str) -> Optional[DetectedPrompt]:
        """Check for open-ended questions."""
        # Don't detect questions if there's a permission dialog on screen
        # (e.g., "Type here to tell Claude what to do differently" is NOT a standalone question)
        lines = recent_text.strip().split('\n')
        last_lines = '\n'.join(lines[-15:])
        has_permission_context = bool(re.search(
            r'^[\s❯]*[1-3]\.\s*(Yes|No|Ja|Nej|Allow|Reject)',
            last_lines, re.MULTILINE | re.IGNORECASE
        ))
        if has_permission_context:
            return None  # Skip question detection in permission dialogs

        for pattern in self._question_re:
            if match := pattern.search(recent_text):
                # Don't match questions that are part of code
                for ignore in self._ignore_re:
                    if ignore.match(match.group(0)):
                        continue

                return DetectedPrompt(
                    prompt_type=PromptType.QUESTION,
                    text=match.group(0),
                    context=recent_text,
                    suggested_response=None,  # Needs smart regex to answer
                    confidence=0.6,
                )
        return None

    def _check_completed(self, recent_text: str, full_context: str) -> Optional[DetectedPrompt]:
        """Check for task completion indicators."""
        for pattern in self._completed_re:
            if match := pattern.search(recent_text):
                # Don't match if it looks like code
                for ignore in self._ignore_re:
                    if ignore.match(match.group(0)):
                        continue

                return DetectedPrompt(
                    prompt_type=PromptType.COMPLETED,
                    text=match.group(0),
                    context=recent_text,
                    suggested_response=None,  # Will use follow-up prompts
                    confidence=0.5,  # Lower confidence - needs cooldown logic
                )
        return None

    def is_same_prompt(self, prompt: DetectedPrompt) -> bool:
        """Check if this is the same prompt we already detected."""
        if self._last_detected is None:
            return False
        return (
            self._last_detected.prompt_type == prompt.prompt_type and
            self._last_detected.text == prompt.text
        )

    def mark_handled(self, prompt: DetectedPrompt):
        """Mark a prompt as handled to avoid duplicate responses."""
        self._last_detected = prompt
        self._detection_count += 1

    def reset(self):
        """Reset detection state (e.g., when screen changes significantly)."""
        self._last_detected = None


# Global instance
pattern_detector = PatternDetector()
