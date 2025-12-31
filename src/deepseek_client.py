"""
DeepSeek API client for intelligent question answering and follow-up generation.
Uses rate limiting to stay within budget (default: 5 calls/hour).
"""
import os
import time
import logging
import configparser
from typing import Optional
from pathlib import Path
from dataclasses import dataclass
import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class DeepSeekConfig:
    """DeepSeek configuration."""
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_tokens: int = 500
    temperature: float = 0.7
    calls_per_hour: int = 5


class RateLimiter:
    """Simple rate limiter tracking calls per hour."""

    def __init__(self, max_calls_per_hour: int = 5):
        self.max_calls = max_calls_per_hour
        self.calls: list[float] = []

    def can_call(self) -> bool:
        """Check if we can make another call."""
        self._cleanup_old_calls()
        return len(self.calls) < self.max_calls

    def record_call(self):
        """Record a call."""
        self.calls.append(time.time())

    def _cleanup_old_calls(self):
        """Remove calls older than 1 hour."""
        one_hour_ago = time.time() - 3600
        self.calls = [t for t in self.calls if t > one_hour_ago]

    def remaining_calls(self) -> int:
        """Return number of calls remaining this hour."""
        self._cleanup_old_calls()
        return max(0, self.max_calls - len(self.calls))

    def seconds_until_next(self) -> float:
        """Seconds until next call is available (0 if available now)."""
        if self.can_call():
            return 0
        self._cleanup_old_calls()
        if not self.calls:
            return 0
        oldest = min(self.calls)
        return max(0, oldest + 3600 - time.time())


def load_config() -> Optional[DeepSeekConfig]:
    """
    Load DeepSeek config from config files.
    Tries claudecontinue.config.local first, then claudecontinue.config.
    """
    project_root = Path(__file__).parent.parent

    config_files = [
        project_root / "claudecontinue.config.local",
        project_root / "claudecontinue.config",
    ]

    for config_file in config_files:
        if config_file.exists():
            try:
                config = configparser.ConfigParser()
                config.read(config_file)

                if "deepseek" in config and config["deepseek"].get("api_key"):
                    api_key = config["deepseek"]["api_key"].strip()
                    if not api_key:
                        continue

                    # Get rate limit from rate_limits section if exists
                    calls_per_hour = 5
                    if "rate_limits" in config:
                        calls_per_hour = int(config["rate_limits"].get(
                            "deepseek_calls_per_hour", "5"
                        ))

                    return DeepSeekConfig(
                        api_key=api_key,
                        base_url=config["deepseek"].get("base_url", "https://api.deepseek.com/v1"),
                        model=config["deepseek"].get("model", "deepseek-chat"),
                        max_tokens=int(config["deepseek"].get("max_tokens", "500")),
                        temperature=float(config["deepseek"].get("temperature", "0.7")),
                        calls_per_hour=calls_per_hour,
                    )
            except Exception as e:
                logger.warning(f"Failed to parse {config_file}: {e}")
                continue

    return None


class DeepSeekClient:
    """
    Client for DeepSeek API with rate limiting.
    Used for answering questions and generating follow-ups.
    """

    SYSTEM_PROMPT = """You are an assistant helping with Claude Code prompts.
Your job is to answer questions or generate helpful follow-up prompts.

Context: You're observing a terminal session where Claude Code is running.
The user may have questions that need answering, or Claude may need follow-up prompts.

Be concise - responses should be short and actionable.
For questions, give direct answers.
For follow-ups, suggest what to ask Claude next."""

    def __init__(self):
        self.config = load_config()
        if self.config:
            self.rate_limiter = RateLimiter(self.config.calls_per_hour)
            logger.info(f"DeepSeek client initialized (max {self.config.calls_per_hour} calls/hour)")
        else:
            self.rate_limiter = None
            logger.info("DeepSeek not configured - using pattern-based responses only")

    @property
    def is_available(self) -> bool:
        """Check if DeepSeek is configured and available."""
        return self.config is not None

    @property
    def can_call(self) -> bool:
        """Check if we can make a call (configured + not rate limited)."""
        return self.is_available and self.rate_limiter.can_call()

    def get_status(self) -> dict:
        """Get current status for web GUI."""
        if not self.is_available:
            return {
                "enabled": False,
                "reason": "No API key configured",
            }

        return {
            "enabled": True,
            "remaining_calls": self.rate_limiter.remaining_calls(),
            "max_calls_per_hour": self.config.calls_per_hour,
            "seconds_until_next": self.rate_limiter.seconds_until_next(),
        }

    async def answer_question(self, question: str, context: str = "") -> Optional[str]:
        """
        Answer a question using DeepSeek.

        Args:
            question: The question to answer
            context: Terminal context (recent output)

        Returns:
            Answer string, or None if rate limited/unavailable
        """
        if not self.can_call:
            if not self.is_available:
                logger.debug("DeepSeek not configured")
            else:
                remaining = self.rate_limiter.seconds_until_next()
                logger.info(f"DeepSeek rate limited - wait {remaining:.0f}s")
            return None

        try:
            user_message = f"""Terminal context:
{context[-2000:] if context else '(no context)'}

Question to answer:
{question}

Provide a concise, helpful answer."""

            response = await self._call_api(user_message)
            self.rate_limiter.record_call()
            logger.info(f"DeepSeek answered question ({self.rate_limiter.remaining_calls()} calls remaining)")
            return response

        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            return None

    async def generate_followup(self, context: str) -> Optional[str]:
        """
        Generate a follow-up prompt based on context.

        Args:
            context: Recent terminal output

        Returns:
            Follow-up prompt, or None if rate limited/unavailable
        """
        if not self.can_call:
            if not self.is_available:
                logger.debug("DeepSeek not configured")
            else:
                remaining = self.rate_limiter.seconds_until_next()
                logger.info(f"DeepSeek rate limited - wait {remaining:.0f}s")
            return None

        try:
            user_message = f"""Terminal context (recent Claude Code output):
{context[-3000:] if context else '(no context)'}

Claude appears to be idle. Generate a helpful follow-up prompt to continue the work.
The prompt should:
- Be concise (1-2 sentences)
- Ask Claude to continue or explain next steps
- Be prefixed with [AUTO] to indicate it's automated

Just respond with the follow-up prompt, nothing else."""

            response = await self._call_api(user_message)
            self.rate_limiter.record_call()
            logger.info(f"DeepSeek generated follow-up ({self.rate_limiter.remaining_calls()} calls remaining)")

            # Ensure [AUTO] prefix
            if response and not response.startswith("[AUTO]"):
                response = f"[AUTO] {response}"

            return response

        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            return None

    async def _call_api(self, user_message: str) -> Optional[str]:
        """Make the actual API call."""
        if not self.config:
            return None

        url = f"{self.config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"API error {resp.status}: {error_text}")

                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()


# Global instance
deepseek_client = DeepSeekClient()
