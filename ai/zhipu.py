import logging
import time
from datetime import datetime, timezone
from typing import Dict, List

import requests

logger = logging.getLogger("zhipu")

BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ENDPOINT = "/chat/completions"


def _generate_jwt(api_key: str) -> str:
    import hmac
    import hashlib
    import base64
    import json

    parts = api_key.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid Zhipu API key format — expected 'key_id.secret'")
    key_id, secret = parts[0], parts[1]
    now = int(datetime.now(timezone.utc).timestamp())
    header = {"alg": "HS256", "sign_type": "SIGN"}
    payload = {"api_key": key_id, "exp": now + 30, "timestamp": now}

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = b64(json.dumps(header, separators=(",", ":")).encode())
    p = b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{b64(sig)}"


class ZhipuClient:
    def __init__(
        self,
        api_key: str,
        model: str = "glm-4-flash",
        timeout: int = 30,
        max_tokens: int = 800,
        round1_temperature: float = 0.2,
        round2_temperature: float = 0.75,
        round3_temperature: float = 0.2,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperatures = {1: round1_temperature, 2: round2_temperature, 3: round3_temperature}

    def chat(self, messages: List[Dict], round_number: int = 2) -> str:
        temperature = self.temperatures.get(round_number, 0.7)
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        last_error = None
        for attempt in range(1, 4):
            try:
                token = _generate_jwt(self.api_key)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
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
                    logger.warning(f"Zhipu HTTP {resp.status_code}. Attempt {attempt}/3. Retrying in {wait}s.")
                    last_error = f"HTTP {resp.status_code}"
                    time.sleep(wait)
                    continue
                logger.error(f"Zhipu non-retryable error {resp.status_code}: {resp.text[:200]}")
                raise RuntimeError(f"Zhipu API error {resp.status_code}")
            except requests.Timeout:
                wait = 2 ** (attempt - 1)
                logger.error(f"Zhipu request timeout. Attempt {attempt}/3.")
                last_error = "timeout"
                if attempt < 3:
                    time.sleep(wait)
        raise RuntimeError(f"Zhipu failed after 3 attempts: {last_error}")

    def is_healthy(self) -> bool:
        if not self.api_key or not self.api_key.strip():
            return False
        parts = self.api_key.split(".")
        return len(parts) == 2
