import logging
import time
from typing import List, Dict

import requests

logger = logging.getLogger("deepseek")

BASE_URL = "https://api.deepseek.com"
ENDPOINT = "/chat/completions"

TEMPERATURES = {1: 0.2, 2: 0.75, 3: 0.2}


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        timeout: int = 30,
        max_tokens: int = 1000,
        round1_temperature: float = 0.2,
        round2_temperature: float = 0.75,
        round3_temperature: float = 0.2,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperatures = {
            1: round1_temperature,
            2: round2_temperature,
            3: round3_temperature,
        }

    def chat(self, messages: List[Dict], round_number: int = 2) -> str:
        temperature = self.temperatures.get(round_number, 0.7)
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error = None
        for attempt in range(1, 4):
            try:
                resp = requests.post(
                    BASE_URL + ENDPOINT,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** (attempt - 1)
                    logger.warning(f"DeepSeek HTTP {resp.status_code}. Attempt {attempt}/3. Retrying in {wait}s.")
                    last_error = f"HTTP {resp.status_code}"
                    time.sleep(wait)
                    continue
                logger.error(f"DeepSeek non-retryable error {resp.status_code}: {resp.text[:200]}")
                raise RuntimeError(f"DeepSeek API error {resp.status_code}")
            except requests.Timeout:
                wait = 2 ** (attempt - 1)
                logger.error(f"DeepSeek request timeout. Attempt {attempt}/3.")
                last_error = "timeout"
                if attempt < 3:
                    time.sleep(wait)
        raise RuntimeError(f"DeepSeek failed after 3 attempts: {last_error}")

    def is_healthy(self) -> bool:
        return bool(self.api_key and self.api_key.strip())
