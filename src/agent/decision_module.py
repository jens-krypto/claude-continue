"""
Decision module for multi-tier decision making.

Implements a 3-tier decision system:
- Tier 1 (Fast): Rule-based for common cases (no API)
- Tier 2 (Learned): UCB recommendations from past experiences (no API)
- Tier 3 (LLM): DeepSeek for complex/stuck situations (rate-limited)
"""
import json
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple

from ..smart_responder import SmartResponder, SmartResponse
from ..deepseek_client import deepseek_client

logger = logging.getLogger(__name__)


class DecisionTier(Enum):
    """Which tier made the decision."""
    TIER_1_RULES = "rules"       # Rule-based (fast, no API)
    TIER_2_UCB = "ucb"           # UCB recommendations (learned, no API)
    TIER_3_LLM = "llm"           # DeepSeek LLM (slow, rate-limited)
    FALLBACK = "fallback"        # Default fallback


@dataclass
class Decision:
    """A decision made by the agent."""
    action_type: str             # "approve", "deny", "respond", "continue", "wait", "replan"
    action_value: str            # The actual response (e.g., "1", "yes", text response)
    confidence: float            # 0.0 to 1.0
    tier: DecisionTier           # Which tier made this decision
    reason: str                  # Human-readable explanation

    # For learning
    context_hash: Optional[str] = None  # Hash of context for experience matching
    goal_relevance: float = 0.0  # How relevant to current goal (0-1)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "action_type": self.action_type,
            "action_value": self.action_value,
            "confidence": self.confidence,
            "tier": self.tier.value,
            "reason": self.reason,
            "context_hash": self.context_hash,
            "goal_relevance": self.goal_relevance,
        }


class DecisionModule:
    """
    Multi-tier decision making for agent actions.

    Tier 1: Rule-based decisions (from SmartResponder)
    Tier 2: UCB-based recommendations (from learning module)
    Tier 3: LLM-based decisions (from DeepSeek)
    """

    # Confidence threshold for accepting Tier 1 decisions
    TIER_1_CONFIDENCE_THRESHOLD = 0.7

    # Stuck threshold for escalating to Tier 3
    STUCK_THRESHOLD = 3  # 3 similar observations = stuck

    def __init__(self):
        self._smart_responder = SmartResponder()
        self._ucb_recommendations: Dict[str, List[Tuple[str, float]]] = {}
        logger.info("DecisionModule initialized")

    def set_ucb_recommendations(self, recommendations: Dict[str, List[Tuple[str, float]]]):
        """
        Set UCB recommendations from learning module.

        Args:
            recommendations: context_hash → [(action, ucb_score), ...]
        """
        self._ucb_recommendations = recommendations

    def decide(
        self,
        prompt_type: str,
        prompt_text: str,
        context: str,
        goal_description: Optional[str] = None,
        is_stuck: bool = False,
        similar_count: int = 0,
    ) -> Decision:
        """
        Make a decision about how to respond to a prompt.

        Goes through tiers until a confident decision is found.

        Args:
            prompt_type: Type of prompt (permission, question, continuation, completed)
            prompt_text: The actual prompt text
            context: Terminal context (screen content)
            goal_description: Current goal if any
            is_stuck: Whether the session appears stuck
            similar_count: Number of similar observations seen

        Returns:
            Decision object with action and metadata
        """
        context_hash = self._hash_context(prompt_type, prompt_text)

        # Tier 1: Rule-based decisions
        tier1_decision = self._tier1_rules(prompt_type, prompt_text, context)
        if tier1_decision and tier1_decision.confidence >= self.TIER_1_CONFIDENCE_THRESHOLD:
            tier1_decision.context_hash = context_hash
            logger.debug(f"Tier 1 decision: {tier1_decision.action_value} ({tier1_decision.confidence:.0%})")
            return tier1_decision

        # Tier 2: UCB recommendations
        tier2_decision = self._tier2_ucb(context_hash, prompt_type)
        if tier2_decision and tier2_decision.confidence >= 0.6:
            tier2_decision.context_hash = context_hash
            logger.debug(f"Tier 2 UCB decision: {tier2_decision.action_value} ({tier2_decision.confidence:.0%})")
            return tier2_decision

        # Tier 3: LLM decision (only if stuck or low confidence)
        if is_stuck or similar_count >= self.STUCK_THRESHOLD:
            tier3_decision = self._tier3_llm(
                prompt_type, prompt_text, context, goal_description
            )
            if tier3_decision:
                tier3_decision.context_hash = context_hash
                logger.info(f"Tier 3 LLM decision: {tier3_decision.action_value}")
                return tier3_decision

        # Fallback: Use Tier 1 with lower threshold or default
        if tier1_decision:
            tier1_decision.context_hash = context_hash
            return tier1_decision

        # Ultimate fallback
        return self._fallback_decision(prompt_type, context_hash)

    def _tier1_rules(
        self,
        prompt_type: str,
        prompt_text: str,
        context: str,
    ) -> Optional[Decision]:
        """
        Tier 1: Rule-based decisions using SmartResponder patterns.
        """
        if prompt_type == "permission":
            # Permission prompts get Yes/No based on action safety
            approved, confidence, reason = self._smart_responder.should_approve_action(
                f"{prompt_text}\n{context}"
            )
            return Decision(
                action_type="approve" if approved else "deny",
                action_value="1" if approved else "2",
                confidence=confidence,
                tier=DecisionTier.TIER_1_RULES,
                reason=reason,
            )

        elif prompt_type == "continuation":
            # Continuation prompts almost always get "continue"
            return Decision(
                action_type="continue",
                action_value="continue",
                confidence=0.9,
                tier=DecisionTier.TIER_1_RULES,
                reason="Continuation prompt - default continue",
            )

        elif prompt_type == "question":
            # Questions use pattern matching
            response = self._smart_responder.answer_question(prompt_text, context)
            return Decision(
                action_type="respond",
                action_value=response.response,
                confidence=response.confidence,
                tier=DecisionTier.TIER_1_RULES,
                reason=response.reason,
            )

        elif prompt_type == "completed":
            # Completion - could wait for user or generate follow-up
            return Decision(
                action_type="wait",
                action_value="",
                confidence=0.6,
                tier=DecisionTier.TIER_1_RULES,
                reason="Task appears completed - waiting for user",
            )

        return None

    def _tier2_ucb(
        self,
        context_hash: str,
        prompt_type: str,
    ) -> Optional[Decision]:
        """
        Tier 2: UCB-based recommendations from learning module.
        """
        if context_hash not in self._ucb_recommendations:
            return None

        recommendations = self._ucb_recommendations[context_hash]
        if not recommendations:
            return None

        # Get best action by UCB score
        best_action, best_score = recommendations[0]

        # Convert UCB score to confidence (UCB scores are typically > 1)
        confidence = min(1.0, best_score / 2.0)

        return Decision(
            action_type=self._infer_action_type(best_action, prompt_type),
            action_value=best_action,
            confidence=confidence,
            tier=DecisionTier.TIER_2_UCB,
            reason=f"UCB recommendation (score: {best_score:.2f})",
        )

    def _tier3_llm(
        self,
        prompt_type: str,
        prompt_text: str,
        context: str,
        goal_description: Optional[str],
    ) -> Optional[Decision]:
        """
        Tier 3: LLM-based decisions using DeepSeek.

        Only called when stuck or unable to make confident decision.
        Rate-limited to 5 calls/hour.
        """
        if not deepseek_client.can_call:
            logger.debug("Tier 3 skipped - DeepSeek rate limited or unavailable")
            return None

        # Build prompt for LLM
        prompt = self._build_llm_prompt(prompt_type, prompt_text, context, goal_description)

        try:
            # Note: This is synchronous - will be called from async context
            # In production, we'd want to handle this better
            import asyncio

            # Try to get running loop, or create new one
            try:
                loop = asyncio.get_running_loop()
                # We're in async context - can't call sync here
                # Return None and let caller handle async
                logger.debug("Tier 3 skipped - already in async context")
                return None
            except RuntimeError:
                # No running loop - safe to create one
                response = asyncio.run(
                    deepseek_client._call_api(prompt)  # Direct API call
                )

            if not response:
                return None

            # Parse JSON response
            decision_data = self._parse_llm_response(response)
            if not decision_data:
                return None

            return Decision(
                action_type=decision_data.get("action_type", "respond"),
                action_value=decision_data.get("action_value", ""),
                confidence=float(decision_data.get("confidence", 0.7)),
                tier=DecisionTier.TIER_3_LLM,
                reason=decision_data.get("reason", "LLM decision"),
                goal_relevance=float(decision_data.get("goal_relevance", 0.5)),
            )

        except Exception as e:
            logger.error(f"Tier 3 LLM decision failed: {e}")
            return None

    async def decide_async(
        self,
        prompt_type: str,
        prompt_text: str,
        context: str,
        goal_description: Optional[str] = None,
        is_stuck: bool = False,
        similar_count: int = 0,
    ) -> Decision:
        """
        Async version of decide() - supports LLM calls in async context.
        """
        context_hash = self._hash_context(prompt_type, prompt_text)

        # Tier 1: Rule-based decisions
        tier1_decision = self._tier1_rules(prompt_type, prompt_text, context)
        if tier1_decision and tier1_decision.confidence >= self.TIER_1_CONFIDENCE_THRESHOLD:
            tier1_decision.context_hash = context_hash
            return tier1_decision

        # Tier 2: UCB recommendations
        tier2_decision = self._tier2_ucb(context_hash, prompt_type)
        if tier2_decision and tier2_decision.confidence >= 0.6:
            tier2_decision.context_hash = context_hash
            return tier2_decision

        # Tier 3: LLM decision (async)
        if is_stuck or similar_count >= self.STUCK_THRESHOLD:
            tier3_decision = await self._tier3_llm_async(
                prompt_type, prompt_text, context, goal_description
            )
            if tier3_decision:
                tier3_decision.context_hash = context_hash
                return tier3_decision

        # Fallback
        if tier1_decision:
            tier1_decision.context_hash = context_hash
            return tier1_decision

        return self._fallback_decision(prompt_type, context_hash)

    async def _tier3_llm_async(
        self,
        prompt_type: str,
        prompt_text: str,
        context: str,
        goal_description: Optional[str],
    ) -> Optional[Decision]:
        """Async version of Tier 3 LLM decisions."""
        if not deepseek_client.can_call:
            return None

        prompt = self._build_llm_prompt(prompt_type, prompt_text, context, goal_description)

        try:
            response = await deepseek_client._call_api(prompt)
            if not response:
                return None

            decision_data = self._parse_llm_response(response)
            if not decision_data:
                return None

            return Decision(
                action_type=decision_data.get("action_type", "respond"),
                action_value=decision_data.get("action_value", ""),
                confidence=float(decision_data.get("confidence", 0.7)),
                tier=DecisionTier.TIER_3_LLM,
                reason=decision_data.get("reason", "LLM decision"),
                goal_relevance=float(decision_data.get("goal_relevance", 0.5)),
            )
        except Exception as e:
            logger.error(f"Async Tier 3 LLM decision failed: {e}")
            return None

    def _fallback_decision(self, prompt_type: str, context_hash: str) -> Decision:
        """Generate a safe fallback decision."""
        if prompt_type == "permission":
            # Default approve with low confidence
            return Decision(
                action_type="approve",
                action_value="1",
                confidence=0.3,
                tier=DecisionTier.FALLBACK,
                reason="Fallback: default approve",
                context_hash=context_hash,
            )
        elif prompt_type == "continuation":
            return Decision(
                action_type="continue",
                action_value="continue",
                confidence=0.5,
                tier=DecisionTier.FALLBACK,
                reason="Fallback: default continue",
                context_hash=context_hash,
            )
        else:
            # Wait for user
            return Decision(
                action_type="wait",
                action_value="",
                confidence=0.2,
                tier=DecisionTier.FALLBACK,
                reason="Fallback: waiting for user",
                context_hash=context_hash,
            )

    def _build_llm_prompt(
        self,
        prompt_type: str,
        prompt_text: str,
        context: str,
        goal_description: Optional[str],
    ) -> str:
        """Build prompt for LLM decision making."""
        goal_section = ""
        if goal_description:
            goal_section = f"\nCurrent Goal: {goal_description}\n"

        return f"""You are an AI agent controlling a Claude Code session.
{goal_section}
A {prompt_type} prompt has appeared in the terminal.

Terminal context (last lines):
{context[-1500:]}

Prompt detected:
{prompt_text}

Decide how to respond. Return JSON only:
{{
    "action_type": "approve|deny|respond|continue|wait|replan",
    "action_value": "your response (e.g., '1' for approve, '2' for deny, or text)",
    "confidence": 0.0-1.0,
    "reason": "brief explanation",
    "goal_relevance": 0.0-1.0 (how relevant is this to achieving the goal)
}}

Guidelines:
- For permission prompts: "1" = Yes/approve, "2" = No/deny
- For questions: provide a helpful answer
- For continuations: "continue" or specific guidance
- Use "replan" if current approach isn't working
- Use "wait" if user input is needed

Respond with JSON only, no markdown."""

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse JSON response from LLM."""
        try:
            # Try to find JSON in response
            response = response.strip()

            # Remove markdown code blocks if present
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1])

            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {response[:100]}")
            return None

    def _hash_context(self, prompt_type: str, prompt_text: str) -> str:
        """Create a hash of the context for experience matching."""
        import hashlib
        content = f"{prompt_type}:{prompt_text[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _infer_action_type(self, action_value: str, prompt_type: str) -> str:
        """Infer action type from action value."""
        if action_value == "1":
            return "approve"
        elif action_value == "2":
            return "deny"
        elif action_value.lower() in ("continue", "yes"):
            return "continue"
        elif prompt_type == "permission":
            return "approve" if action_value == "1" else "deny"
        else:
            return "respond"


# Global instance
decision_module = DecisionModule()
