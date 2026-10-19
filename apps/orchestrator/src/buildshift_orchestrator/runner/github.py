from __future__ import annotations

import httpx


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


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
    """Create a PR and return its HTML URL. Reuses an open PR for the same head if present."""
    headers = _gh_headers(token)
    base_url = api_url.rstrip("/")
    with httpx.Client(timeout=60.0) as client:
        list_url = f"{base_url}/repos/{repo_full_name}/pulls"
        existing = client.get(list_url, headers=headers, params={"head": head, "state": "open"})
        if existing.status_code < 400:
            for pr in existing.json():
                if pr.get("head", {}).get("ref") == head or pr.get("html_url"):
                    # head filter may be owner:branch; accept first open match by head.ref
                    if pr.get("head", {}).get("ref") == head.split(":")[-1]:
                        return pr["html_url"]
        url = f"{base_url}/repos/{repo_full_name}/pulls"
        payload = {"title": title, "head": head, "base": base, "body": body}
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub PR failed ({resp.status_code}): {resp.text}")
        return resp.json()["html_url"]


def merge_pull_request(
    *,
    api_url: str,
    token: str,
    repo_full_name: str,
    pr_url: str,
    commit_title: str | None = None,
) -> None:
    """Merge an open PR by number extracted from its HTML URL."""
    # https://github.com/owner/repo/pull/123
    try:
        number = int(pr_url.rstrip("/").split("/")[-1])
    except ValueError as exc:
        raise RuntimeError(f"cannot parse PR number from {pr_url}") from exc
    url = f"{api_url.rstrip('/')}/repos/{repo_full_name}/pulls/{number}/merge"
    payload: dict = {"merge_method": "squash"}
    if commit_title:
        payload["commit_title"] = commit_title
    with httpx.Client(timeout=60.0) as client:
        resp = client.put(url, headers=_gh_headers(token), json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub merge failed ({resp.status_code}): {resp.text}")


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
