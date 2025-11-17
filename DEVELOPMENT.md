# Development Guide

This guide explains how to set up your local development environment and run checks before committing.

## Setup Development Environment

1. **Create and activate virtual environment** (if not already done):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On macOS/Linux
   ```

2. **Install development dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   ```

3. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```

## Linting

This project uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting.

### Automatic Linting (Pre-commit)

Pre-commit hooks will automatically run ruff before each commit. If there are issues, the commit will be blocked until they're fixed.

### Manual Linting

To run linting manually before pushing:

```bash
./lint.sh
```

Or run ruff commands directly:

```bash
# Check for lint errors
ruff check .

# Auto-fix lint errors
ruff check --fix .

# Check formatting
ruff format --check .

# Auto-format code
ruff format .
```

### Running All Pre-commit Hooks Manually

```bash
pre-commit run --all-files
```

## Development Workflow

1. Make your changes
2. Run `./lint.sh` to check for errors (or rely on pre-commit hooks)
3. Commit your changes (pre-commit will run automatically)
4. Push to GitHub

## CI/CD

GitHub Actions will automatically run linting on every push and pull request. Make sure to run linting locally to catch issues early!
