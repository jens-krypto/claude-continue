"""
Goal module for managing goals per session.

Features:
- Store goals per session (session_id → Goal)
- Hierarchical goals (primary + subgoals)
- Success criteria tracking
- Persistent storage (~/.claude-continue/goals/)
"""
import json
import time
import uuid
import logging
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class GoalStatus(Enum):
    """Goal status states."""
    PENDING = "pending"          # Goal set but not started
    ACTIVE = "active"            # Currently working toward goal
    COMPLETED = "completed"      # Goal achieved
    FAILED = "failed"            # Goal abandoned or failed
    PAUSED = "paused"            # Goal temporarily paused


@dataclass
class Goal:
    """A goal for an agent to pursue."""
    goal_id: str
    session_id: str
    description: str             # Human-readable goal description
    status: GoalStatus = GoalStatus.PENDING

    # Timestamps
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Hierarchical goals
    parent_id: Optional[str] = None      # Parent goal (if this is a subgoal)
    subgoal_ids: List[str] = field(default_factory=list)

    # Success criteria
    success_criteria: List[str] = field(default_factory=list)
    criteria_met: List[bool] = field(default_factory=list)

    # Progress tracking
    progress_notes: List[str] = field(default_factory=list)
    estimated_steps: int = 0
    completed_steps: int = 0

    # Metadata
    tags: List[str] = field(default_factory=list)
    priority: int = 1            # 1 (low) to 5 (critical)

    def __post_init__(self):
        """Initialize criteria_met list."""
        if self.success_criteria and not self.criteria_met:
            self.criteria_met = [False] * len(self.success_criteria)

    def start(self):
        """Mark goal as started."""
        self.status = GoalStatus.ACTIVE
        self.started_at = time.time()
        logger.info(f"Goal {self.goal_id[:8]} started: {self.description[:50]}")

    def complete(self, notes: Optional[str] = None):
        """Mark goal as completed."""
        self.status = GoalStatus.COMPLETED
        self.completed_at = time.time()
        if notes:
            self.progress_notes.append(f"[COMPLETED] {notes}")
        logger.info(f"Goal {self.goal_id[:8]} completed: {self.description[:50]}")

    def fail(self, reason: str):
        """Mark goal as failed."""
        self.status = GoalStatus.FAILED
        self.completed_at = time.time()
        self.progress_notes.append(f"[FAILED] {reason}")
        logger.warning(f"Goal {self.goal_id[:8]} failed: {reason}")

    def pause(self, reason: Optional[str] = None):
        """Pause the goal."""
        self.status = GoalStatus.PAUSED
        if reason:
            self.progress_notes.append(f"[PAUSED] {reason}")

    def resume(self):
        """Resume a paused goal."""
        if self.status == GoalStatus.PAUSED:
            self.status = GoalStatus.ACTIVE
            self.progress_notes.append("[RESUMED]")

    def add_progress(self, note: str):
        """Add a progress note."""
        self.progress_notes.append(f"[{time.strftime('%H:%M')}] {note}")

    def mark_criterion(self, index: int, met: bool = True):
        """Mark a success criterion as met/unmet."""
        if 0 <= index < len(self.criteria_met):
            self.criteria_met[index] = met

    def add_subgoal_id(self, subgoal_id: str):
        """Add a subgoal reference."""
        if subgoal_id not in self.subgoal_ids:
            self.subgoal_ids.append(subgoal_id)

    @property
    def is_active(self) -> bool:
        """Check if goal is active."""
        return self.status == GoalStatus.ACTIVE

    @property
    def is_done(self) -> bool:
        """Check if goal is completed or failed."""
        return self.status in (GoalStatus.COMPLETED, GoalStatus.FAILED)

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        # Based on success criteria
        if self.criteria_met:
            criteria_progress = sum(self.criteria_met) / len(self.criteria_met)
        else:
            criteria_progress = 0

        # Based on steps
        if self.estimated_steps > 0:
            step_progress = min(1.0, self.completed_steps / self.estimated_steps)
        else:
            step_progress = 0

        # Average both if we have both
        if self.criteria_met and self.estimated_steps > 0:
            return (criteria_progress + step_progress) / 2 * 100
        elif self.criteria_met:
            return criteria_progress * 100
        elif self.estimated_steps > 0:
            return step_progress * 100
        else:
            return 0

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        if not self.started_at:
            return 0
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "goal_id": self.goal_id,
            "session_id": self.session_id,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "parent_id": self.parent_id,
            "subgoal_ids": self.subgoal_ids,
            "success_criteria": self.success_criteria,
            "criteria_met": self.criteria_met,
            "progress_notes": self.progress_notes,
            "estimated_steps": self.estimated_steps,
            "completed_steps": self.completed_steps,
            "tags": self.tags,
            "priority": self.priority,
            "progress_percent": self.progress_percent,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        """Create Goal from dictionary."""
        # Handle status enum
        status = GoalStatus(data.get("status", "pending"))

        return cls(
            goal_id=data["goal_id"],
            session_id=data["session_id"],
            description=data["description"],
            status=status,
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            parent_id=data.get("parent_id"),
            subgoal_ids=data.get("subgoal_ids", []),
            success_criteria=data.get("success_criteria", []),
            criteria_met=data.get("criteria_met", []),
            progress_notes=data.get("progress_notes", []),
            estimated_steps=data.get("estimated_steps", 0),
            completed_steps=data.get("completed_steps", 0),
            tags=data.get("tags", []),
            priority=data.get("priority", 1),
        )


class GoalModule:
    """
    Manages goals for all sessions.

    Provides goal storage, persistence, and hierarchical goal management.
    Goals persist across daemon restarts via JSON storage.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        """Initialize with optional custom storage directory."""
        self._goals: Dict[str, Goal] = {}  # goal_id → Goal
        self._session_goals: Dict[str, List[str]] = {}  # session_id → [goal_ids]

        # Storage setup
        if storage_dir:
            self._storage_dir = storage_dir
        else:
            self._storage_dir = Path.home() / ".claude-continue" / "goals"

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._load_goals()

        logger.info(f"GoalModule initialized with {len(self._goals)} goals")

    def create_goal(
        self,
        session_id: str,
        description: str,
        success_criteria: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        priority: int = 1,
        tags: Optional[List[str]] = None,
    ) -> Goal:
        """Create a new goal for a session."""
        goal_id = str(uuid.uuid4())

        goal = Goal(
            goal_id=goal_id,
            session_id=session_id,
            description=description,
            success_criteria=success_criteria or [],
            parent_id=parent_id,
            priority=priority,
            tags=tags or [],
        )

        # Store goal
        self._goals[goal_id] = goal

        # Track session → goals mapping
        if session_id not in self._session_goals:
            self._session_goals[session_id] = []
        self._session_goals[session_id].append(goal_id)

        # Link to parent if subgoal
        if parent_id and parent_id in self._goals:
            self._goals[parent_id].add_subgoal_id(goal_id)

        # Persist
        self._save_goal(goal)

        logger.info(f"Created goal {goal_id[:8]} for session {session_id[:8]}: {description[:50]}")
        return goal

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Get a goal by ID."""
        return self._goals.get(goal_id)

    def get_session_goals(self, session_id: str) -> List[Goal]:
        """Get all goals for a session."""
        goal_ids = self._session_goals.get(session_id, [])
        return [self._goals[gid] for gid in goal_ids if gid in self._goals]

    def get_active_goal(self, session_id: str) -> Optional[Goal]:
        """Get the currently active goal for a session."""
        goals = self.get_session_goals(session_id)
        active = [g for g in goals if g.is_active]

        # Return highest priority active goal
        if active:
            return max(active, key=lambda g: g.priority)
        return None

    def update_goal(self, goal: Goal):
        """Update and persist a goal."""
        if goal.goal_id in self._goals:
            self._goals[goal.goal_id] = goal
            self._save_goal(goal)

    def complete_goal(self, goal_id: str, notes: Optional[str] = None):
        """Mark a goal as completed."""
        goal = self.get_goal(goal_id)
        if goal:
            goal.complete(notes)
            self._save_goal(goal)

    def fail_goal(self, goal_id: str, reason: str):
        """Mark a goal as failed."""
        goal = self.get_goal(goal_id)
        if goal:
            goal.fail(reason)
            self._save_goal(goal)

    def remove_session_goals(self, session_id: str):
        """Remove all goals for a session."""
        goal_ids = self._session_goals.pop(session_id, [])
        for goal_id in goal_ids:
            if goal_id in self._goals:
                # Don't delete from storage, just from memory
                del self._goals[goal_id]
        logger.info(f"Removed {len(goal_ids)} goals for session {session_id[:8]}")

    def get_all_goals(self) -> List[Goal]:
        """Get all goals."""
        return list(self._goals.values())

    def _save_goal(self, goal: Goal):
        """Save a goal to storage."""
        path = self._storage_dir / f"{goal.goal_id}.json"
        try:
            with open(path, "w") as f:
                json.dump(goal.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save goal {goal.goal_id[:8]}: {e}")

    def _load_goals(self):
        """Load goals from storage."""
        for path in self._storage_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                    goal = Goal.from_dict(data)

                    # Only load non-completed goals (keep history small)
                    if not goal.is_done:
                        self._goals[goal.goal_id] = goal
                        if goal.session_id not in self._session_goals:
                            self._session_goals[goal.session_id] = []
                        self._session_goals[goal.session_id].append(goal.goal_id)

            except Exception as e:
                logger.warning(f"Failed to load goal from {path}: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get status for web API."""
        return {
            "total_goals": len(self._goals),
            "active_goals": sum(1 for g in self._goals.values() if g.is_active),
            "goals_by_session": {
                sid: [self._goals[gid].to_dict() for gid in gids if gid in self._goals]
                for sid, gids in self._session_goals.items()
            },
        }


# Global instance
goal_module = GoalModule()
