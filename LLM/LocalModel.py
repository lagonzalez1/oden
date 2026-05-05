import json
import logging
from typing import Optional

import requests
from pydantic import BaseModel, ValidationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OLLAMA_BASE_URL="http://host.docker.internal:11434"


class LocalModel:
    def __init__(self, response_validator: Optional[BaseModel], prompt_data: Optional[dict]):
        logger.info("[INFO] call stack init LocalModel")
        self.prompt_data = prompt_data
        self.response_validator = response_validator
        self.response_metadata: Optional[dict] = None

    def set_metadata(self, metadata: Optional[dict]):
        self.response_metadata = metadata

    def _invoke_model(self) -> dict:
        try:
            messages = self.prompt_data.get("messages", [])
            prompt = "\n".join(item["content"] for item in messages)

            schema = self.response_validator.model_json_schema()

            payload = {
                "model": self.prompt_data.get("model"),
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "options": {
                    "temperature": self.prompt_data.get("temperature", 0.7),
                    "num_ctx": 4096,
                },
                "keep_alive": "5m",
            }

            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                timeout=50000,
            )
            response.raise_for_status()

            body = response.json()

            if not body:
                return None

            # qwen3 and other thinking models return JSON in 'thinking' when
            # response is empty — fall back to thinking field if response is blank
            raw = body.get("response") or body.get("thinking") or ""

            if not raw:
                logger.error("[ERROR OLLAMA] Both response and thinking fields are empty.")
                return None

            logger.info(f"[INFO OLLAMA] Successfully invoked model.")
            logger.info(f"[INFO OLLAMA] Raw => {raw}")

            validated_data = self.response_validator.model_validate_json(raw)

            return validated_data.model_dump()

        except ValidationError as e:
            logger.info(f"[ERROR] Validation error on _invoke_model: {e}")
            raise
        except Exception as e:
            logger.info(f"[ERROR] Exception found _invoke_model: {e}")
            raise

    """
        Parse the response metadata according to Ollama API
        link: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-completion
    """
    def get_usage(self) -> Optional[dict]:
        try:
            if self.response_metadata is None:
                return None
            usage = {
                "input_tokens":  self.response_metadata["prompt_token_count"],
                "output_tokens": self.response_metadata["candidates_token_count"],
                "total_tokens":  int(self.response_metadata["prompt_token_count"])
                                 + int(self.response_metadata["candidates_token_count"]),
            }
            return usage
        except (AttributeError, json.JSONDecodeError) as e:
            raise Exception(f"unable to get usage {e}.")