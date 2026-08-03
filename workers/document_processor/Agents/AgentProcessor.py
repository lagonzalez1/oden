import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from Prompts.Builder import PromptBuilder, PromptConfig
from LLM.DocumentValidator import FilingExtraction
from LLM.LocalModel import LocalModel

logger = logging.getLogger(__name__)

# Variables binder: receives run context, returns PromptConfig.variables
VariablesBinder = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class AgentConfig:
    """Runtime knobs for model calls and multi-step prompt pipelines."""
    model: str = "qwen3.5"
    max_tokens: int = 80000
    temperature: float = 0.1
    max_retries: int = 3
    base_delay: float = 2.0
    exponential_base: float = 2.0


@dataclass
class PromptStep:
    """
    One PromptBuilder invocation in a pipeline.

    Each step owns its own template_name / system_template_name / variables.
    Use `bind` to derive variables from prior step output (and original text).
    """
    name: str
    template_name: str
    system_template_name: str = "system"
    system_variables: Dict[str, Any] = field(default_factory=lambda: {"dummy_key": None})
    # Optional overrides for this step only
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    # context -> variables dict for PromptConfig
    bind: Optional[VariablesBinder] = None


@dataclass
class AgentStepResult:
    """Record of one completed (or failed) pipeline step."""
    step_index: int
    name: str
    prompt_data: Dict[str, Any]
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def _bind_extract(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {"text": ctx["text"]}


def _bind_correct(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "text": ctx["text"],
        "extracted_json": json.dumps(ctx["last_response"], indent=2),
    }


# Default filing pipeline: extract → correct
FILING_PIPELINE: List[PromptStep] = [
    PromptStep(
        name="extract",
        template_name="reader_identity",
        system_template_name="system",
        bind=_bind_extract,
        temperature=0.2,
    ),
    PromptStep(
        name="correct",
        template_name="corrector_prompt",
        system_template_name="system",
        bind=_bind_correct,
        temperature=0.1,
    ),
]


class AgentProcessor:
    """
    Ollama-backed agent runner driven by a PromptStep pipeline.

    Flow:
      run(text)
        → for each PromptStep:
            PromptBuilder(PromptConfig(...))  # step-specific templates/vars
            → LocalModel invoke (with retry)
            → stash response on context for the next step's bind()
        → return final step response
    """

    def __init__(
        self,
        response_schema: Type[BaseModel] = FilingExtraction,
        config: Optional[AgentConfig] = None,
        builder: Optional[PromptBuilder] = None,
        steps: Optional[List[PromptStep]] = None,
    ):
        self.response_schema = response_schema
        self.config = config or AgentConfig()
        self.builder = builder or PromptBuilder()
        self.steps_spec = steps or FILING_PIPELINE
        self.messages: List[Dict[str, Any]] = []
        self.step_results: List[AgentStepResult] = []

    def _build_prompt(self, step: PromptStep, variables: Dict[str, Any]) -> Dict[str, Any]:
        prompt_config = PromptConfig(
            template_name=step.template_name,
            system_template_name=step.system_template_name,
            system_variables=step.system_variables,
            model=step.model or self.config.model,
            variables=variables,
            max_tokens=step.max_tokens if step.max_tokens is not None else self.config.max_tokens,
            temperature=(
                step.temperature if step.temperature is not None else self.config.temperature
            ),
        )
        prompt_data = self.builder.build(prompt_config)
        if not prompt_data:
            raise ValueError(
                f"Failed to build prompt for step={step.name} template={step.template_name}"
            )
        return prompt_data

    def _invoke(self, prompt_data: Dict[str, Any]) -> Dict[str, Any]:
        model = LocalModel(self.response_schema, prompt_data)
        response = model._invoke_model()
        if not response or not isinstance(response, dict):
            raise ValueError(f"Invalid response from model: {response}")
        return response

    async def _with_retry(self, fn: Callable[[], Any]) -> Any:
        last_exception: Optional[Exception] = None
        for attempt in range(self.config.max_retries):
            try:
                return await asyncio.to_thread(fn)
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"[AgentProcessor] Attempt {attempt + 1}/{self.config.max_retries} failed: {e}"
                )
                if attempt < self.config.max_retries - 1:
                    delay = (
                        self.config.base_delay
                        * (self.config.exponential_base ** attempt)
                        + random.uniform(0, 1)
                    )
                    logger.info(f"[AgentProcessor] Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)

        logger.error(f"[AgentProcessor] All {self.config.max_retries} attempts failed")
        raise last_exception

    async def _run_step(
        self,
        step: PromptStep,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build PromptConfig for this step → invoke → record result on context."""
        binder = step.bind or _bind_extract
        variables = binder(context)
        prompt_data = self._build_prompt(step, variables)

        self.messages = list(prompt_data.get("messages", []))
        result = AgentStepResult(
            step_index=len(self.step_results),
            name=step.name,
            prompt_data=prompt_data,
        )
        self.step_results.append(result)

        logger.info(
            f"[AgentProcessor] Running step '{step.name}' "
            f"(template={step.template_name}, system={step.system_template_name})"
        )

        try:
            response = await self._with_retry(lambda: self._invoke(prompt_data))
            result.response = response
            self.messages.append({"role": "assistant", "content": response})
            context["last_response"] = response
            context["responses"].append(response)
            return response
        except Exception as e:
            result.error = str(e)
            raise

    async def run(
        self,
        text: Optional[str],
        steps: Optional[List[PromptStep]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a PromptStep pipeline.

        Args:
            text: Source document text
            steps: Optional override pipeline; defaults to self.steps_spec (extract → correct)
        """
        if not text:
            return None

        pipeline = steps or self.steps_spec
        self.step_results = []
        self.messages = []
        context: Dict[str, Any] = {
            "text": text,
            "last_response": None,
            "responses": [],
        }

        try:
            response: Optional[Dict[str, Any]] = None
            for step in pipeline:
                response = await self._run_step(step, context)
            return response
        except Exception as e:
            logger.warning(f"[AgentProcessor] Pipeline failed: {e}")
            return None
