"""
Agent system for Claude Continue.

This module implements an intelligent agent that controls Claude Code sessions
with goals, planning, and reinforcement learning.

Architecture:
- Goal Module: Manages goals per session
- State Module: Tracks observations, actions, and phases
- Plan Module: Creates and tracks plans toward goals
- Decision Module: Multi-tier decision making (rules → UCB → LLM)
- Learning Module: UCB-based learning with experience replay
- Orchestrator: Coordinates all modules
"""

from .state_module import (
    AgentPhase,
    Observation,
    Action,
    ActionOutcome,
    SessionState,
    StateModule,
)
from .goal_module import (
    Goal,
    GoalStatus,
    GoalModule,
)
from .plan_module import (
    PlanStep,
    StepStatus,
    Plan,
    PlanModule,
)
from .decision_module import (
    Decision,
    DecisionTier,
    DecisionModule,
)
from .learning_module import (
    Experience,
    LearningModule,
)
from .orchestrator import (
    Orchestrator,
    orchestrator,
)

__all__ = [
    # State
    "AgentPhase",
    "Observation",
    "Action",
    "ActionOutcome",
    "SessionState",
    "StateModule",
    # Goals
    "Goal",
    "GoalStatus",
    "GoalModule",
    # Plans
    "PlanStep",
    "StepStatus",
    "Plan",
    "PlanModule",
    # Decisions
    "Decision",
    "DecisionTier",
    "DecisionModule",
    # Learning
    "Experience",
    "LearningModule",
    # Orchestrator
    "Orchestrator",
    "orchestrator",
]
