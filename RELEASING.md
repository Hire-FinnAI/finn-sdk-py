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
   This reserves the name; the project is created on the first successful publish.
3. GitHub -> repo Settings -> Environments -> New environment `pypi`. Add required reviewers so every
   publish waits for an approval, and limit deployment tags to `v*`.
4. Optional, for dry runs: the same on https://test.pypi.org (separate account) with environment `testpypi`,
   and create a `testpypi` environment on GitHub.

## Each release

1. On a branch, bump `finn/_version.py` and `version` in `pyproject.toml` (same value), merge to `main`.
2. Optional dry run: Actions -> release -> Run workflow, tick `testpypi`. Check
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ hirefinn`.
3. GitHub -> Releases -> Draft a new release, new tag `vX.Y.Z` on `main` (must equal the package version),
   publish it. The workflow tests, builds, runs `twine check`, then waits for approval on `pypi` and publishes.
4. Check https://pypi.org/p/hirefinn and `pip install hirefinn`.

A version cannot be re-uploaded to PyPI; to fix a bad release, bump the version and release again
(you can yank the bad one on PyPI).

## Local check (no upload)

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' build twine
.venv/bin/pytest
.venv/bin/python -m build && .venv/bin/twine check --strict dist/*
```
