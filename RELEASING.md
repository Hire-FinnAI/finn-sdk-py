# Releasing hirefinn

PyPI distribution: `hirefinn`. Import name: `finn`. Publishing runs only from `.github/workflows/release.yml`
through PyPI Trusted Publishing (OIDC); there are no API tokens in this repo or its secrets.

## One-time setup (a person with the PyPI account does this)

1. Sign in to https://pypi.org (turn on 2FA) with the account that will own the project.
2. Account -> Publishing -> "Add a new pending publisher" -> GitHub:
   - PyPI project name: `hirefinn`
   - Owner: `Hire-FinnAI`
   - Repository name: `finn-sdk-py`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
   Done 2026-11-06. A pending publisher does NOT reserve the name: anyone can still register `hirefinn`
   until the first publish creates the project, so publish soon (or upload once by hand) to hold it.
3. GitHub -> repo Settings -> Environments -> `pypi`, deployments limited to tags `v*` (done 2026-11-06).
   Required reviewers are not available for a private repo on the current GitHub plan; until then, anyone
   who can publish a GitHub release can publish to PyPI. Add reviewers if the repo goes public or the plan allows.
4. Optional, for dry runs: the same on https://test.pypi.org (separate account) with environment `testpypi`,
   and create a `testpypi` environment on GitHub.

## Each release

1. On a branch, bump `finn/_version.py` and `version` in `pyproject.toml` (same value), merge to `main`.
2. Optional dry run: Actions -> release -> Run workflow, tick `testpypi`. Check
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ hirefinn`.
3. GitHub -> Releases -> Draft a new release, new tag `vX.Y.Z` on `main` (must equal the package version),
   publish it. The workflow tests, builds, runs `twine check`, then publishes through the `pypi` environment.
4. Check https://pypi.org/p/hirefinn and `pip install hirefinn`.

A version cannot be re-uploaded to PyPI; to fix a bad release, bump the version and release again
(you can yank the bad one on PyPI).

## Local check (no upload)

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' build twine
.venv/bin/pytest
.venv/bin/python -m build && .venv/bin/twine check --strict dist/*
```
