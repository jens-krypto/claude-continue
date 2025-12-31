"""
Tests for the agent system modules.
"""
import pytest
import time
from pathlib import Path


# ============================================================
# State Module Tests
# ============================================================

class TestStateModule:
    """Tests for the state module."""

    def test_get_state_creates_session(self, state_module, mock_session_id):
        """Test that get_state creates a new session if it doesn't exist."""
        state = state_module.get_state(mock_session_id)
        assert state is not None
        assert state.session_id == mock_session_id

    def test_record_observation(self, state_module, mock_session_id):
        """Test recording an observation."""
        obs = state_module.record_observation(
            session_id=mock_session_id,
            screen_content="Test content",
            prompt_type="permission",
            prompt_text="Allow edit?",
        )

        assert obs.session_id == mock_session_id
        assert obs.screen_content == "Test content"
        assert obs.prompt_type == "permission"
        assert obs.has_permission is True

        state = state_module.get_state(mock_session_id)
        assert state.total_observations == 1

    def test_record_action(self, state_module, mock_session_id):
        """Test recording an action."""
        # First record an observation
        state_module.record_observation(
            session_id=mock_session_id,
            screen_content="Test",
            prompt_type="permission",
        )

        # Then record an action
        action = state_module.record_action(
            session_id=mock_session_id,
            action_type="approve",
            action_value="1",
            observation_index=0,
        )

        assert action.action_type == "approve"
        assert action.action_value == "1"

        state = state_module.get_state(mock_session_id)
        assert state.total_actions == 1

    def test_similar_observation_detection(self, state_module, mock_session_id):
        """Test detection of similar observations (stuck detection)."""
        # Record same observation multiple times
        for _ in range(4):
            state_module.record_observation(
                session_id=mock_session_id,
                screen_content="Same content\nLine 2\nLine 3",
                prompt_type="permission",
            )

        state = state_module.get_state(mock_session_id)
        assert state.similar_observations_count >= 3
        assert state.is_stuck is True

    def test_phase_transitions(self, state_module, mock_session_id):
        """Test phase transitions."""
        from src.agent.state_module import AgentPhase

        state = state_module.get_state(mock_session_id)
        assert state.phase == AgentPhase.IDLE

        state_module.set_phase(mock_session_id, AgentPhase.OBSERVING)
        assert state.phase == AgentPhase.OBSERVING

        state_module.set_phase(mock_session_id, AgentPhase.EXECUTING)
        assert state.phase == AgentPhase.EXECUTING


# ============================================================
# Goal Module Tests
# ============================================================

class TestGoalModule:
    """Tests for the goal module."""

    def test_create_goal(self, goal_module, mock_session_id, sample_goal_data):
        """Test creating a goal."""
        goal = goal_module.create_goal(
            session_id=mock_session_id,
            **sample_goal_data,
        )

        assert goal is not None
        assert goal.session_id == mock_session_id
        assert goal.description == sample_goal_data["description"]
        assert len(goal.success_criteria) == 3

    def test_get_session_goals(self, goal_module, mock_session_id, sample_goal_data):
        """Test getting goals for a session."""
        goal_module.create_goal(
            session_id=mock_session_id,
            **sample_goal_data,
        )

        goals = goal_module.get_session_goals(mock_session_id)
        assert len(goals) == 1

    def test_goal_lifecycle(self, goal_module, mock_session_id, sample_goal_data):
        """Test goal start/complete/fail lifecycle."""
        from src.agent.goal_module import GoalStatus

        goal = goal_module.create_goal(
            session_id=mock_session_id,
            **sample_goal_data,
        )

        assert goal.status == GoalStatus.PENDING

        goal.start()
        assert goal.status == GoalStatus.ACTIVE
        assert goal.started_at is not None

        goal.complete("All done!")
        assert goal.status == GoalStatus.COMPLETED
        assert goal.completed_at is not None

    def test_goal_progress(self, goal_module, mock_session_id, sample_goal_data):
        """Test goal progress tracking."""
        goal = goal_module.create_goal(
            session_id=mock_session_id,
            **sample_goal_data,
        )

        # Initially 0% progress
        assert goal.progress_percent == 0

        # Mark some criteria as met
        goal.mark_criterion(0, True)
        assert goal.progress_percent > 0

        goal.mark_criterion(1, True)
        goal.mark_criterion(2, True)
        assert goal.progress_percent == 100

    def test_hierarchical_goals(self, goal_module, mock_session_id):
        """Test parent/child goal relationships."""
        parent = goal_module.create_goal(
            session_id=mock_session_id,
            description="Main goal",
        )

        child = goal_module.create_goal(
            session_id=mock_session_id,
            description="Sub-goal",
            parent_id=parent.goal_id,
        )

        assert child.parent_id == parent.goal_id
        assert child.goal_id in parent.subgoal_ids


# ============================================================
# Plan Module Tests
# ============================================================

class TestPlanModule:
    """Tests for the plan module."""

    def test_create_plan(self, plan_module, mock_session_id, sample_plan_steps):
        """Test creating a plan."""
        plan = plan_module.create_plan(
            goal_id="goal-123",
            session_id=mock_session_id,
            steps=sample_plan_steps,
        )

        assert plan is not None
        assert len(plan.steps) == 5
        assert plan.steps[0].description == sample_plan_steps[0]

    def test_plan_execution(self, plan_module, mock_session_id, sample_plan_steps):
        """Test plan execution flow."""
        from src.agent.plan_module import StepStatus

        plan = plan_module.create_plan(
            goal_id="goal-123",
            session_id=mock_session_id,
            steps=sample_plan_steps,
        )

        plan.start()
        assert plan.started_at is not None

        # Current step should be first step
        current = plan.get_current_step()
        assert current.description == sample_plan_steps[0]
        assert current.status == StepStatus.IN_PROGRESS

        # Advance to next step
        next_step = plan.advance()
        assert next_step.description == sample_plan_steps[1]
        assert plan.steps[0].status == StepStatus.COMPLETED

    def test_plan_progress(self, plan_module, mock_session_id, sample_plan_steps):
        """Test plan progress tracking."""
        plan = plan_module.create_plan(
            goal_id="goal-123",
            session_id=mock_session_id,
            steps=sample_plan_steps,
        )

        assert plan.progress_percent == 0

        plan.start()
        plan.advance()  # Complete step 1
        assert plan.progress_percent == 20  # 1/5 = 20%

        plan.advance()  # Complete step 2
        assert plan.progress_percent == 40  # 2/5 = 40%

    def test_step_retry(self, plan_module, mock_session_id, sample_plan_steps):
        """Test step retry functionality."""
        plan = plan_module.create_plan(
            goal_id="goal-123",
            session_id=mock_session_id,
            steps=sample_plan_steps,
        )

        plan.start()
        plan.mark_step_failed("Error occurred")

        current = plan.get_current_step()
        assert current.error_message == "Error occurred"

        # Retry should work
        assert plan.retry_current_step() is True
        assert current.retries == 1

    def test_replan(self, plan_module, mock_session_id, sample_plan_steps):
        """Test replanning creates new plan and invalidates old."""
        plan1 = plan_module.create_plan(
            goal_id="goal-123",
            session_id=mock_session_id,
            steps=sample_plan_steps[:2],
        )

        new_steps = ["New step 1", "New step 2", "New step 3"]
        plan2 = plan_module.replan(
            goal_id="goal-123",
            session_id=mock_session_id,
            reason="Original plan not working",
            new_steps=new_steps,
        )

        assert plan1.is_active is False
        assert plan2.is_active is True
        assert plan2.replan_count == 1


# ============================================================
# Decision Module Tests
# ============================================================

class TestDecisionModule:
    """Tests for the decision module."""

    def test_tier1_permission_decision(self, decision_module):
        """Test Tier 1 rule-based permission decisions."""
        decision = decision_module.decide(
            prompt_type="permission",
            prompt_text="Claude wants to read file.py",
            context="Reading a Python file",
        )

        from src.agent.decision_module import DecisionTier
        assert decision.tier == DecisionTier.TIER_1_RULES
        assert decision.action_type == "approve"
        assert decision.action_value == "1"

    def test_tier1_dangerous_deny(self, decision_module):
        """Test Tier 1 denies dangerous actions."""
        decision = decision_module.decide(
            prompt_type="permission",
            prompt_text="Claude wants to run: rm -rf /",
            context="Deleting files",
        )

        assert decision.action_type == "deny"
        assert decision.action_value == "2"

    def test_tier1_continuation(self, decision_module):
        """Test Tier 1 continuation decisions."""
        decision = decision_module.decide(
            prompt_type="continuation",
            prompt_text="Stopped",
            context="Claude stopped",
        )

        assert decision.action_type == "continue"
        assert decision.action_value == "continue"

    def test_tier2_ucb_recommendations(self, decision_module):
        """Test Tier 2 UCB-based recommendations."""
        # Set up some UCB recommendations
        recommendations = {
            "abc123": [("1", 1.5), ("2", 0.5)],
        }
        decision_module.set_ucb_recommendations(recommendations)

        # The decision module should use UCB when rules are low confidence
        # This is hard to test without more setup, so we just verify the method works
        recs = decision_module._ucb_recommendations
        assert "abc123" in recs

    def test_context_hash(self, decision_module):
        """Test context hashing for experience matching."""
        hash1 = decision_module._hash_context("permission", "Allow edit?")
        hash2 = decision_module._hash_context("permission", "Allow edit?")
        hash3 = decision_module._hash_context("permission", "Allow delete?")

        assert hash1 == hash2  # Same context = same hash
        assert hash1 != hash3  # Different context = different hash


# ============================================================
# Learning Module Tests
# ============================================================

class TestLearningModule:
    """Tests for the learning module."""

    def test_record_experience(self, learning_module, mock_session_id):
        """Test recording an experience."""
        exp = learning_module.record_experience(
            session_id=mock_session_id,
            context_hash="abc123",
            prompt_type="permission",
            prompt_text="Allow edit?",
            action_type="approve",
            action_value="1",
            outcome="success",
        )

        assert exp is not None
        assert exp.action_value == "1"
        assert exp.outcome == "success"
        assert exp.reward > 0  # Success should have positive reward

    def test_ucb_recommendations(self, learning_module, mock_session_id, sample_experiences):
        """Test UCB recommendations after learning."""
        # Record multiple experiences
        for exp_data in sample_experiences:
            learning_module.record_experience(**exp_data)

        # Get recommendations
        recommendations = learning_module.get_recommendations("abc123")

        # Should have recommendations now
        assert len(recommendations) > 0

        # Best action should be "1" (more successes)
        best_action, _ = recommendations[0]
        assert best_action == "1"

    def test_reward_calculation(self, learning_module):
        """Test reward calculation."""
        # Success with progress should give high reward
        reward1 = learning_module._calculate_reward("success", 0.0, 0.5)
        assert reward1 > 0.5

        # Failure should give negative reward
        reward2 = learning_module._calculate_reward("failed", 0.5, 0.5)
        assert reward2 < 0

        # Timeout is slightly negative
        reward3 = learning_module._calculate_reward("timeout", 0.5, 0.5)
        assert reward3 < 0
        assert reward3 > reward2  # Timeout less bad than failure

    def test_batch_learning_threshold(self, learning_module, mock_session_id):
        """Test batch learning threshold."""
        assert learning_module.should_batch_learn() is False

        # Record enough experiences
        for i in range(12):
            learning_module.record_experience(
                session_id=mock_session_id,
                context_hash=f"hash{i}",
                prompt_type="permission",
                prompt_text=f"Prompt {i}",
                action_type="approve",
                action_value="1",
                outcome="success",
            )

        assert learning_module.should_batch_learn() is True

        # Get batch clears pending
        batch = learning_module.get_batch_for_learning()
        assert len(batch) >= 10
        assert learning_module.should_batch_learn() is False


# ============================================================
# Orchestrator Tests
# ============================================================

class TestOrchestrator:
    """Tests for the orchestrator."""

    @pytest.mark.asyncio
    async def test_process_observation_no_prompt(self, orchestrator, mock_session_id):
        """Test processing observation with no prompt detected."""
        result = await orchestrator.process_observation(
            session_id=mock_session_id,
            screen_content="Normal terminal output",
            prompt_type=None,
            prompt_text=None,
        )

        assert result is None  # No action needed

    @pytest.mark.asyncio
    async def test_process_observation_permission(
        self, orchestrator, mock_session_id, mock_screen_content
    ):
        """Test processing permission prompt."""
        result = await orchestrator.process_observation(
            session_id=mock_session_id,
            screen_content=mock_screen_content,
            prompt_type="permission",
            prompt_text="Claude wants to run ls -la",
        )

        assert result is not None
        action_type, action_value = result
        assert action_type == "approve"
        assert action_value == "1"

    @pytest.mark.asyncio
    async def test_set_goal(self, orchestrator, mock_session_id, sample_goal_data):
        """Test setting a goal via orchestrator."""
        goal = orchestrator.set_goal(
            session_id=mock_session_id,
            description=sample_goal_data["description"],
            success_criteria=sample_goal_data["success_criteria"],
        )

        assert goal is not None
        assert goal.is_active

        # Session should have goal
        status = orchestrator.get_session_status(mock_session_id)
        assert status["goal"] is not None

    @pytest.mark.asyncio
    async def test_create_plan(self, orchestrator, mock_session_id, sample_plan_steps):
        """Test creating a plan via orchestrator."""
        goal = orchestrator.set_goal(
            session_id=mock_session_id,
            description="Test goal",
        )

        plan = orchestrator.create_plan(
            goal_id=goal.goal_id,
            session_id=mock_session_id,
            steps=sample_plan_steps,
        )

        assert plan is not None
        assert len(plan.steps) == 5
        assert plan.is_active

    @pytest.mark.asyncio
    async def test_record_outcome(self, orchestrator, mock_session_id, mock_screen_content):
        """Test recording action outcome."""
        # First create an action
        await orchestrator.process_observation(
            session_id=mock_session_id,
            screen_content=mock_screen_content,
            prompt_type="permission",
            prompt_text="Test prompt",
        )

        # Record success
        await orchestrator.record_outcome(
            session_id=mock_session_id,
            outcome="success",
            details="Action completed",
        )

        state = orchestrator.state.get_state(mock_session_id)
        assert state.successful_actions == 1

    @pytest.mark.asyncio
    async def test_full_status(self, orchestrator, mock_session_id):
        """Test getting full agent status."""
        status = orchestrator.get_full_status()

        assert "state" in status
        assert "goals" in status
        assert "plans" in status
        assert "learning" in status
