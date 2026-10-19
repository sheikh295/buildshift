# services/litellm

LiteLLM gateway configuration. One place for model routing, spend tracking, and provider switching.

The Compose service mounts `config.yaml` and reads provider keys from the environment (see root `.env.example`).
