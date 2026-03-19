---
name: LLM Provider Issues
about: Issues with Gemini API configuration and Ollama performance
title: '[BUG] LLM Provider Issues: Gemini API Error & Slow Ollama Extraction'
labels: bug, llm, performance
assignees: ''
---

## 🐛 Bug Description

Multiple issues affecting LLM provider functionality:

1. **Gemini API Error**: `AttributeError: module 'google.genai' has no attribute 'configure'`
2. **Slow Ollama Extraction**: Extremely slow extraction performance when using local Ollama
3. **Unclear Parallelization**: Uncertain whether parallel API calls are working as expected

---

## 🔴 Issue 1: Gemini API Configuration Error

### Error Message
```
Pipeline failed: module 'google.genai' has no attribute 'configure'
AttributeError: module 'google.genai' has no attribute 'configure'
```

### Stack Trace
```
File "/Users/paragdharadhar/Documents/Parag/MS/Hackathon/Clinical_AI_Hackathon_Team_Cloud9/app.py", line 309, in <module>
    extractions = extract_all_cases(cases, batch_delay=0.0, max_workers=max_workers)
File "/Users/paragdharadhar/Documents/Parag/MS/Hackathon/Clinical_AI_Hackathon_Team_Cloud9/extract_llm.py", line 255, in extract_all_cases
    client = LLMClient()
File "/Users/paragdharadhar/Documents/Parag/MS/Hackathon/Clinical_AI_Hackathon_Team_Cloud9/llm_client.py", line 59, in __init__
    self._init_gemini()
File "/Users/paragdharadhar/Documents/Parag/MS/Hackathon/Clinical_AI_Hackathon_Team_Cloud9/llm_client.py", line 91, in _init_gemini
    genai.configure(api_key=api_key)
```

### Root Cause
**File**: `llm_client.py:91`

The code is using an outdated Gemini API pattern. The current implementation attempts:
```python
import google.genai as genai
genai.configure(api_key=api_key)  # ❌ This method doesn't exist
self.client = genai.Client(api_key=api_key)
```

The `google.genai` package (newer SDK) does **not** have a `configure()` method. This is mixing patterns from the older `google.generativeai` package.

### Expected Behavior
- Gemini API should initialize successfully when `LOCAL_LLM_PROVIDER=gemini` is set
- Extraction should proceed without configuration errors

### Actual Behavior
- Pipeline immediately crashes with `AttributeError`
- Cannot use Gemini as LLM provider

---

## 🐌 Issue 2: Slow Ollama Extraction Performance

### Problem Description
When using Ollama as the LLM provider, extraction is extremely slow—taking significantly longer than expected for processing MDT cases.

### Context
- **Model**: `llama3.1:8b` (default)
- **Endpoint**: `http://localhost:11434/v1`
- **Parallelization**: `max_workers=5` (default in UI)

### Observed Behavior
- Extraction takes an unreasonably long time per case
- Progress appears slower than serial processing would suggest
- Unclear if parallelization is actually working

### Potential Causes
1. **Single Client Instance**: `LLMClient()` is instantiated once in `extract_all_cases()` (line 255) and shared across all worker threads. This may cause:
   - Thread contention on the OpenAI client
   - Serialized requests despite ThreadPoolExecutor usage

2. **Ollama Concurrency Limitations**: Local Ollama may not handle concurrent requests efficiently:
   - Single-threaded model inference
   - Resource contention (CPU/GPU)
   - Queue-based processing

3. **Large Prompt Size**: The extraction prompts include:
   - Full case text (can be 2000+ words)
   - 88 field definitions in system instruction
   - JSON schema requirements
   - This results in high token counts per request

4. **Model Performance**: `llama3.1:8b` may be inherently slower for complex structured extraction tasks

---

## ❓ Issue 3: Parallelization Verification

### Uncertainty
**Question**: Is the parallel API call implementation actually working?

### Current Implementation
**File**: `extract_llm.py:239-293`

```python
def extract_all_cases(
    cases: list[CaseText],
    batch_delay: float = 0.0,
    max_workers: int = 5,
) -> list[CaseResult]:
    # Single client instance created
    client = LLMClient()  # ⚠️ Shared across threads

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(extract_case, case, client): (i, case)
            for i, case in enumerate(cases)
        }

        for future in as_completed(futures):
            # Process results...
```

**Observations**:
- ✅ Uses `ThreadPoolExecutor` with configurable `max_workers`
- ✅ Submits all cases concurrently
- ✅ Processes results as they complete
- ⚠️ Shares single `LLMClient` instance across threads
- ⚠️ `batch_delay` parameter is deprecated/unused

### Questions
1. Does the shared `LLMClient` instance create a bottleneck?
2. Are requests actually sent in parallel, or serialized internally?
3. How can we verify parallel execution is working?

---

## 🔍 Environment

- **OS**: macOS (Darwin 25.3.0)
- **Python Version**: [Please specify]
- **Branch**: `PR7`
- **LLM Providers**:
  - Ollama: `llama3.1:8b` @ `http://localhost:11434/v1`
  - Gemini: `gemini-2.5-flash` (non-functional)
- **Packages**:
  - `openai` (for Ollama compatibility)
  - `google-genai` (for Gemini)

---

## 🎯 Expected Solutions

### Fix 1: Gemini API Configuration
Update `llm_client.py` to use correct Gemini SDK initialization:

**Option A**: Use `google-generativeai` (older, stable SDK)
```python
import google.generativeai as genai
genai.configure(api_key=api_key)
self.client = genai.GenerativeModel(self.model)
```

**Option B**: Use `google.genai` correctly (newer SDK)
```python
import google.genai as genai
self.client = genai.Client(api_key=api_key)
# No configure() needed
```

### Fix 2: Improve Ollama Performance

**Option A**: Per-thread Client Instances
```python
# Create client per thread to avoid contention
def extract_case_with_client(case: CaseText) -> CaseResult:
    client = LLMClient()  # New instance per thread
    return extract_case(case, client)
```

**Option B**: Connection Pool
```python
# Use connection pooling for better concurrency
from openai import OpenAI
self.client = OpenAI(
    base_url=base_url,
    api_key="ollama",
    max_retries=3,
    timeout=60.0,
)
```

**Option C**: Async Implementation
```python
# Use async/await for true concurrency
import asyncio
from openai import AsyncOpenAI

async def extract_case_async(case, client):
    # Async extraction logic
```

### Fix 3: Parallelization Verification

Add logging/timing to confirm parallel execution:
```python
import time
import threading

def extract_case(case: CaseText, client: LLMClient, max_retries: int = 2) -> CaseResult:
    thread_id = threading.get_ident()
    start_time = time.time()

    print(f"[Thread {thread_id}] Starting case {case.case_index}")
    # ... extraction logic ...

    elapsed = time.time() - start_time
    print(f"[Thread {thread_id}] Completed case {case.case_index} in {elapsed:.2f}s")
```

---

## 📋 Reproduction Steps

### For Gemini Error:
1. Set `LOCAL_LLM_PROVIDER=gemini` in `.env` or Streamlit sidebar
2. Provide valid `GEMINI_API_KEY`
3. Upload MDT DOCX file
4. Click "Run Pipeline"
5. **Result**: Immediate crash with `AttributeError`

### For Ollama Slowness:
1. Ensure Ollama is running: `ollama serve`
2. Pull model: `ollama pull llama3.1:8b`
3. Set `LOCAL_LLM_PROVIDER=ollama` in Streamlit
4. Upload MDT DOCX file with multiple cases (e.g., 5+ cases)
5. Set `max_workers=5` or higher
6. Click "Run Pipeline"
7. **Observe**: Very slow extraction progress (e.g., >30s per case)

---

## 🔧 Acceptance Criteria

- [ ] Gemini provider initializes without errors
- [ ] Extraction completes successfully with both Ollama and Gemini
- [ ] Ollama extraction performance is acceptable (e.g., <10s per case for llama3.1:8b)
- [ ] Parallel processing is verified to be working (via logs or metrics)
- [ ] Documentation updated with performance benchmarks and recommended configurations

---

## 📚 Additional Context

### Related Files
- `llm_client.py` (lines 76-93) - Gemini initialization
- `extract_llm.py` (lines 239-293) - Parallel extraction logic
- `app.py` (lines 305-314) - Pipeline execution

### Migration History
This project recently migrated from Gemini API to local Ollama (see `MIGRATION.md`). The Gemini code path may have been broken during refactoring.

### Performance Baseline
- **Expected**: ~5-10 seconds per case with llama3.1:8b
- **Actual**: >30 seconds per case
- **Suspected Issue**: Lack of true parallelization or model bottleneck

---

## 💡 Suggested Investigation Steps

1. **Test Gemini Fix**:
   - Try both `google-generativeai` and `google.genai` SDKs
   - Verify API calls work with simple test script
   - Check for API version compatibility

2. **Profile Ollama Performance**:
   - Add timing logs to each extraction step
   - Monitor Ollama server logs during extraction
   - Test with different `max_workers` values (1, 3, 5, 10)
   - Check CPU/GPU utilization during extraction

3. **Verify Parallelization**:
   - Add thread ID logging to confirm concurrent execution
   - Compare wall-clock time vs. sum of individual extraction times
   - Test with smaller cases to isolate model inference time

4. **Benchmark Alternative Models**:
   - Try faster models: `mistral:7b`, `qwen3.5:9b`
   - Compare structured output capabilities
   - Evaluate speed vs. accuracy tradeoff

---

## 🏷️ Labels
- `bug`: Confirmed Gemini error
- `performance`: Slow Ollama extraction
- `llm`: LLM provider-related
- `needs-investigation`: Parallelization verification
- `high-priority`: Blocks cloud-based testing

---

## 📝 Notes

- **Gemini is NOT allowed for hackathon submission** (cloud-based), but fixing it enables testing/development
- Ollama performance is critical since it's the only hackathon-compliant option
- Consider adding provider benchmarks to documentation
