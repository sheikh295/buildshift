# services/litellm

LiteLLM → **Vercel AI Gateway** (`VERCEL_AI_GATEWAY_API_KEY`).

## Recommended aliases (testing / stretch $5 credits)

| Alias | Upstream | Approx $/1M |
|-------|----------|-------------|
| `minimax-m3.1-flash` | `minimax/minimax-m3.1-flash` | **$0** (default roles) |
| `nemotron-3.5-lightning-free` | `nvidia/nemotron-3.5-lightning-free` | **$0** (use higher max_tokens) |
| `mistral-nemo` | `mistral/mistral-nemo` | ~$0.03 / $0.03 |
| `ling-3.0-flash` | `inclusionai/ling-3.0-flash` | ~$0.02 / $0.06 |
| `qwen3.7-flash` | `alibaba/qwen3.7-flash` | ~$0.03 / $0.13 |
| `gpt-oss-20b` | `openai/gpt-oss-20b` | ~$0.03 / $0.14 |
| `nova-micro` / `nova-lite` | Amazon Nova | ~$0.04–0.06 / $0.14–0.24 |
| `mimo-v2.6-flash` | `xiaomi/mimo-v2.6-flash` | ~$0.14 / $0.28 |
| `gemini-2.5-flash-lite` | Google | ~$0.10 / $0.40 |
| `gemma-4-31b-it` | Google open | ~$0.14 / $0.40 |

Set role → alias in office **Control**. Alias names must match `model_name` above.

## Smoke

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"minimax-m3.1-flash","messages":[{"role":"user","content":"ping"}],"max_tokens":32}'
```
