"""
Plan module for tracking plans toward goals.

Features:
- Create plans from goals (list of steps)
- Track current step and progress
- Support replanning when stuck
- Persistent storage
"""
import json
import time
import uuid
import logging
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Status of a plan step."""
    PENDING = "pending"          # Not started
    IN_PROGRESS = "in_progress"  # Currently executing
    COMPLETED = "completed"      # Successfully completed
    FAILED = "failed"            # Failed to complete
    SKIPPED = "skipped"          # Skipped (e.g., already done or not needed)


@dataclass
class PlanStep:
    """A single step in a plan."""
    step_id: str
    description: str
    status: StepStatus = StepStatus.PENDING
    order: int = 0               # Step order in plan

    # Timing
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Outcome
    outcome_notes: Optional[str] = None
    error_message: Optional[str] = None

    # Execution metadata
    actions_taken: int = 0       # Number of agent actions for this step
    retries: int = 0             # Number of retry attempts

    def start(self):
        """Mark step as started."""
        self.status = StepStatus.IN_PROGRESS
        self.started_at = time.time()

    def complete(self, notes: Optional[str] = None):
        """Mark step as completed."""
        self.status = StepStatus.COMPLETED
        self.completed_at = time.time()
        if notes:
            self.outcome_notes = notes

    def fail(self, error: str):
        """Mark step as failed."""
        self.status = StepStatus.FAILED
        self.completed_at = time.time()
        self.error_message = error

    def skip(self, reason: str):
        """Skip this step."""
        self.status = StepStatus.SKIPPED
        self.completed_at = time.time()
        self.outcome_notes = reason

    def retry(self):
        """Retry this step."""
        self.retries += 1
        self.status = StepStatus.IN_PROGRESS
        self.error_message = None

    @property
    def is_done(self) -> bool:
        """Check if step is finished (any terminal state)."""
        return self.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        if not self.started_at:
            return 0
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "status": self.status.value,
            "order": self.order,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "outcome_notes": self.outcome_notes,
            "error_message": self.error_message,
            "actions_taken": self.actions_taken,
            "retries": self.retries,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        """Create from dictionary."""
        return cls(
            step_id=data["step_id"],
            description=data["description"],
            status=StepStatus(data.get("status", "pending")),
            order=data.get("order", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            outcome_notes=data.get("outcome_notes"),
            error_message=data.get("error_message"),
            actions_taken=data.get("actions_taken", 0),
            retries=data.get("retries", 0),
        )


@dataclass
class Plan:
    """A plan to achieve a goal."""
    plan_id: str
    goal_id: str
    session_id: str
    steps: List[PlanStep] = field(default_factory=list)

    # Timing
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Replanning
    is_active: bool = True
    replan_count: int = 0        # How many times we've replanned
    replan_reasons: List[str] = field(default_factory=list)

    # Current execution state
    current_step_index: int = 0

    def add_step(self, description: str) -> PlanStep:
        """Add a step to the plan."""
        step = PlanStep(
            step_id=str(uuid.uuid4()),
            description=description,
            order=len(self.steps),
        )
        self.steps.append(step)
        return step

    def add_steps(self, descriptions: List[str]):
        """Add multiple steps."""
        for desc in descriptions:
            self.add_step(desc)

    def start(self):
        """Start executing the plan."""
        self.started_at = time.time()
        if self.steps:
            self.steps[0].start()
        logger.info(f"Plan {self.plan_id[:8]} started with {len(self.steps)} steps")

    def get_current_step(self) -> Optional[PlanStep]:
        """Get the current step being executed."""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def advance(self) -> Optional[PlanStep]:
        """Advance to the next step. Returns the new current step or None if done."""
        # Mark current step as completed if still in progress
        current = self.get_current_step()
        if current and current.status == StepStatus.IN_PROGRESS:
            current.complete()

        # Move to next step
        self.current_step_index += 1

        next_step = self.get_current_step()
        if next_step:
            next_step.start()
            return next_step

        # No more steps - plan completed
        self.completed_at = time.time()
        logger.info(f"Plan {self.plan_id[:8]} completed")
        return None

    def mark_step_failed(self, error: str):
        """Mark current step as failed."""
        current = self.get_current_step()
        if current:
            current.fail(error)

    def retry_current_step(self) -> bool:
        """Retry the current step. Returns False if max retries exceeded."""
        current = self.get_current_step()
        if current and current.retries < 3:  # Max 3 retries
            current.retry()
            return True
        return False

    def skip_current_step(self, reason: str):
        """Skip current step and move to next."""
        current = self.get_current_step()
        if current:
            current.skip(reason)
        self.advance()

    def invalidate(self, reason: str):
        """Invalidate this plan (for replanning)."""
        self.is_active = False
        self.replan_reasons.append(reason)
        self.completed_at = time.time()
        logger.info(f"Plan {self.plan_id[:8]} invalidated: {reason}")

    @property
    def is_done(self) -> bool:
        """Check if plan is completed."""
        return self.completed_at is not None or not self.is_active

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if not self.steps:
            return 0
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        return (completed / len(self.steps)) * 100

    @property
    def completed_steps(self) -> int:
        """Count completed steps."""
        return sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)

    @property
    def failed_steps(self) -> int:
        """Count failed steps."""
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "session_id": self.session_id,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "is_active": self.is_active,
            "replan_count": self.replan_count,
            "replan_reasons": self.replan_reasons,
            "current_step_index": self.current_step_index,
            "progress_percent": self.progress_percent,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Create from dictionary."""
        plan = cls(
            plan_id=data["plan_id"],
            goal_id=data["goal_id"],
            session_id=data["session_id"],
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            is_active=data.get("is_active", True),
            replan_count=data.get("replan_count", 0),
            replan_reasons=data.get("replan_reasons", []),
            current_step_index=data.get("current_step_index", 0),
        )
        plan.steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
        return plan


class PlanModule:
    """
    Manages plans for goals.

    Creates, tracks, and persists plans. Supports replanning when
    current plan becomes invalid.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        """Initialize with optional custom storage directory."""
        self._plans: Dict[str, Plan] = {}  # plan_id → Plan
        self._goal_plans: Dict[str, List[str]] = {}  # goal_id → [plan_ids]

        # Storage setup
        if storage_dir:
            self._storage_dir = storage_dir
        else:
            self._storage_dir = Path.home() / ".claude-continue" / "plans"

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._load_plans()

        logger.info(f"PlanModule initialized with {len(self._plans)} plans")

    def create_plan(
        self,
        goal_id: str,
        session_id: str,
        steps: Optional[List[str]] = None,
    ) -> Plan:
        """Create a new plan for a goal."""
        plan_id = str(uuid.uuid4())

        # Check for existing plans and increment replan count
        replan_count = 0
        existing_plans = self.get_goal_plans(goal_id)
        if existing_plans:
            # Invalidate existing active plans
            for existing in existing_plans:
                if existing.is_active:
                    existing.invalidate("Replaced by new plan")
                    self._save_plan(existing)
            replan_count = max(p.replan_count for p in existing_plans) + 1

        plan = Plan(
            plan_id=plan_id,
            goal_id=goal_id,
            session_id=session_id,
            replan_count=replan_count,
        )

        if steps:
            plan.add_steps(steps)

        # Store plan
        self._plans[plan_id] = plan

        # Track goal → plans mapping
        if goal_id not in self._goal_plans:
            self._goal_plans[goal_id] = []
        self._goal_plans[goal_id].append(plan_id)

        # Persist
        self._save_plan(plan)

        logger.info(f"Created plan {plan_id[:8]} for goal {goal_id[:8]} with {len(steps or [])} steps")
        return plan

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Get a plan by ID."""
        return self._plans.get(plan_id)

    def get_goal_plans(self, goal_id: str) -> List[Plan]:
        """Get all plans for a goal."""
        plan_ids = self._goal_plans.get(goal_id, [])
        return [self._plans[pid] for pid in plan_ids if pid in self._plans]

    def get_active_plan(self, goal_id: str) -> Optional[Plan]:
        """Get the active plan for a goal."""
        plans = self.get_goal_plans(goal_id)
        active = [p for p in plans if p.is_active]
        return active[0] if active else None

    def update_plan(self, plan: Plan):
        """Update and persist a plan."""
        if plan.plan_id in self._plans:
            self._plans[plan.plan_id] = plan
            self._save_plan(plan)

    def advance_plan(self, plan_id: str) -> Optional[PlanStep]:
        """Advance a plan to the next step."""
        plan = self.get_plan(plan_id)
        if plan:
            next_step = plan.advance()
            self._save_plan(plan)
            return next_step
        return None

    def replan(self, goal_id: str, session_id: str, reason: str, new_steps: List[str]) -> Plan:
        """Create a new plan replacing the current one."""
        # Invalidate current plan
        current = self.get_active_plan(goal_id)
        if current:
            current.invalidate(reason)
            self._save_plan(current)

        # Create new plan
        return self.create_plan(goal_id, session_id, new_steps)

    def remove_goal_plans(self, goal_id: str):
        """Remove all plans for a goal."""
        plan_ids = self._goal_plans.pop(goal_id, [])
        for plan_id in plan_ids:
            if plan_id in self._plans:
                del self._plans[plan_id]
        logger.info(f"Removed {len(plan_ids)} plans for goal {goal_id[:8]}")

    def _save_plan(self, plan: Plan):
        """Save a plan to storage."""
        path = self._storage_dir / f"{plan.plan_id}.json"
        try:
            with open(path, "w") as f:
                json.dump(plan.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save plan {plan.plan_id[:8]}: {e}")

    def _load_plans(self):
        """Load active plans from storage."""
        for path in self._storage_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                    plan = Plan.from_dict(data)

                    # Only load active plans
                    if plan.is_active:
                        self._plans[plan.plan_id] = plan
                        if plan.goal_id not in self._goal_plans:
                            self._goal_plans[plan.goal_id] = []
                        self._goal_plans[plan.goal_id].append(plan.plan_id)

            except Exception as e:
                logger.warning(f"Failed to load plan from {path}: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get status for web API."""
        return {
            "total_plans": len(self._plans),
            "active_plans": sum(1 for p in self._plans.values() if p.is_active),
            "plans_by_goal": {
                gid: [self._plans[pid].to_dict() for pid in pids if pid in self._plans]
                for gid, pids in self._goal_plans.items()
            },
        }


# Global instance
plan_module = PlanModule()
