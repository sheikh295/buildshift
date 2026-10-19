# Security Policy

## Supported versions

Security fixes are applied to the default branch. Pin releases once tagged.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Email the maintainers (see README) with:

- A description of the issue
- Steps to reproduce
- Impact assessment if known

We aim to acknowledge reports within a few business days.

## Hardening notes for operators

- Do not expose the orchestrator API on a public interface. Bind to localhost or a private network (Tailscale / WireGuard).
- Keep `GITHUB_TOKEN` and LLM API keys out of git; use `.env` on the host only.
- Workers receive short-lived, scoped credentials. Never mount long-lived cloud admin keys into worker containers.
- Review `docs/RUNBOOK.md` before running on a VPS.
