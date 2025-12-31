"""
Orchestrator module - coordinates all agent modules.

Main entry point: process_observation()
Coordinates state, goal, plan, decision, and learning modules.
"""
import logging
from typing import Optional, Dict, Any, Tuple

from .state_module import (
    StateModule, state_module,
    AgentPhase, Observation, ActionOutcome,
)
from .goal_module import GoalModule, goal_module, Goal, GoalStatus
from .plan_module import PlanModule, plan_module, Plan
from .decision_module import DecisionModule, decision_module, Decision, DecisionTier
from .learning_module import LearningModule, learning_module

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Central coordinator for the agent system.

    Ties together all modules and provides a single entry point
    for processing observations from the session monitor.
    """

    def __init__(
        self,
        state_mod: Optional[StateModule] = None,
        goal_mod: Optional[GoalModule] = None,
        plan_mod: Optional[PlanModule] = None,
        decision_mod: Optional[DecisionModule] = None,
        learning_mod: Optional[LearningModule] = None,
    ):
        """Initialize with module instances (or use globals)."""
        self.state = state_mod or state_module
        self.goals = goal_mod or goal_module
        self.plans = plan_mod or plan_module
        self.decisions = decision_mod or decision_module
        self.learning = learning_mod or learning_module

        # Update decision module with UCB recommendations
        self._sync_ucb_recommendations()

        logger.info("Orchestrator initialized")

    async def process_observation(
        self,
        session_id: str,
        screen_content: str,
        prompt_type: Optional[str] = None,
        prompt_text: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        Process an observation and decide on action.

        This is the main entry point called by session_monitor.

        Args:
            session_id: The iTerm2 session ID
            screen_content: Current terminal screen content
            prompt_type: Detected prompt type (permission, question, etc.)
            prompt_text: Detected prompt text

        Returns:
            Tuple of (action_type, action_value) or None if no action needed
        """
        # Record observation
        observation = self.state.record_observation(
            session_id=session_id,
            screen_content=screen_content,
            prompt_type=prompt_type,
            prompt_text=prompt_text,
        )

        # Get session state
        session_state = self.state.get_state(session_id)

        # Get current goal and plan
        active_goal = self.goals.get_active_goal(session_id)
        active_plan = None
        if active_goal:
            active_plan = self.plans.get_active_plan(active_goal.goal_id)

        # If no prompt detected, just observe
        if not prompt_type:
            session_state.set_phase(AgentPhase.OBSERVING)
            return None

        # Make decision
        decision = await self.decisions.decide_async(
            prompt_type=prompt_type,
            prompt_text=prompt_text or "",
            context=screen_content,
            goal_description=active_goal.description if active_goal else None,
            is_stuck=session_state.is_stuck,
            similar_count=session_state.similar_observations_count,
        )

        # Handle special actions
        if decision.action_type == "wait":
            session_state.set_phase(AgentPhase.IDLE)
            return None

        if decision.action_type == "replan":
            await self._handle_replan(session_id, active_goal, decision)
            return None

        # Record the action
        obs_index = session_state.total_observations - 1
        action = self.state.record_action(
            session_id=session_id,
            action_type=decision.action_type,
            action_value=decision.action_value,
            observation_index=obs_index,
        )

        # Log the decision
        logger.info(
            f"Session {session_id[:8]}: {decision.tier.value} decision "
            f"'{decision.action_value}' for {prompt_type} ({decision.confidence:.0%})"
        )

        return (decision.action_type, decision.action_value)

    async def record_outcome(
        self,
        session_id: str,
        outcome: str,
        details: Optional[str] = None,
    ):
        """
        Record the outcome of the last action.

        Called by session_monitor after sending a response.

        Args:
            session_id: The session ID
            outcome: "success", "failed", or "timeout"
            details: Optional details about the outcome
        """
        session_state = self.state.get_state(session_id)
        action = session_state.latest_action
        observation = session_state.latest_observation

        # Map outcome string to enum
        outcome_enum = {
            "success": ActionOutcome.SUCCESS,
            "failed": ActionOutcome.FAILED,
            "timeout": ActionOutcome.TIMEOUT,
        }.get(outcome, ActionOutcome.FAILED)

        # Record in state module
        self.state.record_outcome(session_id, outcome_enum, details)

        # Record experience for learning
        if action and observation:
            # Get goal progress
            progress_before = 0.0
            progress_after = 0.0
            goal_id = session_state.current_goal_id

            if goal_id:
                goal = self.goals.get_goal(goal_id)
                if goal:
                    progress_after = goal.progress_percent / 100.0
                    # Estimate progress before (use completed steps ratio)
                    if goal.estimated_steps > 0:
                        progress_before = max(0, (goal.completed_steps - 1) / goal.estimated_steps)

            self.learning.record_experience(
                session_id=session_id,
                context_hash=getattr(action, 'context_hash', self.decisions._hash_context(
                    observation.prompt_type or "", observation.prompt_text or ""
                )),
                prompt_type=observation.prompt_type or "",
                prompt_text=observation.prompt_text or "",
                action_type=action.action_type,
                action_value=action.action_value,
                outcome=outcome,
                outcome_details=details,
                goal_id=goal_id,
                goal_progress_before=progress_before,
                goal_progress_after=progress_after,
            )

            # Update decision module with new recommendations
            self._sync_ucb_recommendations()

            # Update plan progress if we have an active plan
            if goal_id:
                active_plan = self.plans.get_active_plan(goal_id)
                if active_plan and outcome == "success":
                    current_step = active_plan.get_current_step()
                    if current_step:
                        current_step.actions_taken += 1

    def set_goal(
        self,
        session_id: str,
        description: str,
        success_criteria: Optional[list] = None,
        priority: int = 1,
    ) -> Goal:
        """
        Set a goal for a session.

        Args:
            session_id: The session ID
            description: Goal description
            success_criteria: Optional list of success criteria
            priority: Goal priority (1-5)

        Returns:
            The created Goal
        """
        goal = self.goals.create_goal(
            session_id=session_id,
            description=description,
            success_criteria=success_criteria,
            priority=priority,
        )

        # Update session state
        session_state = self.state.get_state(session_id)
        session_state.current_goal_id = goal.goal_id
        session_state.set_phase(AgentPhase.PLANNING)

        # Start the goal
        goal.start()

        logger.info(f"Set goal for session {session_id[:8]}: {description[:50]}")
        return goal

    def create_plan(
        self,
        goal_id: str,
        session_id: str,
        steps: list,
    ) -> Plan:
        """
        Create a plan for a goal.

        Args:
            goal_id: The goal ID
            session_id: The session ID
            steps: List of step descriptions

        Returns:
            The created Plan
        """
        plan = self.plans.create_plan(
            goal_id=goal_id,
            session_id=session_id,
            steps=steps,
        )

        # Update goal with estimated steps
        goal = self.goals.get_goal(goal_id)
        if goal:
            goal.estimated_steps = len(steps)
            self.goals.update_goal(goal)

        # Start the plan
        plan.start()

        # Update session phase
        session_state = self.state.get_state(session_id)
        session_state.set_phase(AgentPhase.EXECUTING)

        logger.info(f"Created plan with {len(steps)} steps for goal {goal_id[:8]}")
        return plan

    async def _handle_replan(
        self,
        session_id: str,
        goal: Optional[Goal],
        decision: Decision,
    ):
        """Handle a replan decision."""
        if not goal:
            logger.warning("Replan requested but no active goal")
            return

        session_state = self.state.get_state(session_id)
        session_state.set_phase(AgentPhase.PLANNING)

        # Invalidate current plan
        current_plan = self.plans.get_active_plan(goal.goal_id)
        if current_plan:
            current_plan.invalidate(decision.reason)
            self.plans.update_plan(current_plan)

        goal.add_progress(f"Replanning: {decision.reason}")
        self.goals.update_goal(goal)

        logger.info(f"Session {session_id[:8]}: Replanning - {decision.reason}")

    def _sync_ucb_recommendations(self):
        """Sync UCB recommendations from learning to decision module."""
        recommendations = self.learning.get_all_recommendations()
        self.decisions.set_ucb_recommendations(recommendations)

    def complete_current_step(self, session_id: str, notes: Optional[str] = None):
        """Mark the current plan step as completed."""
        session_state = self.state.get_state(session_id)
        goal_id = session_state.current_goal_id

        if not goal_id:
            return

        goal = self.goals.get_goal(goal_id)
        plan = self.plans.get_active_plan(goal_id)

        if not plan:
            return

        # Advance plan
        next_step = plan.advance()
        self.plans.update_plan(plan)

        # Update goal progress
        if goal:
            goal.completed_steps = plan.completed_steps
            goal.add_progress(notes or f"Completed step {plan.current_step_index}")
            self.goals.update_goal(goal)

        # Check if plan is complete
        if plan.is_done and goal:
            if plan.failed_steps == 0:
                goal.complete("All plan steps completed")
                session_state.set_phase(AgentPhase.COMPLETED)
            else:
                goal.add_progress(f"Plan finished with {plan.failed_steps} failed steps")

            self.goals.update_goal(goal)

    def remove_session(self, session_id: str):
        """Clean up when a session is closed."""
        # Don't remove goals/plans - they persist
        self.state.remove_session(session_id)
        logger.info(f"Cleaned up session {session_id[:8]}")

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get full status for a session."""
        session_state = self.state.get_state(session_id)
        goal = self.goals.get_active_goal(session_id)
        plan = None
        if goal:
            plan = self.plans.get_active_plan(goal.goal_id)

        return {
            "state": session_state.to_dict(),
            "goal": goal.to_dict() if goal else None,
            "plan": plan.to_dict() if plan else None,
        }

    def get_full_status(self) -> Dict[str, Any]:
        """Get full agent system status."""
        return {
            "state": self.state.get_status(),
            "goals": self.goals.get_status(),
            "plans": self.plans.get_status(),
            "learning": self.learning.get_status(),
        }


# Global instance
orchestrator = Orchestrator()
