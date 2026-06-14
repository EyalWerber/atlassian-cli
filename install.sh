#!/usr/bin/env sh
set -e

echo "==> Installing atlassian-cli with Turso support"

# Turso CLI
if ! command -v turso > /dev/null 2>&1; then
  echo "==> Installing Turso CLI..."
  npm install -g turso
else
  echo "==> Turso CLI already installed"
fi

# Python package
echo "==> Installing atlassian-cli..."
pip install -e .

echo ""
echo "Done! Next steps:"
echo "  1. turso auth login"
echo "  2. turso db create atlassian-memory"
echo "  3. turso db show atlassian-memory --url    # → TURSO_URL"
echo "  4. turso db tokens create atlassian-memory # → TURSO_AUTH_TOKEN"
echo "  5. Add TURSO_URL and TURSO_AUTH_TOKEN to .env"
