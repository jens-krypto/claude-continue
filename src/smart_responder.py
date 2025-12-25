"""
Smart regex-based responder for Claude Code prompts.
Used when DeepSeek is disabled - makes intelligent decisions using patterns.
"""
import re
import logging
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SmartResponse:
    """A response with confidence and reasoning."""
    response: str
    confidence: float  # 0.0 to 1.0
    reason: str


class SmartResponder:
    """
    Makes intelligent decisions about Claude Code prompts using regex patterns.
    No external API calls - pure pattern matching.
    """

    # =========================================================================
    # FILE OPERATION PATTERNS - Almost always safe to approve
    # =========================================================================
    SAFE_FILE_PATTERNS = [
        # Read operations
        (r"read\s+", "read operation"),
        (r"Read\s+file", "file read"),
        (r"cat\s+", "cat file"),
        (r"view\s+", "view file"),
        (r"show\s+", "show file"),

        # Edit operations on code files
        (r"edit\s+.*\.(py|js|ts|tsx|jsx|go|rs|java|c|cpp|h|hpp|rb|php|swift|kt)$", "code file edit"),
        (r"Edit\s+.*\.(py|js|ts|tsx|jsx|go|rs|java|c|cpp|h|hpp|rb|php|swift|kt)$", "code file edit"),

        # Common safe edits
        (r"edit\s+.*\.(md|txt|json|yaml|yml|toml|ini|cfg|conf)$", "config/doc edit"),
        (r"edit\s+.*\.(css|scss|less|html|xml|svg)$", "web file edit"),

        # Git operations
        (r"git\s+(status|diff|log|branch|show|fetch)", "safe git read"),
        (r"git\s+add", "git add"),

        # Safe shell commands
        (r"(ls|pwd|echo|cat|head|tail|wc|grep|find|which|type|file)\s", "safe shell command"),
        (r"npm\s+(list|ls|outdated|audit)", "npm read"),
        (r"pip\s+(list|show|freeze)", "pip read"),
        (r"python\s+-m\s+pytest", "run tests"),
        (r"pytest\s+", "run tests"),
        (r"npm\s+(test|run\s+test)", "run tests"),
        (r"make\s+test", "run tests"),
    ]

    # =========================================================================
    # CAUTION PATTERNS - Approve but note the risk
    # =========================================================================
    CAUTION_PATTERNS = [
        (r"git\s+(commit|push|pull|merge|rebase)", "git write operation"),
        (r"npm\s+(install|update|uninstall)", "npm package operation"),
        (r"pip\s+(install|uninstall)", "pip package operation"),
        (r"write\s+", "file write"),
        (r"create\s+", "file create"),
        (r"mkdir\s+", "create directory"),
    ]

    # =========================================================================
    # DANGEROUS PATTERNS - Deny or ask for confirmation
    # =========================================================================
    DANGEROUS_PATTERNS = [
        (r"rm\s+-rf\s+/", "recursive delete from root"),
        (r"rm\s+-rf\s+~", "recursive delete from home"),
        (r"rm\s+-rf\s+\*", "recursive delete wildcard"),
        (r"delete\s+.*\.env", "delete env file"),
        (r"edit\s+.*\.env", "edit env file"),
        (r">\s*/dev/", "redirect to device"),
        (r"chmod\s+777", "insecure permissions"),
        (r"curl.*\|\s*(bash|sh)", "pipe curl to shell"),
        (r"eval\s*\(", "eval execution"),
        (r"sudo\s+rm", "sudo delete"),
        (r"DROP\s+TABLE", "SQL drop table"),
        (r"DELETE\s+FROM.*WHERE\s+1", "SQL delete all"),
        (r"format\s+", "format operation"),
    ]

    # =========================================================================
    # QUESTION RESPONSE PATTERNS - Regex-based answers
    # =========================================================================
    QUESTION_RESPONSES = [
        # File naming questions
        (r"what.*file.*name|name.*file|filename",
         "Use a descriptive name following the project's naming convention", 0.7),
        (r"what.*should.*call|what.*name.*should",
         "Use a descriptive name that reflects its purpose", 0.6),

        # Location questions
        (r"where.*should.*(put|place|create|add)",
         "Follow the existing project structure", 0.6),
        (r"which.*directory|which.*folder",
         "Use the most appropriate existing directory for this type of file", 0.6),

        # Choice questions
        (r"which.*option|which.*one|which.*prefer",
         "1", 0.5),  # Default to first option
        (r"option\s*[aA1].*or.*option\s*[bB2]",
         "Option A", 0.5),

        # Yes/No questions (default to yes for most dev tasks)
        (r"do you want.*continue|shall.*continue|should.*continue",
         "yes", 0.8),
        (r"do you want.*proceed|shall.*proceed|should.*proceed",
         "yes", 0.8),
        (r"is.*okay|is.*ok|is.*fine|is.*correct",
         "yes", 0.7),
        (r"do you want.*install|should.*install",
         "yes", 0.7),
        (r"do you want.*create|should.*create",
         "yes", 0.8),
        (r"do you want.*add|should.*add",
         "yes", 0.8),
        (r"do you want.*update|should.*update",
         "yes", 0.7),
        (r"do you want.*run|should.*run",
         "yes", 0.7),

        # Format questions
        (r"what.*format|which.*format",
         "Use the standard format for this project", 0.5),

        # Implementation questions
        (r"how.*should.*(implement|do|handle|approach)",
         "Use the simplest approach that follows existing patterns in the codebase", 0.5),

        # Default/fallback
        (r"what.*should|how.*should|which.*should",
         "Use your best judgment based on the project context", 0.4),
    ]

    # =========================================================================
    # CONTINUATION TRIGGERS
    # =========================================================================
    CONTINUATION_TRIGGERS = [
        r"would you like me to continue",
        r"shall i (continue|proceed|go on)",
        r"do you want me to continue",
        r"ready to (continue|proceed)",
        r"continue\?",
        r"proceed\?",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile all patterns for performance."""
        self._safe_re = [(re.compile(p, re.IGNORECASE), r) for p, r in self.SAFE_FILE_PATTERNS]
        self._caution_re = [(re.compile(p, re.IGNORECASE), r) for p, r in self.CAUTION_PATTERNS]
        self._danger_re = [(re.compile(p, re.IGNORECASE), r) for p, r in self.DANGEROUS_PATTERNS]
        self._question_re = [(re.compile(p, re.IGNORECASE), resp, conf)
                             for p, resp, conf in self.QUESTION_RESPONSES]
        self._continue_re = [re.compile(p, re.IGNORECASE) for p in self.CONTINUATION_TRIGGERS]

    def should_approve_action(self, action_text: str) -> Tuple[bool, float, str]:
        """
        Determine if an action should be approved.

        Returns:
            Tuple of (should_approve, confidence, reason)
        """
        action_lower = action_text.lower()

        # Check dangerous patterns first
        for pattern, reason in self._danger_re:
            if pattern.search(action_text):
                logger.warning(f"Dangerous action detected: {reason}")
                return False, 0.95, f"Dangerous: {reason}"

        # Check safe patterns
        for pattern, reason in self._safe_re:
            if pattern.search(action_text):
                return True, 0.9, f"Safe: {reason}"

        # Check caution patterns
        for pattern, reason in self._caution_re:
            if pattern.search(action_text):
                return True, 0.7, f"Caution: {reason}"

        # Default: approve with lower confidence
        return True, 0.5, "Default: no specific pattern matched"

    def answer_question(self, question: str, context: str = "") -> SmartResponse:
        """
        Generate an answer to a question using pattern matching.

        Args:
            question: The question text
            context: Additional context from terminal

        Returns:
            SmartResponse with answer, confidence, and reasoning
        """
        full_text = f"{context}\n{question}".lower()

        # Check for continuation triggers first
        for pattern in self._continue_re:
            if pattern.search(full_text):
                return SmartResponse(
                    response="continue",
                    confidence=0.9,
                    reason="Continuation prompt detected"
                )

        # Try to match question patterns
        for pattern, response, confidence in self._question_re:
            if pattern.search(full_text):
                return SmartResponse(
                    response=response,
                    confidence=confidence,
                    reason=f"Matched pattern: {pattern.pattern[:50]}"
                )

        # Fallback: generic continue/yes response
        return SmartResponse(
            response="yes",
            confidence=0.3,
            reason="Fallback: no specific pattern matched"
        )

    def get_response(self, prompt_text: str, context: str = "") -> str:
        """
        Get a response for any prompt type.
        Simplified interface that returns just the response string.
        """
        # Check if it looks like a permission prompt
        if any(kw in prompt_text.lower() for kw in ['wants to', 'allow', 'approve', 'permission']):
            approved, confidence, reason = self.should_approve_action(prompt_text)
            logger.debug(f"Permission decision: {approved} ({confidence:.0%}) - {reason}")
            return "1" if approved else "2"

        # Otherwise treat as question
        response = self.answer_question(prompt_text, context)
        logger.debug(f"Question response: {response.response} ({response.confidence:.0%}) - {response.reason}")
        return response.response


# Global instance
smart_responder = SmartResponder()
