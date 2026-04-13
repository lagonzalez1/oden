# prompts/registry.py
from pathlib import Path
from typing import Optional, Dict, Any
from jinja2 import Environment, FileSystemLoader, Template
import logging

logger = logging.getLogger(__name__)

class PromptRegistry:
    """Central registry for managing prompt templates"""
    
    _instance = None
    _templates: Dict[str, Template] = {}
    
    def __new__(cls):
        logger.info("[INFO] call stack PromptRegistry")
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Load all prompt templates and metadata"""
        templates_dir = Path(__file__).parent / "Template"
        
        # Set up Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False
        )
    
    def get_template(self, name: str) -> Optional[Template]:
        """Get a prompt template by name"""
        try:
            if name not in self._templates:
                self._templates[name] = self.env.get_template(f"{name}.j2")
            return self._templates[name]
        except Exception as e:
            logger.error(f"Failed to load template '{name}': {e}")
            return None
    
    def render(self, template_name: str, **kwargs) -> Optional[str]:
        template = self.get_template(template_name)
        if not template:
            return None
        
        try:
            rendered = template.render(**kwargs)
            logger.debug(f"Rendered template '{template_name}'")
            return rendered
        except Exception as e:
            logger.error(f"Failed to render template '{template_name}': {e}")
            return None

# Singleton instance
registry = PromptRegistry()