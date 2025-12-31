"""
State module for tracking agent observations, actions, and phases.

Maintains the current state of each session including:
- Observations (screen content snapshots)
- Actions taken and their outcomes
- Current phase in the agent lifecycle
- Progress metrics
"""
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from collections import deque

logger = logging.getLogger(__name__)


class AgentPhase(Enum):
    """Agent lifecycle phases."""
    IDLE = "idle"                    # No active goal, waiting for user
    OBSERVING = "observing"          # Watching screen, gathering info
    PLANNING = "planning"            # Creating/updating plan
    EXECUTING = "executing"          # Sending response/taking action
    WAITING = "waiting"              # Waiting for Claude Code to respond
    COMPLETED = "completed"          # Goal achieved
    STUCK = "stuck"                  # Unable to progress, needs help


@dataclass
class Observation:
    """A single observation of the screen state."""
    timestamp: float
    screen_content: str
    prompt_type: Optional[str]       # From PromptType enum
    prompt_text: Optional[str]       # Detected prompt text
    session_id: str

    # Computed features for learning
    has_error: bool = False
    has_permission: bool = False
    has_question: bool = False
    line_count: int = 0

    def __post_init__(self):
        """Compute derived features."""
        if self.screen_content:
            self.line_count = len(self.screen_content.split('\n'))
            self.has_error = any(kw in self.screen_content.lower()
                                for kw in ['error', 'failed', 'exception', 'traceback'])
        if self.prompt_type:
            self.has_permission = self.prompt_type == "permission"
            self.has_question = self.prompt_type == "question"


class ActionOutcome(Enum):
    """Possible outcomes of an action."""
    SUCCESS = "success"              # Action completed successfully
    FAILED = "failed"                # Action failed (error, rejected)
    PENDING = "pending"              # Waiting for result
    TIMEOUT = "timeout"              # No response within expected time
    SKIPPED = "skipped"              # Action was skipped


@dataclass
class Action:
    """An action taken by the agent."""
    timestamp: float
    action_type: str                 # "approve", "deny", "respond", "continue", etc.
    action_value: str                # The actual response/input sent
    observation_id: int              # Index of triggering observation
    session_id: str

    # Outcome tracking
    outcome: ActionOutcome = ActionOutcome.PENDING
    outcome_timestamp: Optional[float] = None
    outcome_details: Optional[str] = None

    def mark_outcome(self, outcome: ActionOutcome, details: Optional[str] = None):
        """Record the outcome of this action."""
        self.outcome = outcome
        self.outcome_timestamp = time.time()
        self.outcome_details = details


@dataclass
class SessionState:
    """Complete state for a single session."""
    session_id: str
    phase: AgentPhase = AgentPhase.IDLE
    phase_changed_at: float = field(default_factory=time.time)

    # History (limited size for memory efficiency)
    observations: deque = field(default_factory=lambda: deque(maxlen=100))
    actions: deque = field(default_factory=lambda: deque(maxlen=100))

    # Progress metrics
    total_observations: int = 0
    total_actions: int = 0
    successful_actions: int = 0
    failed_actions: int = 0

    # Stuck detection
    similar_observations_count: int = 0
    last_progress_at: float = field(default_factory=time.time)

    # Goal reference (set by GoalModule)
    current_goal_id: Optional[str] = None

    def add_observation(self, obs: Observation) -> int:
        """Add an observation and return its index."""
        self.observations.append(obs)
        self.total_observations += 1
        return self.total_observations - 1

    def add_action(self, action: Action):
        """Add an action to history."""
        self.actions.append(action)
        self.total_actions += 1

    def record_action_outcome(self, outcome: ActionOutcome):
        """Update metrics based on action outcome."""
        if outcome == ActionOutcome.SUCCESS:
            self.successful_actions += 1
            self.last_progress_at = time.time()
            self.similar_observations_count = 0
        elif outcome == ActionOutcome.FAILED:
            self.failed_actions += 1

    def set_phase(self, phase: AgentPhase):
        """Transition to a new phase."""
        if phase != self.phase:
            logger.debug(f"Session {self.session_id[:8]}: {self.phase.value} → {phase.value}")
            self.phase = phase
            self.phase_changed_at = time.time()

    @property
    def success_rate(self) -> float:
        """Calculate success rate of actions."""
        total = self.successful_actions + self.failed_actions
        if total == 0:
            return 1.0  # No actions yet = perfect
        return self.successful_actions / total

    @property
    def is_stuck(self) -> bool:
        """Detect if session appears stuck."""
        # Stuck if 3+ similar observations without progress
        if self.similar_observations_count >= 3:
            return True
        # Stuck if no progress for 5+ minutes
        if time.time() - self.last_progress_at > 300:
            return True
        return False

    @property
    def latest_observation(self) -> Optional[Observation]:
        """Get the most recent observation."""
        return self.observations[-1] if self.observations else None

    @property
    def latest_action(self) -> Optional[Action]:
        """Get the most recent action."""
        return self.actions[-1] if self.actions else None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for web API."""
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "phase_changed_at": self.phase_changed_at,
            "total_observations": self.total_observations,
            "total_actions": self.total_actions,
            "successful_actions": self.successful_actions,
            "failed_actions": self.failed_actions,
            "success_rate": self.success_rate,
            "is_stuck": self.is_stuck,
            "current_goal_id": self.current_goal_id,
            "seconds_since_progress": time.time() - self.last_progress_at,
        }


class StateModule:
    """
    Manages state for all monitored sessions.

    Thread-safe singleton that maintains SessionState objects
    for each active session.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        logger.info("StateModule initialized")

    def get_state(self, session_id: str) -> SessionState:
        """Get or create state for a session."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
            logger.info(f"Created state for session {session_id[:8]}")
        return self._sessions[session_id]

    def record_observation(
        self,
        session_id: str,
        screen_content: str,
        prompt_type: Optional[str] = None,
        prompt_text: Optional[str] = None,
    ) -> Observation:
        """Record an observation for a session."""
        state = self.get_state(session_id)

        obs = Observation(
            timestamp=time.time(),
            screen_content=screen_content,
            prompt_type=prompt_type,
            prompt_text=prompt_text,
            session_id=session_id,
        )

        # Check for similar observations (stuck detection)
        if state.latest_observation:
            if self._is_similar(obs, state.latest_observation):
                state.similar_observations_count += 1
            else:
                state.similar_observations_count = 0

        state.add_observation(obs)

        # Update phase based on observation
        if prompt_type:
            state.set_phase(AgentPhase.OBSERVING)

        return obs

    def record_action(
        self,
        session_id: str,
        action_type: str,
        action_value: str,
        observation_index: int,
    ) -> Action:
        """Record an action taken for a session."""
        state = self.get_state(session_id)

        action = Action(
            timestamp=time.time(),
            action_type=action_type,
            action_value=action_value,
            observation_id=observation_index,
            session_id=session_id,
        )

        state.add_action(action)
        state.set_phase(AgentPhase.WAITING)

        return action

    def record_outcome(
        self,
        session_id: str,
        outcome: ActionOutcome,
        details: Optional[str] = None,
    ):
        """Record the outcome of the most recent action."""
        state = self.get_state(session_id)

        if state.latest_action:
            state.latest_action.mark_outcome(outcome, details)
            state.record_action_outcome(outcome)

            if outcome == ActionOutcome.SUCCESS:
                state.set_phase(AgentPhase.OBSERVING)
            elif outcome == ActionOutcome.FAILED:
                state.set_phase(AgentPhase.STUCK if state.is_stuck else AgentPhase.OBSERVING)

    def set_phase(self, session_id: str, phase: AgentPhase):
        """Manually set the phase for a session."""
        state = self.get_state(session_id)
        state.set_phase(phase)

    def remove_session(self, session_id: str):
        """Remove state for a closed session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Removed state for session {session_id[:8]}")

    def get_all_states(self) -> Dict[str, SessionState]:
        """Get all session states."""
        return self._sessions.copy()

    def _is_similar(self, obs1: Observation, obs2: Observation) -> bool:
        """Check if two observations are similar (for stuck detection)."""
        # Same prompt type and similar content
        if obs1.prompt_type != obs2.prompt_type:
            return False

        # Compare line counts (rough similarity)
        if abs(obs1.line_count - obs2.line_count) > 5:
            return False

        # Compare last few lines (most relevant part)
        lines1 = obs1.screen_content.strip().split('\n')[-5:]
        lines2 = obs2.screen_content.strip().split('\n')[-5:]

        return lines1 == lines2

    def get_status(self) -> Dict[str, Any]:
        """Get status for web API."""
        return {
            "active_sessions": len(self._sessions),
            "sessions": {
                sid: state.to_dict()
                for sid, state in self._sessions.items()
            },
        }


# Global instance
state_module = StateModule()
