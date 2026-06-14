Write-Host "==> Installing atlassian-cli with Turso support"

# cmake (required to build libsql-experimental)
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing cmake..."
    winget install Kitware.CMake --silent
    # Reload PATH so cmake is available in this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")
} else {
    Write-Host "==> cmake already installed"
}

# Turso CLI
if (-not (Get-Command turso -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing Turso CLI..."
    npm install -g @tursodatabase/cli
} else {
    Write-Host "==> Turso CLI already installed"
}

# Python package with turso extra
Write-Host "==> Installing atlassian-cli + turso extra..."
pip install -e ".[turso]"

Write-Host ""
Write-Host "Done! Next steps:"
Write-Host "  1. turso auth login"
Write-Host "  2. turso db create atlassian-memory"
Write-Host "  3. turso db show atlassian-memory --url     # -> TURSO_URL"
Write-Host "  4. turso db tokens create atlassian-memory  # -> TURSO_AUTH_TOKEN"
Write-Host "  5. Add TURSO_URL and TURSO_AUTH_TOKEN to .env"
