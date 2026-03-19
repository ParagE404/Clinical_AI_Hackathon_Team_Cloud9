#!/usr/bin/env python3
"""
verify_ollama_setup.py — Verify Ollama installation and configuration.

This script checks:
1. Ollama service is running
2. Required model is available
3. LLM client can successfully generate responses
4. Environment variables are properly configured

Run this before starting the main pipeline to ensure everything is set up correctly.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from llm_client import LLMClient, LLMProvider
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Error importing dependencies: {e}")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)


def check_env_vars():
    """Check if environment variables are properly set."""
    print("=" * 60)
    print("1. Checking Environment Variables")
    print("=" * 60)

    load_dotenv()

    provider = os.getenv("LOCAL_LLM_PROVIDER", "ollama")
    print(f"✅ LOCAL_LLM_PROVIDER: {provider}")

    if provider == "ollama":
        model = os.getenv("LOCAL_LLM_MODEL", "llama3.1:8b")
        base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        temp = os.getenv("LOCAL_LLM_TEMPERATURE", "0.0")

        print(f"✅ LOCAL_LLM_MODEL: {model}")
        print(f"✅ LOCAL_LLM_BASE_URL: {base_url}")
        print(f"✅ LOCAL_LLM_TEMPERATURE: {temp}")

        return True, provider, model, base_url

    elif provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        if not api_key:
            print("❌ GEMINI_API_KEY not set")
            return False, provider, model, None

        print(f"✅ GEMINI_API_KEY: {'*' * 20} (hidden)")
        print(f"✅ GEMINI_MODEL: {model}")
        print("⚠️  WARNING: Gemini is cloud-based (NOT hackathon compliant)")

        return True, provider, model, None

    else:
        print(f"❌ Unknown provider: {provider}")
        return False, provider, None, None


def check_ollama_service(base_url):
    """Check if Ollama service is running."""
    print("\n" + "=" * 60)
    print("2. Checking Ollama Service")
    print("=" * 60)

    import requests

    try:
        # Remove /v1 suffix to get base Ollama API URL
        ollama_base = base_url.replace("/v1", "")
        response = requests.get(f"{ollama_base}/api/tags", timeout=5)

        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            print(f"✅ Ollama service is running at {ollama_base}")
            print(f"✅ Found {len(models)} model(s) installed:")

            for model in models:
                name = model.get("name", "unknown")
                size_gb = model.get("size", 0) / (1024**3)
                print(f"   - {name} ({size_gb:.1f} GB)")

            return True, models
        else:
            print(f"❌ Ollama service returned status code: {response.status_code}")
            return False, []

    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Ollama at {ollama_base}")
        print("   Make sure Ollama is running: ollama serve")
        return False, []

    except Exception as e:
        print(f"❌ Error checking Ollama service: {e}")
        return False, []


def check_model_availability(required_model, available_models):
    """Check if the required model is available."""
    print("\n" + "=" * 60)
    print("3. Checking Model Availability")
    print("=" * 60)

    if not available_models:
        print(f"❌ No models available")
        print(f"   Run: ollama pull {required_model}")
        return False

    # Extract model names (handle tags like "llama3.1:8b")
    model_names = [m.get("name", "") for m in available_models]

    if required_model in model_names:
        print(f"✅ Required model '{required_model}' is available")

        # Check model size
        for m in available_models:
            if m.get("name") == required_model:
                size_gb = m.get("size", 0) / (1024**3)
                print(f"   Model size: {size_gb:.1f} GB")

                if size_gb > 5.0:
                    print(f"   ⚠️  WARNING: Model size exceeds 5GB (hackathon limit)")
                else:
                    print(f"   ✅ Model size is within hackathon limit (≤5GB)")

        return True
    else:
        print(f"❌ Required model '{required_model}' not found")
        print(f"   Available models: {', '.join(model_names)}")
        print(f"   Run: ollama pull {required_model}")
        return False


def test_llm_generation():
    """Test LLM generation with a simple prompt."""
    print("\n" + "=" * 60)
    print("4. Testing LLM Generation")
    print("=" * 60)

    try:
        client = LLMClient()
        print(f"✅ LLM client initialized: {client}")

        # Simple test prompt
        test_prompt = 'Return JSON: {"status": "working", "message": "LLM is functional"}'

        print("   Testing with simple JSON generation prompt...")
        response = client.generate(
            prompt=test_prompt,
            system_instruction="You are a helpful assistant. Always return valid JSON.",
            json_mode=True
        )

        response_text = response.get("text", "")
        print(f"✅ LLM responded successfully")
        print(f"   Response: {response_text[:100]}...")

        # Try to parse JSON
        import json
        try:
            data = json.loads(response_text)
            print(f"✅ Response is valid JSON")
            print(f"   Parsed data: {data}")
        except json.JSONDecodeError:
            print(f"⚠️  Response is not valid JSON (this may cause issues)")

        # Check token usage
        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        if prompt_tokens > 0 or completion_tokens > 0:
            print(f"   Token usage: {prompt_tokens} prompt + {completion_tokens} completion")

        return True

    except Exception as e:
        print(f"❌ Error testing LLM generation: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks."""
    print("\n🔍 Ollama Setup Verification")
    print("=" * 60)

    # Check 1: Environment variables
    env_ok, provider, model, base_url = check_env_vars()

    if not env_ok:
        print("\n❌ Environment configuration failed")
        print("   Create a .env file with proper configuration")
        print("   See .env.example for reference")
        sys.exit(1)

    # Check 2: Ollama service (skip for Gemini)
    if provider == "ollama":
        service_ok, models = check_ollama_service(base_url)

        if not service_ok:
            print("\n❌ Ollama service check failed")
            sys.exit(1)

        # Check 3: Model availability
        model_ok = check_model_availability(model, models)

        if not model_ok:
            print("\n❌ Required model not available")
            sys.exit(1)

    # Check 4: Test generation
    gen_ok = test_llm_generation()

    if not gen_ok:
        print("\n❌ LLM generation test failed")
        sys.exit(1)

    # All checks passed
    print("\n" + "=" * 60)
    print("✅ ALL CHECKS PASSED")
    print("=" * 60)
    print(f"✅ Provider: {provider}")
    print(f"✅ Model: {model}")
    print("✅ LLM is ready for use")
    print("\nYou can now run:")
    print("  - python main.py")
    print("  - streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
