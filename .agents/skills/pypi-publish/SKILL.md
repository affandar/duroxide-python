---
name: pypi-publish
description: Publishing duroxide-python to PyPI. Use when releasing a new version, building platform wheels, or publishing to the Python Package Index.
---

# Publishing duroxide-python to PyPI

## Pre-Publish Checklist

Before publishing, verify ALL of the following:

### 1. Clean Build

```bash
cd duroxide-python
source .venv/bin/activate

# Clippy — must pass with zero warnings
cargo clippy --all-targets

# Release build via maturin
maturin develop --release
```

### 2. Tests Pass

```bash
# All 49 tests must pass (requires DATABASE_URL in .env)
pytest -v
```

### 3. Changelog Updated

- `CHANGELOG.md` must have an entry for the new version
- Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format
- Include all Added/Changed/Fixed/Removed sections as applicable

### 4. README Points to Changelog

Verify `README.md` contains a link to `CHANGELOG.md`:
```markdown
See [CHANGELOG.md](CHANGELOG.md) for release notes.
```

### 5. Version Bumped

Update version in `pyproject.toml`:

```toml
[project]
name = "duroxide"
version = "0.1.1"  # ← bump this
```

Also update `Cargo.toml` version to match:
```toml
[package]
version = "0.1.1"
```

## Build Platform Wheels

PyPI uses **wheels** — one per platform + Python version combo. Unlike npm (separate packages per platform), PyPI serves all wheels under the **same package name**. `pip install duroxide` automatically picks the right one.

### Local Build (current platform only)

```bash
maturin build --release
# Output: target/wheels/duroxide-0.1.0-cp39-cp39-macosx_11_0_arm64.whl
```

### Cross-Platform Builds via GitHub Actions (Recommended)

Use maturin's official GitHub Action to build for all platforms:

```yaml
name: Publish to PyPI
on:
  release:
    types: [published]

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.9", "3.10", "3.11", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: PyO3/maturin-action@v1
        with:
          command: build
          args: --release --out dist
          manylinux: auto
      - uses: actions/upload-artifact@v4
        with:
          name: wheels-${{ matrix.os }}-${{ matrix.python-version }}
          path: dist/*.whl

  publish:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: wheels-*
          merge-multiple: true
          path: dist
      - uses: PyO3/maturin-action@v1
        with:
          command: upload
          args: --skip-existing dist/*
        env:
          MATURIN_PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}
```

### Supported Platforms

| Platform | Target | Notes |
|----------|--------|-------|
| macOS ARM | `aarch64-apple-darwin` | Native build on M1/M2 |
| macOS Intel | `x86_64-apple-darwin` | Cross-compile from ARM |
| Linux x64 | `x86_64-unknown-linux-gnu` | Use `manylinux` Docker |
| Linux ARM | `aarch64-unknown-linux-gnu` | Cross-compile via QEMU |
| Windows x64 | `x86_64-pc-windows-msvc` | Native build on Windows |

### Docker Build for Linux (manylinux)

```bash
docker run --rm -v "$(pwd):/io" -w /io ghcr.io/pyo3/maturin build --release
# Produces manylinux-compatible wheels
```

## Publish to PyPI

### Option 1: maturin publish (build + upload in one step)

```bash
# Requires MATURIN_PYPI_TOKEN env var or ~/.pypirc config
export MATURIN_PYPI_TOKEN=pypi-...
maturin publish --skip-existing
```

### Option 2: Build then upload with twine

```bash
maturin build --release
pip install twine
twine upload target/wheels/*.whl
```

### Option 3: Test on TestPyPI first

```bash
maturin publish --repository testpypi
# Test install:
pip install --index-url https://test.pypi.org/simple/ duroxide
```

## PyPI Authentication

- Create API token at: https://pypi.org/manage/account/token/
- Scope: project-specific (recommended) or account-wide
- Set as `MATURIN_PYPI_TOKEN` env var or configure in `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-...
```

- Never commit tokens to source code

## Verify Published Package

```bash
# In a clean virtualenv
python3 -m venv /tmp/test-duroxide
source /tmp/test-duroxide/bin/activate
pip install duroxide
python -c "from duroxide import SqliteProvider; print('loaded successfully')"
deactivate
rm -rf /tmp/test-duroxide
```

## Key Differences from npm Publishing

| Aspect | npm (duroxide-node) | PyPI (duroxide-python) |
|--------|--------------------|-----------------------|
| Packages per platform | Separate (`@duroxide/darwin-arm64`) | One package, multiple wheels |
| Publish order | Platform packages first, then main | Just publish all wheels |
| Binary selection | `optionalDependencies` in package.json | pip auto-selects by wheel filename |
| Build tool | `npx napi build` | `maturin build` |
| Upload tool | `npm publish` | `maturin publish` or `twine upload` |
| Token type | npm Automation token | PyPI API token |

## Summary Checklist

- [ ] `cargo clippy --all-targets` — zero warnings
- [ ] `maturin develop --release` — clean build
- [ ] `pytest -v` — all 49 tests pass
- [ ] `CHANGELOG.md` — updated for new version
- [ ] `README.md` — links to CHANGELOG.md and docs
- [ ] Version bumped in `pyproject.toml` + `Cargo.toml`
- [ ] Wheels built for all target platforms (via CI or locally)
- [ ] Published to PyPI (or TestPyPI first)
- [ ] Verified with `pip install duroxide` in a clean virtualenv
