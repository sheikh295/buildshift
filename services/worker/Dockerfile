FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates curl bash nodejs npm \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /bin/bash buildshift

# OpenCode (default coding harness for LiteLLM / Vercel models)
ARG OPENCODE_VERSION=1.19.3
RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" \
  && opencode --version

# Optional Claude Code CLI for HARNESS=claude (Anthropic-compatible models)
ARG INSTALL_CLAUDE=false
RUN if [ "$INSTALL_CLAUDE" = "true" ]; then \
      npm install -g @anthropic-ai/claude-code; \
    fi

WORKDIR /workspace
COPY entrypoint.sh /usr/local/bin/buildshift-worker
COPY github_proxy.py /usr/local/bin/github_proxy.py
COPY buildshift-fetch /usr/local/bin/buildshift-fetch
RUN chmod +x /usr/local/bin/buildshift-worker /usr/local/bin/github_proxy.py /usr/local/bin/buildshift-fetch

USER buildshift
ENTRYPOINT ["buildshift-worker"]
