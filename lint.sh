#!/bin/bash
# Local validation script - run this before pushing

set -e

echo "🔍 Running all checks..."
echo ""

# Find ruff - check venv first, then system
if [ -f ".venv/bin/ruff" ]; then
    RUFF=".venv/bin/ruff"
elif command -v ruff &> /dev/null; then
    RUFF="ruff"
else
    echo "❌ ruff not found. Install it with: pip install -r requirements-dev.txt"
    exit 1
fi

echo "📝 Running ruff linter..."
$RUFF check .

echo ""
echo "🎨 Checking formatting..."
$RUFF format --check .

echo ""
echo "🔎 Running pyright type check..."
if [ -f ".venv/bin/pyright" ]; then
    PYRIGHT=".venv/bin/pyright"
elif command -v pyright &> /dev/null; then
    PYRIGHT="pyright"
else
    echo "❌ pyright not found. Install it with: pip install -r requirements-dev.txt"
    exit 1
fi
$PYRIGHT

echo ""
echo "🔍 Running HACS validation..."
./validate-hacs.sh

echo ""
echo "✅ All checks passed!"
