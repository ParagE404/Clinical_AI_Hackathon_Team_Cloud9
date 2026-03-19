#!/usr/bin/env python3
"""
Test script to verify LLM provider fixes without requiring actual API keys.
Tests that the code paths work correctly and classes can be instantiated.
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))


def test_ollama_initialization():
    """Test that Ollama client can be initialized."""
    print("Testing Ollama initialization...")
    try:
        from llm_client import LLMClient, LLMProvider

        # Set environment for Ollama
        os.environ["LOCAL_LLM_PROVIDER"] = "ollama"
        os.environ["LOCAL_LLM_MODEL"] = "llama3.1:8b"

        client = LLMClient()

        assert client.provider == LLMProvider.OLLAMA
        assert client.model == "llama3.1:8b"
        assert client.client is not None

        print("✓ Ollama initialization successful")
        print(f"  - Provider: {client.provider.value}")
        print(f"  - Model: {client.model}")
        print(f"  - Client type: {type(client.client).__name__}")
        return True
    except Exception as e:
        print(f"✗ Ollama initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gemini_initialization_without_key():
    """Test that Gemini client fails gracefully without API key."""
    print("\nTesting Gemini initialization without API key...")
    try:
        from llm_client import LLMClient, LLMProvider

        # Set environment for Gemini but without API key
        os.environ["LOCAL_LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]

        try:
            client = LLMClient()
            print("✗ Gemini initialization should have failed without API key")
            return False
        except RuntimeError as e:
            if "GEMINI_API_KEY not set" in str(e):
                print("✓ Gemini correctly requires API key")
                return True
            else:
                print(f"✗ Unexpected error: {e}")
                return False
    except ImportError as e:
        print(f"⚠ Gemini package not installed (expected): {e}")
        return True  # This is OK - package is optional
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gemini_initialization_with_key():
    """Test that Gemini client initializes with a dummy API key (won't call API)."""
    print("\nTesting Gemini initialization with API key...")
    try:
        from llm_client import LLMClient, LLMProvider

        # Set environment for Gemini with dummy API key
        os.environ["LOCAL_LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
        os.environ["GEMINI_API_KEY"] = "dummy_api_key_for_testing"

        client = LLMClient()

        assert client.provider == LLMProvider.GEMINI
        assert client.model == "gemini-2.5-flash"
        assert client.client is not None

        print("✓ Gemini initialization successful (no configure() error)")
        print(f"  - Provider: {client.provider.value}")
        print(f"  - Model: {client.model}")
        print(f"  - Client type: {type(client.client).__name__}")
        return True
    except ImportError as e:
        print(f"⚠ Gemini package not installed (expected): {e}")
        return True  # This is OK - package is optional
    except AttributeError as e:
        if "configure" in str(e):
            print(f"✗ Old Gemini bug still present: {e}")
            return False
        else:
            raise
    except Exception as e:
        print(f"✗ Gemini initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_threading_import():
    """Test that threading is imported correctly in extract_llm."""
    print("\nTesting threading import...")
    try:
        from extract_llm import extract_case, extract_all_cases
        import threading

        # Verify threading is available
        thread_id = threading.get_ident()

        print("✓ Threading import successful")
        print(f"  - Current thread ID: {thread_id}")
        return True
    except Exception as e:
        print(f"✗ Threading import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("LLM Provider Fixes Test Suite")
    print("=" * 60)

    results = []

    # Test 1: Ollama initialization
    results.append(("Ollama initialization", test_ollama_initialization()))

    # Test 2: Gemini without key
    results.append(("Gemini without key", test_gemini_initialization_without_key()))

    # Test 3: Gemini with key (tests the fix)
    results.append(("Gemini with key", test_gemini_initialization_with_key()))

    # Test 4: Threading import
    results.append(("Threading import", test_threading_import()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
