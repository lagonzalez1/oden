import json
import logging
from typing import Optional, Any
from ollama import chat, ChatResponse
from pydantic import BaseModel, ValidationError
from ollama import Client

logger = logging.getLogger(__name__)

class LamaModel:
    def __init__(self, response_validator: Optional[BaseModel], prompt_data: Optional[dict]):
        logger.info("[INFO] Initializing LamaModel")
        self.prompt_data = prompt_data or {}
        self.client = Client(host='http://host.docker.internal:11434')
        self.response_validator = response_validator
        self.response_metadata: Optional[dict] = None

    def _invoke_model(self) -> Optional[dict]:
        try:
            messages = self.prompt_data.get("messages", [])
            model_name = self.prompt_data.get("model", "llama3")
            
            # 1. Extract Schema: Ollama accepts JSON schema to constrain output
            schema = self.response_validator.model_json_schema() if self.response_validator else None

            # 2. Invoke chat: Note that we pass 'format' here to the library
            # We use the actual response object returned by the ollama-python library
            response = self.client.chat(
                model=model_name,
                messages=messages,
                format=schema, # This ensures the model follows your Pydantic structure
                options={
                    "temperature": self.prompt_data.get("temperature", 0.7),
                },
            )
        
            if not response or not response.message.content:
                logger.error("[ERROR OLLAMA] Empty response from model.")
                return None

            # 3. Store metadata for usage tracking later
            # Ollama uses 'prompt_eval_count' and 'eval_count'
            self.response_metadata = response.model_dump()

            raw_content = response.message.content
            logger.info(f"[INFO OLLAMA] Raw Content: {raw_content}")

            # 4. Validation
            if self.response_validator:
                validated_data = self.response_validator.model_validate_json(raw_content)
                return validated_data.model_dump()
            
            return {"content": raw_content}

        except ValidationError as e:
            logger.error(f"[ERROR] Pydantic Validation failed: {e}")
            raise
        except Exception as e:
            logger.error(f"[ERROR] Exception during model invocation: {e}")
            raise

    def get_usage(self) -> Optional[dict]:
        """
        Ollama specific token usage mapping.
        """
        if not self.response_metadata:
            return None
        
        try:
            # Ollama field names:
            # prompt_eval_count = input tokens
            # eval_count = output tokens
            prompt_tokens = self.response_metadata.get("prompt_eval_count", 0)
            output_tokens = self.response_metadata.get("eval_count", 0)
            
            return {
                "input_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "total_tokens": prompt_tokens + output_tokens,
            }
        except Exception as e:
            logger.error(f"Unable to parse usage: {e}")
            return None