FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates curl bash \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /bin/bash buildshift

# Optional Claude Code CLI for HARNESS=claude (off by default for fast OSS builds)
ARG INSTALL_CLAUDE=false
RUN if [ "$INSTALL_CLAUDE" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends nodejs npm \
      && npm install -g @anthropic-ai/claude-code \
      && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /workspace
COPY entrypoint.sh /usr/local/bin/buildshift-worker
RUN chmod +x /usr/local/bin/buildshift-worker

USER buildshift
ENTRYPOINT ["buildshift-worker"]
