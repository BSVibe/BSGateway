#!/bin/bash
set -e

echo "BSage DevContainer Post-Start Setup"
echo "============================================="

# 0. Configure git safe directory (required for devcontainer)
# Use --replace-all to avoid duplicates on repeated runs
if ! git config --global --get-all safe.directory | grep -q "^/workspace$"; then
    git config --global --add safe.directory /workspace
    echo "[OK] Git safe directory configured"
else
    echo "[OK] Git safe directory already configured"
fi

# 1. Create virtual environment if it doesn't exist (uv is pre-installed in Dockerfile)
if [ ! -d ".venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    uv venv .venv
    echo "[OK] Virtual environment created"
fi

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Install Python dependencies
echo ""
echo "Installing Python dependencies..."
if [ -f "pyproject.toml" ]; then
    # Use copy mode to avoid hardlink warnings (host volume vs container filesystem)
    UV_LINK_MODE=copy uv pip install -e ".[dev]"
    echo "[OK] Dependencies installed successfully"
else
    echo "[SKIP] pyproject.toml not found - will be created during setup"
fi

# 4. Make sure scripts are executable
chmod +x .devcontainer/scripts/*.sh 2>/dev/null || true

# 5. Add venv activation to bashrc
if ! grep -q "source /workspace/.venv/bin/activate" ~/.bashrc; then
    echo 'source /workspace/.venv/bin/activate' >> ~/.bashrc
    echo "[OK] Auto-activation added to bashrc"
fi

# 6. Run local-only setup (gitignored)
LOCAL_SETUP=".devcontainer/scripts/post-start.local.sh"
if [ -f "$LOCAL_SETUP" ]; then
    echo ""
    echo "Running local setup..."
    bash "$LOCAL_SETUP"
    echo "[OK] Local setup complete"
fi

echo ""
echo "============================================="
echo "[DONE] DevContainer setup complete!"
echo "============================================="
echo ""
