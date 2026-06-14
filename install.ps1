Write-Host "==> Installing atlassian-cli with Turso support"

# Turso CLI
if (-not (Get-Command turso -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing Turso CLI..."
    npm install -g turso
} else {
    Write-Host "==> Turso CLI already installed"
}

# Python package
Write-Host "==> Installing atlassian-cli..."
pip install -e .

Write-Host ""
Write-Host "Done! Next steps:"
Write-Host "  1. turso auth login"
Write-Host "  2. turso db create atlassian-memory"
Write-Host "  3. turso db show atlassian-memory --url     # -> TURSO_URL"
Write-Host "  4. turso db tokens create atlassian-memory  # -> TURSO_AUTH_TOKEN"
Write-Host "  5. Add TURSO_URL and TURSO_AUTH_TOKEN to .env"
