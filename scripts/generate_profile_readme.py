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
TOP_REPOS = 10
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


def build_mermaid(items: Iterable[tuple[str, int]]) -> str:
    lines = ['```mermaid', 'pie showData', '    title Language ratio by bytes across public repositories']
    for label, value in items:
        lines.append(f'    "{label}" : {value}')
    lines.append('```')
    return '\n'.join(lines)


def extension_for(path_text: str) -> str | None:
    name = Path(path_text).name
    if name.startswith('.') and name.count('.') == 1:
        return name
    suffix = Path(path_text).suffix.lower()
    return suffix or None


def generate() -> str:
    repos = [repo for repo in get_all_repos(OWNER) if not repo.get('fork')]
    repos.sort(key=lambda repo: repo.get('pushed_at') or '', reverse=True)

    recent_repos = repos[:TOP_REPOS]

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

    recent_lines = [
        f"{index}. [{repo['name']}]({repo['html_url']}) — Updated **{format_date(repo['pushed_at'])}**"
        for index, repo in enumerate(recent_repos, start=1)
    ]

    language_rows = []
    for language, byte_count in top_languages:
        ratio = (byte_count / total_language_bytes * 100) if total_language_bytes else 0
        language_rows.append(f'| {language} | {byte_count:,} | {ratio:.1f}% |')

    extension_rows = []
    for index, (extension, count) in enumerate(top_extensions, start=1):
        extension_rows.append(f'| {index} | `{extension}` | {count:,} |')

    refreshed_at = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    mermaid = build_mermaid(top_languages)

    return f"""# 냥캣 (`{OWNER}`) GitHub Profile

> Last refreshed automatically: **{refreshed_at}**
>
> 이 README는 GitHub API 기반으로 자동 생성됩니다. 하드코딩 대신 **최근 저장소 / 언어 비율 / 확장자 랭킹**을 주기적으로 다시 계산합니다.

## Recent repositories

최근 `pushed_at` 기준으로 가장 최근에 수정되거나 반영된 공개 저장소 10개입니다.

{chr(10).join(recent_lines)}

## Language ratio across my repositories

> 기준: 내 공개 저장소 전체의 GitHub `languages` API 값을 합산한 **바이트 수 기준** 집계입니다.

| Language | Bytes | Ratio |
| --- | ---: | ---: |
{chr(10).join(language_rows)}

{mermaid}

## Extension ranking

> 기준: 내 공개 저장소의 기본 브랜치를 재귀적으로 스캔해 파일 확장자 개수를 집계했습니다.

| Rank | Extension | Files |
| --- | --- | ---: |
{chr(10).join(extension_rows)}

## Live cards

![GitHub stats](https://github-readme-stats.vercel.app/api?username={OWNER}&show_icons=true&theme=transparent)
![Top languages](https://github-readme-stats.vercel.app/api/top-langs/?username={OWNER}&layout=compact&theme=transparent)

## Notes

- 프로필 README 단독 Markdown만으로는 GitHub 내부 데이터를 실시간 계산할 수 없어서, **GitHub Actions가 주기적으로 README를 재생성**하도록 구성했습니다.
- 최근 저장소는 `pushed_at`, 언어 비율은 `languages` API, 확장자 랭킹은 기본 브랜치의 Git tree 재귀 조회 결과를 사용합니다.
- 이 저장소가 `{OWNER}/{REPO}` 프로필 저장소라면, Actions가 실행될 때마다 프로필 화면도 함께 최신 상태로 유지됩니다.
"""


def main() -> int:
    content = generate().rstrip() + '\n'
    README_PATH.write_text(content, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
