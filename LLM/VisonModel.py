import json
import logging
from typing import Optional
import ollama
import requests
from pydantic import BaseModel, ValidationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OLLAMA_BASE_URL="http://host.docker.internal:11434"



class VisionModel:
    def __init__(self, response_validator: Optional[BaseModel], prompt_data: Optional[dict]):
        logger.info("[INFO] call stack init LocalModel")
        self.prompt_data = prompt_data
        self.response_validator = response_validator
        self.response_metadata: Optional[dict] = None
        self.client = ollama.Client(host=OLLAMA_BASE_URL)

    def set_metadata(self, metadata: Optional[dict]):
        self.response_metadata = metadata

    def _invoke_model(self) -> dict:
        try:
            # Keep messages as list of objects — do NOT flatten to string
            # flattening strips the 'images' key needed for vision models
            messages = self.prompt_data.get("messages", [])

            schema = self.response_validator.model_json_schema() if self.response_validator else None

            # ollama.chat takes keyword args directly, NOT a payload dict
            response = self.client.chat(
                model=self.prompt_data.get("model"),
                messages=messages,
                format=schema,
                options={
                    "temperature": self.prompt_data.get("temperature", 0),
                },
            )

            # ollama-python returns an object, NOT a requests.Response
            # access via attribute, not .json()
            raw = response.message.content

            if not raw:
                logger.error("[ERROR OLLAMA] Empty content in message response.")
                return None

            logger.info(f"[INFO OLLAMA] Raw => {raw}")

            # Store token usage metadata
            self.set_metadata({
                "prompt_token_count":     response.prompt_eval_count,
                "candidates_token_count": response.eval_count,
            })

            if self.response_validator:
                validated_data = self.response_validator.model_validate_json(raw)
                return validated_data.model_dump()

            return {"content": raw}

        except ValidationError as e:
            logger.error(f"[ERROR] Validation error on _invoke_model: {e}")
            raise
        except Exception as e:
            logger.error(f"[ERROR] Exception found _invoke_model: {e}")
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