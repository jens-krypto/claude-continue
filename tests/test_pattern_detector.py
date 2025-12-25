"""Tests for pattern detection."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pattern_detector import PatternDetector, PromptType


@pytest.fixture
def detector():
    return PatternDetector()


class TestPermissionDetection:
    """Test permission prompt detection."""

    def test_detects_edit_permission(self, detector):
        screen = """
        Claude wants to edit file.py

        1. Yes
        2. Yes, and don't ask again for similar commands
        3. No, and tell Claude what to do differently (esc)
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.PERMISSION
        assert prompt.suggested_response == "1"

    def test_detects_run_permission(self, detector):
        screen = """
        Claude wants to run pytest tests/

        1. Yes
        2. No
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.PERMISSION

    def test_detects_tool_permission(self, detector):
        screen = """
        Allow Bash to execute: npm install?

        1. Yes
        2. No
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.PERMISSION


class TestContinuationDetection:
    """Test continuation prompt detection."""

    def test_detects_continue_question(self, detector):
        screen = """
        The operation completed successfully.
        Would you like me to continue?
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.CONTINUATION
        assert prompt.suggested_response == "continue"

    def test_detects_shall_proceed(self, detector):
        screen = """
        All tests passed.
        Shall I proceed with the next step?
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.CONTINUATION


class TestQuestionDetection:
    """Test open-ended question detection."""

    def test_detects_what_question(self, detector):
        screen = """
        What file should I create for the tests?
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.QUESTION
        assert prompt.suggested_response is None  # Needs DeepSeek

    def test_detects_which_question(self, detector):
        screen = """
        Which option do you prefer?
        - Option A: Fast but uses more memory
        - Option B: Slower but memory efficient
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.QUESTION


class TestCompletedDetection:
    """Test COMPLETED (idle) pattern detection."""

    def test_detects_let_me_know(self, detector):
        screen = """
        I've made all the changes.
        Let me know if you need anything else!
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.COMPLETED

    def test_detects_is_there_anything_else(self, detector):
        screen = """
        The task is complete.
        Is there anything else I can help with?
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.COMPLETED

    def test_detects_all_done(self, detector):
        screen = """
        All done! The implementation is complete.
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.COMPLETED

    def test_detects_successfully(self, detector):
        screen = """
        Changes have been committed and pushed.
        Successfully!
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.COMPLETED

    def test_detects_changes_made(self, detector):
        screen = """
        I've updated the configuration file.
        The changes have been made and should work now.
        """
        prompt = detector.detect(screen)
        assert prompt is not None
        assert prompt.prompt_type == PromptType.COMPLETED


class TestNoDetection:
    """Test that normal output doesn't trigger detection."""

    def test_ignores_code_output(self, detector):
        screen = """
        import os
        import sys

        def main():
            print("Hello, world!")

        if __name__ == "__main__":
            main()
        """
        prompt = detector.detect(screen)
        # Should not detect code as a prompt
        # (may detect due to "if __name__" but that's acceptable)

    def test_ignores_log_output(self, detector):
        screen = """
        2025-01-15 10:30:45 INFO Starting server
        2025-01-15 10:30:46 INFO Server running on port 8080
        2025-01-15 10:30:47 DEBUG Handling request /api/health
        """
        prompt = detector.detect(screen)
        assert prompt is None


class TestDuplicateHandling:
    """Test that we don't respond to the same prompt twice."""

    def test_same_prompt_detection(self, detector):
        screen = """
        Claude wants to edit file.py

        1. Yes
        2. No
        """
        prompt1 = detector.detect(screen)
        assert prompt1 is not None

        # Mark as handled
        detector.mark_handled(prompt1)

        # Should detect as same prompt
        prompt2 = detector.detect(screen)
        assert prompt2 is not None
        assert detector.is_same_prompt(prompt2)
