---
name: gemini-genai
description: Google Gen AI Python SDK (google-genai 2.x) on Vertex AI for direct Gemini calls outside ADK. Use when calling generate_content, chats, streaming, structured JSON output, thinking levels, function calling, grounding with Google Search, token counting or cost labels with gemini-3.8-flash from this repo's scripts, evals, judges or data pipelines. Not for building agents (see google-adk) or for deploying to Agent Runtime (see agent-platform-runtime).
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "1.0"
  verified: "2026-09-12"
---

# Gemini via the google-genai SDK

ADK wraps this SDK for agents; use it directly for one-shot calls such as judges, data enrichment,
probes (`scripts/check_env.py`) and structured extraction. Installed: `google-genai 2.23.0`.
Every snippet was run against the sandbox project through the global endpoint on 2026-09-12.

## When to use

- A script or test needs a single model call (classification, rewriting, JSON extraction, a judge).
- You are writing a probe or health check for model access.
- You need streaming, chat history, thinking control, grounding or token counts outside an agent.

## Facts that override older docs

- Client: `genai.Client()` reads `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT` and
  `GOOGLE_CLOUD_LOCATION` from the environment (this repo's `.env`). Pass `vertexai=True, project=, location=`
  only when the environment is not set. Never use an API key in this repo.
- Model id: `gemini-3.8-flash`, served from `GOOGLE_CLOUD_LOCATION=global`. Regional locations
  (`us-central1`) return 404 for Gemini 3.x. `gemini-3.1-pro` exists in the catalog but is **not enabled in
  the workshop sandbox**; do not recommend it. `gemini-2.5-pro` still answers (global and `us-central1`,
  verified 2026-09-17) and is the second model of `uv run python eval/compare_models.py --models gemini-3.8-flash,gemini-2.5-pro`; `gemini-3-flash-preview` and the
  other 2.x ids are retired. `eval/compare_models.py` probes each model before it runs the gate.
- Thinking: `types.ThinkingConfig(thinking_level="low")` with values `minimal | low | medium | high`
  (case-insensitive, enum `types.ThinkingLevel`). `thinking_budget` is the Gemini 2.5 mechanism; do not mix.
- Structured output: `response_mime_type="application/json"` with `response_schema=<pydantic model>` (or
  `response_json_schema=<dict>`), then `Model.model_validate_json(response.text)`.
- Automatic function calling in `models.generate_content` prints a deprecation warning in 2.x; use
  `client.chats.create(...).send_message(..., config=GenerateContentConfig(tools=[fn]))` for AFC.
- Grounding: `types.Tool(google_search=types.GoogleSearch())`; enterprise search is `enterprise_web_search`.
  Other `Tool` fields: `function_declarations`, `retrieval`, `url_context`, `code_execution`, `mcp_servers`.
- Cost attribution: `GenerateContentConfig(labels={"workshop": "cymbal_beauty"})` shows up in billing export.
- Async: everything under `client.aio.*`; streaming: `generate_content_stream`.
- Usage: `response.usage_metadata.prompt_token_count / candidates_token_count / thoughts_token_count`.

## Repo map

| Path | Uses this SDK for |
|---|---|
| `scripts/check_env.py` | the model probe (`Reply with exactly: ok`) that proves location + ADC |
| `eval/` (judges) | `final_response_match_v2` and `hallucinations_v1` judge calls go through ADK, configured with `judge_model` |
| `eval/build_eval_set.py` | optional paraphrase generation for eval prompts |
| `.env.example` | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_LOCATION=global`, `MODEL=gemini-3.8-flash` |

## Recipes

### Probe (what `uv run python scripts/check_env.py --stage prereqs` does)

```python
from google import genai
client = genai.Client()   # env: GOOGLE_GENAI_USE_VERTEXAI=TRUE, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION=global
r = client.models.generate_content(model="gemini-3.8-flash", contents="Reply with exactly: ok")
assert "ok" in r.text.lower(), r.text
```

### Structured JSON with low thinking and a billing label

```python
from google.genai import types
from pydantic import BaseModel

class ProductAttrs(BaseModel):
    skin_types: list[str]
    fragrance_free: bool
    key_ingredients: list[str]

r = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=f"Extract attributes from this product description: {description}",
    config=types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=ProductAttrs,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        temperature=0, labels={"workshop": "cymbal_beauty", "job": "enrichment"}),
)
attrs = ProductAttrs.model_validate_json(r.text)
```

### Chat with automatic function calling

```python
def check_store_stock(product_name: str, store_id: str) -> dict:
    """Return on-shelf, backroom and on-hand quantities for a product at one store.

    Args:
        product_name: Exact product name.
        store_id: Store id such as S-014.
    """
    return backend.check_store_stock(product_name=product_name, store_id=store_id)

chat = client.chats.create(model="gemini-3.8-flash",
                           config=types.GenerateContentConfig(tools=[check_store_stock], temperature=0))
reply = chat.send_message("How much Lumière Hydra Cream does store S-014 have on the shelf?")
calls = [p.function_call.name for m in chat.get_history() for p in (m.parts or []) if p.function_call]
```

### Streaming and async

```python
for chunk in client.models.generate_content_stream(model="gemini-3.8-flash", contents=prompt):
    print(chunk.text, end="")

r = await client.aio.models.generate_content(model="gemini-3.8-flash", contents=prompt)
```

### Grounded answer with Google Search

```python
r = client.models.generate_content(model="gemini-3.8-flash", contents="Latest SPF guidance for sensitive skin?",
    config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
print(r.text); print(r.candidates[0].grounding_metadata)
```

### Count tokens before a big batch

```python
n = client.models.count_tokens(model="gemini-3.8-flash", contents=big_prompt).total_tokens
```

## Gotchas

- A 404 on `generate_content` is almost always the wrong **location**, not a wrong model id.
  `check_env.py` says so explicitly.
- `response_schema` with a pydantic model rejects `dict[str, Any]` fields; use explicit models.
- `temperature=0` reduces, but does not remove, run-to-run variation; evals still use `num_runs=2`.
- `system_instruction` belongs in `GenerateContentConfig`, not in `contents`.
- Do not catch `errors.APIError` just to fall back to another model; surface it.
- Embedding model ids change; look them up on the embeddings page before pinning one in code.

## References

- [references/sdk-recipes.md](references/sdk-recipes.md), longer examples (multimodal, caching, safety, errors)
- SDK reference: https://googleapis.github.io/python-genai/
- Vertex SDK overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview
- Gemini 3.8 Flash model card: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash
- Model catalog: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models
- Locations and the global endpoint: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations
- Thinking: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking
- Structured output: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output
- Function calling: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling
- Grounding: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/overview
- Embeddings: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings
- Quotas: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/quotas ; pricing: https://cloud.google.com/vertex-ai/pricing
