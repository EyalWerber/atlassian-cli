#!/usr/bin/env sh
set -e

echo "==> Installing atlassian-cli with Turso support"

# cmake (required to build libsql-experimental)
if ! command -v cmake > /dev/null 2>&1; then
  echo "==> Installing cmake..."
  if command -v brew > /dev/null 2>&1; then
    brew install cmake
  elif command -v apt-get > /dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y cmake
  elif command -v dnf > /dev/null 2>&1; then
    sudo dnf install -y cmake
  else
    echo "ERROR: cmake not found and no known package manager available."
    echo "Install cmake manually: https://cmake.org/download/"
    exit 1
  fi
else
  echo "==> cmake already installed"
fi

# Turso CLI
if ! command -v turso > /dev/null 2>&1; then
  echo "==> Installing Turso CLI..."
  curl -sSfL https://get.tur.so/install.sh | bash
else
  echo "==> Turso CLI already installed"
fi

# Python package with turso extra
echo "==> Installing atlassian-cli + turso extra..."
pip install -e ".[turso]"

echo ""
echo "Done! Next steps:"
echo "  1. turso auth login"
echo "  2. turso db create atlassian-memory"
echo "  3. turso db show atlassian-memory --url    # → TURSO_URL"
echo "  4. turso db tokens create atlassian-memory # → TURSO_AUTH_TOKEN"
echo "  5. Add TURSO_URL and TURSO_AUTH_TOKEN to .env"
