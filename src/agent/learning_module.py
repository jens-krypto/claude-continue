"""
Learning module for reinforcement learning with UCB.

Features:
- Experience replay buffer (observation, action, outcome, reward)
- UCB (Upper Confidence Bound) for exploration/exploitation
- Batch learning: aggregate experiences before API analysis
- Persistent storage (~/.claude-continue/learning/)
- Dense reward shaping based on goal progress
"""
import json
import math
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """A single experience (state, action, outcome, reward)."""
    timestamp: float
    session_id: str

    # Context
    context_hash: str            # Hash of observation context
    prompt_type: str             # permission, question, continuation, etc.
    prompt_text: str             # The actual prompt

    # Action taken
    action_type: str             # approve, deny, respond, continue, etc.
    action_value: str            # The actual response sent

    # Outcome
    outcome: str                 # success, failed, timeout
    outcome_details: Optional[str] = None

    # Reward
    reward: float = 0.0          # -1.0 to 1.0

    # Goal context
    goal_id: Optional[str] = None
    goal_progress_before: float = 0.0
    goal_progress_after: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experience":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ActionStats:
    """Statistics for an action in a context."""
    action_value: str
    count: int = 0
    total_reward: float = 0.0
    successes: int = 0
    failures: int = 0

    @property
    def mean_reward(self) -> float:
        """Calculate mean reward."""
        if self.count == 0:
            return 0.0
        return self.total_reward / self.count

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.successes + self.failures
        if total == 0:
            return 0.5  # Unknown = 50%
        return self.successes / total

    def ucb_score(self, total_count: int, exploration_constant: float = 1.41) -> float:
        """
        Calculate UCB score for this action.

        UCB = mean_reward + c * sqrt(ln(total) / count)

        Args:
            total_count: Total number of experiences in this context
            exploration_constant: c value (default sqrt(2) is theoretically optimal)
        """
        if self.count == 0:
            return float('inf')  # Unexplored actions get priority

        exploitation = self.mean_reward
        exploration = exploration_constant * math.sqrt(math.log(total_count) / self.count)

        return exploitation + exploration


class LearningModule:
    """
    Reinforcement learning module with UCB algorithm.

    Learns from experiences to recommend actions based on past success.
    Uses UCB (Upper Confidence Bound) to balance exploration vs exploitation.
    """

    # Minimum experiences before learning from a context
    MIN_EXPERIENCES_PER_CONTEXT = 3

    # Batch size for LLM-assisted learning
    BATCH_SIZE_FOR_LLM = 10

    # Exploration constant for UCB
    EXPLORATION_CONSTANT = 1.41  # sqrt(2)

    def __init__(self, storage_dir: Optional[Path] = None):
        """Initialize with optional custom storage directory."""
        # Experience storage
        self._experiences: List[Experience] = []

        # Action statistics per context
        # context_hash → action_value → ActionStats
        self._action_stats: Dict[str, Dict[str, ActionStats]] = defaultdict(dict)

        # Pending experiences for batch learning
        self._pending_batch: List[Experience] = []

        # Learned patterns (from LLM analysis)
        self._learned_patterns: Dict[str, str] = {}  # pattern → recommended_action

        # Storage setup
        if storage_dir:
            self._storage_dir = storage_dir
        else:
            self._storage_dir = Path.home() / ".claude-continue" / "learning"

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._load_data()

        logger.info(f"LearningModule initialized with {len(self._experiences)} experiences")

    def record_experience(
        self,
        session_id: str,
        context_hash: str,
        prompt_type: str,
        prompt_text: str,
        action_type: str,
        action_value: str,
        outcome: str,
        outcome_details: Optional[str] = None,
        goal_id: Optional[str] = None,
        goal_progress_before: float = 0.0,
        goal_progress_after: float = 0.0,
    ) -> Experience:
        """
        Record an experience.

        Args:
            session_id: Session identifier
            context_hash: Hash of the context/observation
            prompt_type: Type of prompt
            prompt_text: The actual prompt
            action_type: Type of action taken
            action_value: The actual response sent
            outcome: "success", "failed", or "timeout"
            outcome_details: Additional outcome info
            goal_id: Current goal ID if any
            goal_progress_before: Goal progress before action
            goal_progress_after: Goal progress after action

        Returns:
            The recorded Experience
        """
        # Calculate reward
        reward = self._calculate_reward(
            outcome, goal_progress_before, goal_progress_after
        )

        experience = Experience(
            timestamp=time.time(),
            session_id=session_id,
            context_hash=context_hash,
            prompt_type=prompt_type,
            prompt_text=prompt_text,
            action_type=action_type,
            action_value=action_value,
            outcome=outcome,
            outcome_details=outcome_details,
            reward=reward,
            goal_id=goal_id,
            goal_progress_before=goal_progress_before,
            goal_progress_after=goal_progress_after,
        )

        # Store experience
        self._experiences.append(experience)

        # Update action statistics
        self._update_stats(experience)

        # Add to pending batch
        self._pending_batch.append(experience)

        # Persist
        self._save_experience(experience)

        logger.debug(
            f"Recorded experience: {action_value} → {outcome} (reward: {reward:.2f})"
        )

        return experience

    def get_recommendations(self, context_hash: str) -> List[Tuple[str, float]]:
        """
        Get UCB-scored action recommendations for a context.

        Args:
            context_hash: Hash of the current context

        Returns:
            List of (action_value, ucb_score) sorted by score descending
        """
        if context_hash not in self._action_stats:
            return []

        stats = self._action_stats[context_hash]
        total_count = sum(s.count for s in stats.values())

        if total_count < self.MIN_EXPERIENCES_PER_CONTEXT:
            return []

        # Calculate UCB scores
        recommendations = []
        for action_value, action_stats in stats.items():
            ucb = action_stats.ucb_score(total_count, self.EXPLORATION_CONSTANT)
            recommendations.append((action_value, ucb))

        # Sort by UCB score descending
        recommendations.sort(key=lambda x: x[1], reverse=True)

        return recommendations

    def get_all_recommendations(self) -> Dict[str, List[Tuple[str, float]]]:
        """
        Get recommendations for all known contexts.

        Returns:
            Dict of context_hash → [(action, ucb_score), ...]
        """
        return {
            ctx: self.get_recommendations(ctx)
            for ctx in self._action_stats.keys()
        }

    def should_batch_learn(self) -> bool:
        """Check if we have enough pending experiences for batch learning."""
        return len(self._pending_batch) >= self.BATCH_SIZE_FOR_LLM

    def get_batch_for_learning(self) -> List[Experience]:
        """Get and clear the pending batch for learning."""
        batch = self._pending_batch.copy()
        self._pending_batch.clear()
        return batch

    def add_learned_pattern(self, pattern: str, recommended_action: str):
        """Add a pattern learned from LLM analysis."""
        self._learned_patterns[pattern] = recommended_action
        self._save_patterns()

    def get_learned_pattern(self, context: str) -> Optional[str]:
        """Check if any learned pattern matches the context."""
        import re
        for pattern, action in self._learned_patterns.items():
            try:
                if re.search(pattern, context, re.IGNORECASE):
                    return action
            except re.error:
                continue
        return None

    def _calculate_reward(
        self,
        outcome: str,
        progress_before: float,
        progress_after: float,
    ) -> float:
        """
        Calculate reward for an action.

        Uses dense reward shaping based on:
        1. Immediate outcome (success/failure)
        2. Goal progress delta
        """
        # Base reward from outcome
        if outcome == "success":
            base_reward = 0.5
        elif outcome == "failed":
            base_reward = -0.5
        elif outcome == "timeout":
            base_reward = -0.2
        else:
            base_reward = 0.0

        # Progress bonus/penalty
        progress_delta = progress_after - progress_before
        progress_reward = progress_delta * 0.5  # Scale to [-0.5, 0.5]

        # Combine
        total_reward = base_reward + progress_reward

        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, total_reward))

    def _update_stats(self, experience: Experience):
        """Update action statistics from an experience."""
        ctx = experience.context_hash
        action = experience.action_value

        if action not in self._action_stats[ctx]:
            self._action_stats[ctx][action] = ActionStats(action_value=action)

        stats = self._action_stats[ctx][action]
        stats.count += 1
        stats.total_reward += experience.reward

        if experience.outcome == "success":
            stats.successes += 1
        elif experience.outcome == "failed":
            stats.failures += 1

    def _save_experience(self, experience: Experience):
        """Save an experience to storage."""
        # Save to daily file for organization
        date_str = time.strftime("%Y-%m-%d")
        path = self._storage_dir / f"experiences_{date_str}.jsonl"

        try:
            with open(path, "a") as f:
                f.write(json.dumps(experience.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to save experience: {e}")

    def _save_patterns(self):
        """Save learned patterns to storage."""
        path = self._storage_dir / "learned_patterns.json"
        try:
            with open(path, "w") as f:
                json.dump(self._learned_patterns, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save patterns: {e}")

    def _save_stats(self):
        """Save action statistics to storage."""
        path = self._storage_dir / "action_stats.json"
        try:
            # Convert stats to serializable format
            data = {}
            for ctx, actions in self._action_stats.items():
                data[ctx] = {
                    action: {
                        "action_value": stats.action_value,
                        "count": stats.count,
                        "total_reward": stats.total_reward,
                        "successes": stats.successes,
                        "failures": stats.failures,
                    }
                    for action, stats in actions.items()
                }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    def _load_data(self):
        """Load data from storage."""
        # Load experiences from recent files
        for path in sorted(self._storage_dir.glob("experiences_*.jsonl"))[-7:]:
            try:
                with open(path) as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            exp = Experience.from_dict(data)
                            self._experiences.append(exp)
                            self._update_stats(exp)
            except Exception as e:
                logger.warning(f"Failed to load experiences from {path}: {e}")

        # Load learned patterns
        patterns_path = self._storage_dir / "learned_patterns.json"
        if patterns_path.exists():
            try:
                with open(patterns_path) as f:
                    self._learned_patterns = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load patterns: {e}")

        # Load action stats (optional - can be rebuilt from experiences)
        stats_path = self._storage_dir / "action_stats.json"
        if stats_path.exists():
            try:
                with open(stats_path) as f:
                    data = json.load(f)
                for ctx, actions in data.items():
                    for action, stats_data in actions.items():
                        stats = ActionStats(
                            action_value=stats_data["action_value"],
                            count=stats_data["count"],
                            total_reward=stats_data["total_reward"],
                            successes=stats_data["successes"],
                            failures=stats_data["failures"],
                        )
                        self._action_stats[ctx][action] = stats
            except Exception as e:
                logger.warning(f"Failed to load stats: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get status for web API."""
        return {
            "total_experiences": len(self._experiences),
            "contexts_learned": len(self._action_stats),
            "pending_batch_size": len(self._pending_batch),
            "learned_patterns": len(self._learned_patterns),
            "top_contexts": self._get_top_contexts(5),
        }

    def _get_top_contexts(self, n: int) -> List[Dict[str, Any]]:
        """Get top N contexts by experience count."""
        ctx_counts = [
            (ctx, sum(s.count for s in stats.values()))
            for ctx, stats in self._action_stats.items()
        ]
        ctx_counts.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "context_hash": ctx,
                "experience_count": count,
                "best_action": self.get_recommendations(ctx)[0][0] if self.get_recommendations(ctx) else None,
            }
            for ctx, count in ctx_counts[:n]
        ]

    def clear_old_data(self, days_to_keep: int = 30):
        """Clear experiences older than N days."""
        cutoff = time.time() - (days_to_keep * 86400)

        # Filter experiences
        self._experiences = [
            exp for exp in self._experiences
            if exp.timestamp > cutoff
        ]

        # Rebuild stats from remaining experiences
        self._action_stats.clear()
        for exp in self._experiences:
            self._update_stats(exp)

        # Save updated stats
        self._save_stats()

        logger.info(f"Cleared old data, {len(self._experiences)} experiences remaining")


# Global instance
learning_module = LearningModule()
