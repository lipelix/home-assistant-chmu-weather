#!/bin/bash
# Local HACS validation script

set -e

echo "🔍 Validating HACS requirements..."

# Check required files
echo "Checking required files..."
required_files=(
    "hacs.json"
    "custom_components/chmu/manifest.json"
    "README.md"
    "LICENSE"
)

for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ Missing required file: $file"
        exit 1
    fi
    echo "✅ Found: $file"
done

# Validate JSON files
echo ""
echo "Validating JSON files..."

# Find Python - check venv first, then system python3, then python
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
elif command -v python &> /dev/null; then
    PYTHON="python"
else
    echo "❌ Python not found"
    exit 1
fi

for json_file in hacs.json custom_components/chmu/manifest.json custom_components/chmu/strings.json; do
    if [ -f "$json_file" ]; then
        if ! $PYTHON -m json.tool "$json_file" > /dev/null 2>&1; then
            echo "❌ Invalid JSON in: $json_file"
            exit 1
        fi
        echo "✅ Valid JSON: $json_file"
    fi
done

# Check hacs.json requirements
echo ""
echo "Validating hacs.json content..."
required_hacs_fields=("name")
for field in "${required_hacs_fields[@]}"; do
    if ! grep -q "\"$field\"" hacs.json; then
        echo "❌ hacs.json missing '$field' field"
        exit 1
    fi
done

# Check for invalid hacs.json fields
echo "Checking for invalid hacs.json fields..."
invalid_fields=("domains" "homeassistant" "iot_class")
for field in "${invalid_fields[@]}"; do
    if grep -q "\"$field\"" hacs.json; then
        echo "❌ hacs.json contains invalid field '$field' (should be in manifest.json only)"
        exit 1
    fi
done
echo "✅ hacs.json is valid"

# Check manifest.json requirements
echo ""
echo "Validating manifest.json content..."
required_manifest_fields=("domain" "name" "documentation" "issue_tracker" "version" "codeowners")
for field in "${required_manifest_fields[@]}"; do
    if ! grep -q "\"$field\"" custom_components/chmu/manifest.json; then
        echo "❌ manifest.json missing '$field' field"
        exit 1
    fi
done
echo "✅ All required manifest.json fields present"

# Check for __init__.py
echo ""
echo "Checking integration structure..."
if [ ! -f "custom_components/chmu/__init__.py" ]; then
    echo "❌ Missing custom_components/chmu/__init__.py"
    exit 1
fi
echo "✅ Integration structure valid"

# Check version format
echo ""
echo "Validating version format..."
version=$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' custom_components/chmu/manifest.json | cut -d'"' -f4)
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ Invalid version format in manifest.json: $version (should be X.Y.Z)"
    exit 1
fi
echo "✅ Version format valid: $version"

echo ""
echo "✅ All HACS validation checks passed!"
