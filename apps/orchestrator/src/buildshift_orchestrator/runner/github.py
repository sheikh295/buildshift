from __future__ import annotations

import httpx


def open_pull_request(
    *,
    api_url: str,
    token: str,
    repo_full_name: str,
    title: str,
    head: str,
    base: str,
    body: str,
) -> str:
    """Create a PR and return its HTML URL."""
    url = f"{api_url.rstrip('/')}/repos/{repo_full_name}/pulls"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"title": title, "head": head, "base": base, "body": body}
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub PR failed ({resp.status_code}): {resp.text}")
        return resp.json()["html_url"]


def parse_github_repo(clone_url: str) -> str | None:
    """Return owner/repo from common GitHub URL forms, else None."""
    url = clone_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "github.com:" in url:
        # git@github.com:owner/repo
        return url.split("github.com:")[-1]
    if "github.com/" in url:
        return url.split("github.com/")[-1]
    return None
