from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator
import logging

logger = logging.getLogger(__name__)

class PromptConfig(BaseModel):
    """Configuration for building a prompt"""
    template_name: str
    model: str
    variables: Dict[str, Any]
    images: List[str] = None 
    system_variables: Dict[str, Any]
    system_template_name: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = None
    
    @field_validator('temperature')
    def validate_temperature(cls, v):
        if v is not None and not (0 <= v <= 2):
            raise ValueError('Temperature must be between 0 and 2')
        return v

class PromptBuilder:
    """Build prompts with validation and formatting"""
    def __init__(self, registry=None):
        logger.info("[INFO] call stack PromptBuilder")
        from Prompts.Registry import registry as default_registry
        self.registry = registry or default_registry
    
    def __del__(self):
        pass
    
    def build(self, config: PromptConfig) -> Optional[Dict[str, Any]]:
        try:
            """
            Build a complete prompt from config.
            Returns:
                Dict with 'messages', 'max_tokens', 'temperature', etc.
            """
            # Render user prompt 
            user_prompt = self.registry.render(
                config.template_name,
                **config.variables
            )
            
            if not user_prompt:
                logger.error(f"[ERROR]Failed to render template: {config.template_name}")
                return None
            # Render system prompt
            system_prompt = self.registry.render(
                config.system_template_name,
                **config.system_variables
            )
            if not system_prompt:
                logger.error(f"[ERROR]Failed to render template: {config.system_template_name}")
                return None
            
            # Build messages
            messages = []
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt,
                })
            
            messages.append({
                "role": "user",
                "content":  user_prompt,
            })

            if config.images:
                for i in range(len(config.images)):
                    messages.append({
                        "role": "user",
                        "content":  "What is this image",
                        "image": [config.images[i]]
                    })
            
            return {
                "messages": messages,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "model": config.model
            }
        except Exception as e:
            logger.error(f"[ERROR Builder.py] Error on build func {e}")
            return None
    
    def build_from_dict(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build prompt from dictionary"""
        try:
            config = PromptConfig(**data)
            return self.build(config)
        except Exception as e:
            logger.error(f"Failed to build prompt from dict: {e}")
            return None