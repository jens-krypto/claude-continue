"""
Pytest configuration and shared fixtures for claude-continue tests.
"""
import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_session_id():
    """Generate a mock session ID."""
    return "TEST-SESSION-12345678"


@pytest.fixture
def mock_screen_content():
    """Sample terminal screen content."""
    return """
Claude wants to run this Bash command:
  ls -la

1. Yes, and auto-approve all Bash
2. Yes
3. No
"""


@pytest.fixture
def mock_permission_prompt():
    """Sample permission prompt detection result."""
    return {
        "prompt_type": "permission",
        "prompt_text": "Permission: yes,yes",
        "context": "Claude wants to run ls -la",
    }


@pytest.fixture
def mock_question_prompt():
    """Sample question prompt detection result."""
    return {
        "prompt_type": "question",
        "prompt_text": "What file name should I use?",
        "context": "Creating a new configuration file",
    }


@pytest.fixture
def mock_deepseek_client():
    """Mock DeepSeek client that doesn't make real API calls."""
    with patch('src.deepseek_client.deepseek_client') as mock:
        mock.is_available = True
        mock.can_call = True

        # Mock API responses
        async def mock_call_api(prompt):
            return '{"action_type": "approve", "action_value": "1", "confidence": 0.9, "reason": "Mock decision"}'

        async def mock_answer_question(question, context=""):
            return "Mock answer from DeepSeek"

        async def mock_generate_followup(context):
            return "[AUTO] Mock follow-up prompt"

        mock._call_api = AsyncMock(side_effect=mock_call_api)
        mock.answer_question = AsyncMock(side_effect=mock_answer_question)
        mock.generate_followup = AsyncMock(side_effect=mock_generate_followup)

        mock.get_status.return_value = {
            "enabled": True,
            "remaining_calls": 5,
            "max_calls_per_hour": 5,
        }

        yield mock


@pytest.fixture
def mock_iterm_session():
    """Mock iTerm2 session object."""
    session = MagicMock()
    session.session_id = "MOCK-ITERM-SESSION-1234"

    async def mock_async_get_screen():
        mock_screen = MagicMock()
        mock_screen.contents = "Sample terminal content"
        return mock_screen

    session.async_get_screen_contents = AsyncMock(side_effect=mock_async_get_screen)

    async def mock_send_text(text):
        pass

    session.async_send_text = AsyncMock(side_effect=mock_send_text)

    return session


# ============================================================
# Agent module fixtures
# ============================================================

@pytest.fixture
def state_module(temp_dir):
    """Create a StateModule with temporary storage."""
    from src.agent.state_module import StateModule
    return StateModule()


@pytest.fixture
def goal_module(temp_dir):
    """Create a GoalModule with temporary storage."""
    from src.agent.goal_module import GoalModule
    return GoalModule(storage_dir=temp_dir / "goals")


@pytest.fixture
def plan_module(temp_dir):
    """Create a PlanModule with temporary storage."""
    from src.agent.plan_module import PlanModule
    return PlanModule(storage_dir=temp_dir / "plans")


@pytest.fixture
def learning_module(temp_dir):
    """Create a LearningModule with temporary storage."""
    from src.agent.learning_module import LearningModule
    return LearningModule(storage_dir=temp_dir / "learning")


@pytest.fixture
def decision_module():
    """Create a DecisionModule."""
    from src.agent.decision_module import DecisionModule
    return DecisionModule()


@pytest.fixture
def orchestrator(temp_dir, mock_deepseek_client):
    """Create an Orchestrator with temporary storage and mocked DeepSeek."""
    from src.agent.orchestrator import Orchestrator
    from src.agent.state_module import StateModule
    from src.agent.goal_module import GoalModule
    from src.agent.plan_module import PlanModule
    from src.agent.decision_module import DecisionModule
    from src.agent.learning_module import LearningModule

    return Orchestrator(
        state_mod=StateModule(),
        goal_mod=GoalModule(storage_dir=temp_dir / "goals"),
        plan_mod=PlanModule(storage_dir=temp_dir / "plans"),
        decision_mod=DecisionModule(),
        learning_mod=LearningModule(storage_dir=temp_dir / "learning"),
    )


# ============================================================
# Sample data fixtures
# ============================================================

@pytest.fixture
def sample_goal_data():
    """Sample goal data for testing."""
    return {
        "description": "Implement a new feature for user authentication",
        "success_criteria": [
            "Login form created",
            "API endpoint implemented",
            "Tests passing",
        ],
        "priority": 3,
        "tags": ["feature", "auth"],
    }


@pytest.fixture
def sample_plan_steps():
    """Sample plan steps for testing."""
    return [
        "Create login form component",
        "Implement API endpoint for authentication",
        "Add session management",
        "Write unit tests",
        "Run integration tests",
    ]


@pytest.fixture
def sample_experiences():
    """Sample experiences for learning module testing."""
    return [
        {
            "session_id": "test-session-1",
            "context_hash": "abc123",
            "prompt_type": "permission",
            "prompt_text": "Allow edit?",
            "action_type": "approve",
            "action_value": "1",
            "outcome": "success",
        },
        {
            "session_id": "test-session-1",
            "context_hash": "abc123",
            "prompt_type": "permission",
            "prompt_text": "Allow edit?",
            "action_type": "approve",
            "action_value": "1",
            "outcome": "success",
        },
        {
            "session_id": "test-session-1",
            "context_hash": "abc123",
            "prompt_type": "permission",
            "prompt_text": "Allow edit?",
            "action_type": "deny",
            "action_value": "2",
            "outcome": "failed",
        },
    ]
