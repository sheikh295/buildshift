# AGENTS.md — working in this repository

This file is for human contributors and coding agents working on **Buildshift itself**.

## What this repo is

Buildshift turns a large PRD into production web work via planned shifts, isolated worker containers, verification, and pull requests. Design intent lives in `docs/AI-Software-House-Solution.md`.

## Layout rules

- Put runnable apps under `apps/`.
- Put container images and sidecar config under `services/`.
- Put shared importable code under `packages/` (create a real package when a second consumer appears; do not invent premature shared layers).
- Keep operator docs in `docs/`.
- Never commit secrets. Use `.env.example` as the contract.

## Engineering constraints

- Git is the memory for target product repos; Postgres holds orchestrator state.
- Deterministic checks before LLM review.
- Agents working on *target* products must not touch `main`; same discipline here unless a maintainer merges.
- Prefer small modules with clear boundaries over a single mega-package.
- Cost and kill-switch controls are first-class; do not bypass them in “just for now” paths.

## Core scope reminder

Ship: Compose up/down, task state machine, runner (worktree → worker → push/PR), budgets, kill switch, mock harness, office HUD (projects / sprints / HITL). Expand scope only when the task explicitly requires it.
