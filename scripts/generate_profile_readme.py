from __future__ import annotations

import collections
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

OWNER = os.getenv('PROFILE_OWNER', 'tchinso')
REPO = os.getenv('PROFILE_REPO', OWNER)
README_PATH = Path('README.md')
TOP_REPOS = 9
TOP_LANGUAGES = 5
TOP_EXTENSIONS = 20
API_ROOT = 'https://api.github.com'


def github_request(url: str) -> object:
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'profile-readme-generator',
    }
    token = os.getenv('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def get_all_repos(owner: str) -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({'per_page': 100, 'page': page, 'type': 'owner', 'sort': 'updated'})
        url = f'{API_ROOT}/users/{owner}/repos?{query}'
        chunk = github_request(url)
        if not isinstance(chunk, list):
            raise RuntimeError(f'Unexpected repo response: {chunk!r}')
        repos.extend(chunk)
        if len(chunk) < 100:
            return repos
        page += 1


def get_languages(owner: str, repo_name: str) -> dict[str, int]:
    data = github_request(f'{API_ROOT}/repos/{owner}/{repo_name}/languages')
    if not isinstance(data, dict):
        raise RuntimeError(f'Unexpected languages response for {repo_name}: {data!r}')
    return {str(k): int(v) for k, v in data.items()}


def get_tree(owner: str, repo_name: str, branch: str) -> list[dict]:
    encoded_branch = urllib.parse.quote(branch, safe='')
    data = github_request(f'{API_ROOT}/repos/{owner}/{repo_name}/git/trees/{encoded_branch}?recursive=1')
    if not isinstance(data, dict):
        raise RuntimeError(f'Unexpected tree response for {repo_name}: {data!r}')
    tree = data.get('tree', [])
    if not isinstance(tree, list):
        raise RuntimeError(f'Unexpected tree list for {repo_name}: {tree!r}')
    return [item for item in tree if isinstance(item, dict)]


def format_date(iso_text: str) -> str:
    parsed = dt.datetime.fromisoformat(iso_text.replace('Z', '+00:00'))
    return parsed.strftime('%Y-%m-%d')


def build_mermaid_pie(title: str, items: Iterable[tuple[str, int]]) -> str:
    lines = ['```mermaid', 'pie showData', f'    title {title}']
    for label, value in items:
        lines.append(f'    "{label}" : {value}')
    lines.append('```')
    return '\n'.join(lines)


def build_repo_badge_url(repo_name: str, updated: str) -> str:
    query = urllib.parse.urlencode(
        {
            'label': repo_name,
            'message': f'Updated {updated}',
            'color': '2ea44f',
            'style': 'for-the-badge',
            'logo': 'github',
        }
    )
    return f'https://img.shields.io/static/v1?{query}'


def extension_for(path_text: str) -> str | None:
    name = Path(path_text).name
    if name.startswith('.') and name.count('.') == 1:
        return name
    suffix = Path(path_text).suffix.lower()
    return suffix or None


def generate() -> str:
    repos = [repo for repo in get_all_repos(OWNER) if not repo.get('fork')]
    repos.sort(key=lambda repo: repo.get('pushed_at') or '', reverse=True)

    recent_repos = [repo for repo in repos if str(repo.get('name')) != REPO][:TOP_REPOS]

    language_bytes: collections.Counter[str] = collections.Counter()
    extension_counts: collections.Counter[str] = collections.Counter()

    for repo in repos:
        repo_name = repo['name']
        for language, count in get_languages(OWNER, repo_name).items():
            language_bytes[language] += count

        default_branch = repo.get('default_branch')
        if not default_branch:
            continue
        try:
            tree = get_tree(OWNER, repo_name, default_branch)
        except Exception:
            continue
        for item in tree:
            if item.get('type') != 'blob':
                continue
            path_text = item.get('path')
            if not isinstance(path_text, str):
                continue
            extension = extension_for(path_text)
            if extension:
                extension_counts[extension] += 1

    total_language_bytes = sum(language_bytes.values())
    top_languages = language_bytes.most_common(TOP_LANGUAGES)
    top_extensions = extension_counts.most_common(TOP_EXTENSIONS)

    language_rows = []
    for language, byte_count in top_languages:
        ratio = (byte_count / total_language_bytes * 100) if total_language_bytes else 0
        language_rows.append(f'| {language} | {byte_count:,} | {ratio:.1f}% |')

    extension_rows = []
    for index, (extension, count) in enumerate(top_extensions, start=1):
        extension_rows.append(f'| {index} | `{extension}` | {count:,} |')

    refreshed_at = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    language_mermaid = build_mermaid_pie('Language ratio by bytes across public repositories', top_languages)
    extension_mermaid = build_mermaid_pie('Top file extensions by file count', top_extensions[:8])

    recent_cards: list[str] = []
    for repo in recent_repos:
        name = str(repo['name'])
        url = str(repo['html_url'])
        updated = format_date(str(repo['pushed_at']))
        badge_url = build_repo_badge_url(name, updated)
        recent_cards.append(
            f'<tr><td align="center"><a href="{url}"><img alt="{name}" src="{badge_url}" width="100%" /></a></td></tr>'
        )

    return f"""# 냥캣 (`{OWNER}`) GitHub Profile

> Last refreshed automatically: **{refreshed_at}**

## Recent repositories

<table width="100%">
{chr(10).join(recent_cards)}
</table>

## Language ratio across my repositories

{language_mermaid}

<details>
<summary>언어 비율 표 보기 (접힘)</summary>

| Language | Bytes | Ratio |
| --- | ---: | ---: |
{chr(10).join(language_rows)}

</details>

## Extension ranking

{extension_mermaid}

<details>
<summary>확장자 랭킹 표 보기 (접힘)</summary>

| Rank | Extension | Files |
| --- | --- | ---: |
{chr(10).join(extension_rows)}

</details>

## Live cards

![Profile details](https://github-profile-summary-cards.vercel.app/api/cards/profile-details?username={OWNER}&theme=github_dark)
![Stats](https://github-profile-summary-cards.vercel.app/api/cards/stats?username={OWNER}&theme=github_dark)
"""


def main() -> int:
    content = generate().rstrip() + '\n'
    README_PATH.write_text(content, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
