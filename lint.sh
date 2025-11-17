#!/bin/bash
# Local lint script - run this before pushing

set -e

echo "🔍 Running ruff linter..."
if ! command -v ruff &> /dev/null; then
    echo "❌ ruff not found. Install it with: pip install -r requirements-dev.txt"
    exit 1
fi

echo "Checking for lint errors..."
ruff check .

echo "Checking formatting..."
ruff format --check .

echo "✅ All lint checks passed!"
