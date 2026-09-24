# google-genai 2.x recipes (Vertex AI, global endpoint)

All examples assume `client = genai.Client()` with the repo `.env` loaded and `MODEL = "gemini-3.8-flash"`.

## Client options

```python
from google import genai
from google.genai import types

client = genai.Client()                                   # from environment (preferred in this repo)
client = genai.Client(vertexai=True, project=PROJECT, location="global",
                      http_options=types.HttpOptions(api_version="v1"))   # explicit
async with genai.Client() as aclient: ...                # context managers close connections
```

## Generation config fields used in the workshop

| Field | Use |
|---|---|
| `system_instruction` | persona and rules for one-shot calls |
| `temperature`, `top_p`, `max_output_tokens`, `seed` | determinism for judges and enrichment |
| `thinking_config=ThinkingConfig(thinking_level=..., include_thoughts=False)` | reasoning effort on Gemini 3.x |
| `response_mime_type`, `response_schema` / `response_json_schema` | structured output |
| `tools`, `tool_config`, `automatic_function_calling` | function calling and grounding |
| `labels` | cost attribution in billing export |
| `safety_settings` | per-category thresholds |
| `cached_content` | context caching handle |

## Multimodal input from Cloud Storage

```python
r = client.models.generate_content(model=MODEL, contents=[
    types.Part.from_uri(file_uri="gs://bucket/shade-swatch.png", mime_type="image/png"),
    "Name the dominant shade family and finish."])
```

Use `types.Part.from_bytes(data=..., mime_type=...)` for local files; the Files API (`client.files`) is
Gemini Developer API only and is not available on Vertex.

## Manual function declarations (when you do not want AFC)

```python
tool = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="check_store_stock", description="On-shelf, backroom and on-hand quantities for a product at one store",
    parameters=types.Schema(type=types.Type.OBJECT,
        properties={"product_name": types.Schema(type=types.Type.STRING),
                    "store_id": types.Schema(type=types.Type.STRING)},
        required=["product_name", "store_id"]))])
r = client.models.generate_content(model=MODEL, contents=prompt,
    config=types.GenerateContentConfig(tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
call = next(p.function_call for p in r.candidates[0].content.parts if p.function_call)
result = check_store_stock(**call.args)
follow_up = client.models.generate_content(model=MODEL, contents=[
    r.candidates[0].content,
    types.Content(role="user", parts=[types.Part.from_function_response(name=call.name, response=result)])],
    config=types.GenerateContentConfig(tools=[tool]))
```

## Context caching for a large stable prefix

```python
cache = client.caches.create(model=MODEL, contents=[catalog_text],
    config=types.CreateCachedContentConfig(display_name="cymbal-catalog", ttl="3600s"))
r = client.models.generate_content(model=MODEL, contents="Which cleansers are fragrance-free?",
    config=types.GenerateContentConfig(cached_content=cache.name))
```

Caching has a minimum token count per model; check the model card before relying on it.

## Safety settings

```python
config = types.GenerateContentConfig(safety_settings=[types.SafetySetting(
    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)])
```

## Error handling that stays loud

```python
from google.genai import errors
try:
    r = client.models.generate_content(model=MODEL, contents=prompt)
except errors.APIError as e:
    raise SystemExit(f"Gemini call failed: {e.code} {e.message} (check GOOGLE_CLOUD_LOCATION=global and ADC)") from e
```

Do not retry on 404 (it is a configuration error) and do not swap models on 429; raise, let the caller
decide, and read the quotas page for the `global` endpoint limits.

## Listing models the project can see

```python
for m in client.models.list():
    if "gemini-3" in m.name:
        print(m.name)
```

## Judge pattern used by the evals

ADK's `final_response_match_v2` and `hallucinations_v1` build their own judge calls; configure them with
`judge_model_options` in `test_config.json`. When writing an ad-hoc judge, use `temperature=0`,
`thinking_level="low"`, a `response_schema` with a `score: int` and `reason: str`, and sample it 3 times.
