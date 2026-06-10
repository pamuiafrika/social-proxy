import logging
from typing import Optional

from ai.deepseek import DeepSeekClient
from ai.zhipu import ZhipuClient

logger = logging.getLogger("llm_selector")


class LLMUnavailableError(Exception):
    pass


class LLMSelector:
    def __init__(
        self,
        deepseek: DeepSeekClient,
        zhipu: ZhipuClient,
        state_manager=None,
    ):
        self.deepseek = deepseek
        self.zhipu = zhipu
        self.state = state_manager
        self._ds_healthy: Optional[bool] = None
        self._zh_healthy: Optional[bool] = None

    def check_health(self):
        self._ds_healthy = self.deepseek.is_healthy()
        self._zh_healthy = self.zhipu.is_healthy()
        if self.state:
            self.state.set("llm_primary_healthy", str(self._ds_healthy).lower())
            self.state.set("llm_secondary_healthy", str(self._zh_healthy).lower())
        logger.info(
            f"LLM health — DeepSeek: {'OK' if self._ds_healthy else 'DOWN'}, "
            f"Zhipu: {'OK' if self._zh_healthy else 'DOWN'}"
        )

    def select(self, contact, round_number: int):
        if self._ds_healthy is None:
            self.check_health()

        pref = getattr(contact, "model_preference", "auto")
        trust = getattr(contact, "trust_level", "medium")

        if self._ds_healthy and self._zh_healthy:
            if pref == "deepseek":
                return self.deepseek
            if pref == "zhipu":
                return self.zhipu
            # auto selection
            if round_number in (1, 3):
                return self.deepseek
            if trust in ("high", "medium"):
                return self.deepseek
            return self.zhipu  # low trust, round 2

        if self._ds_healthy:
            return self.deepseek
        if self._zh_healthy:
            return self.zhipu

        raise LLMUnavailableError("Both DeepSeek and Zhipu are unavailable")

    def select_for_insights(self):
        if self._zh_healthy is None:
            self.check_health()
        if self._zh_healthy:
            return self.zhipu
        if self._ds_healthy:
            return self.deepseek
        raise LLMUnavailableError("No LLM available for insight extraction")
