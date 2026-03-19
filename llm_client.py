"""
llm_client.py — Unified LLM client supporting local (Ollama) and cloud (Gemini) providers.

This abstraction layer allows the application to switch between different LLM providers
without changing the core extraction and validation logic.
"""

from __future__ import annotations

import os
from typing import Dict, Any
from enum import Enum
from dotenv import load_dotenv

load_dotenv()


class LLMProvider(Enum):
    """Supported LLM providers."""
    OLLAMA = "ollama"
    GEMINI = "gemini"


class LLMClient:
    """Unified LLM client with support for multiple providers.

    The client automatically selects the provider based on environment variables
    and provides a consistent interface for generating responses with JSON mode support.
    """

    def __init__(self, provider: str = None, model: str = None, temperature: float = None):
        """Initialize the LLM client.

        Args:
            provider: LLM provider name ("ollama" or "gemini"). Defaults to LOCAL_LLM_PROVIDER env var.
            model: Model name. Defaults to LOCAL_LLM_MODEL or GEMINI_MODEL env var depending on provider.
            temperature: Generation temperature. Defaults to LOCAL_LLM_TEMPERATURE or 0.0.
        """
        # Determine provider
        provider_str = provider or os.getenv("LOCAL_LLM_PROVIDER", "ollama")
        self.provider = LLMProvider(provider_str.lower())

        # Determine model based on provider
        if self.provider == LLMProvider.OLLAMA:
            self.model = model or os.getenv("LOCAL_LLM_MODEL", "llama3.1:8b")
        elif self.provider == LLMProvider.GEMINI:
            self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Determine temperature
        if temperature is not None:
            self.temperature = temperature
        else:
            self.temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.0"))

        # Initialize provider-specific client
        if self.provider == LLMProvider.OLLAMA:
            self._init_ollama()
        elif self.provider == LLMProvider.GEMINI:
            self._init_gemini()

    def _init_ollama(self):
        """Initialize Ollama client using OpenAI-compatible API."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "OpenAI package not installed. Run: pip install openai"
            )

        base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        # Configure with reasonable timeout and retries for better reliability
        self.client = OpenAI(
            base_url=base_url,
            api_key="ollama",  # Required but unused for Ollama
            timeout=60.0,  # 60 second timeout for slow local models
            max_retries=2,  # Retry failed requests
        )

    def _init_gemini(self):
        """Initialize Gemini client."""
        try:
            import google.genai as genai
        except ImportError:
            raise ImportError(
                "google-genai package not installed. Run: pip install google-genai"
            )

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Export it or add to .env file."
            )

        # Create client directly - no configure() method in google.genai
        self.client = genai.Client(api_key=api_key)

    def generate(
        self,
        prompt: str,
        system_instruction: str = None,
        json_mode: bool = True
    ) -> Dict[str, Any]:
        """Generate LLM response with unified interface.

        Args:
            prompt: The user prompt/message.
            system_instruction: System instruction for guiding the LLM behavior.
            json_mode: Whether to enforce JSON output format.

        Returns:
            Dict with keys:
                - text: The generated response text
                - usage: Dict with prompt_tokens and completion_tokens (if available)
        """
        if self.provider == LLMProvider.OLLAMA:
            return self._generate_ollama(prompt, system_instruction, json_mode)
        elif self.provider == LLMProvider.GEMINI:
            return self._generate_gemini(prompt, system_instruction, json_mode)

    def _generate_ollama(
        self,
        prompt: str,
        system_instruction: str = None,
        json_mode: bool = True
    ) -> Dict[str, Any]:
        """Generate response using Ollama via OpenAI-compatible API."""
        messages = []

        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        messages.append({"role": "user", "content": prompt})

        # Build request parameters
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        if json_mode:
            params["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**params)

        return {
            "text": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            }
        }

    def _generate_gemini(
        self,
        prompt: str,
        system_instruction: str = None,
        json_mode: bool = True
    ) -> Dict[str, Any]:
        """Generate response using Google Gemini API."""
        config = {
            "temperature": self.temperature,
        }

        if system_instruction:
            config["system_instruction"] = system_instruction

        if json_mode:
            config["response_mime_type"] = "application/json"

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        return {
            "text": response.text,
            "usage": {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
            }
        }

    def __repr__(self):
        return f"LLMClient(provider={self.provider.value}, model={self.model}, temperature={self.temperature})"
