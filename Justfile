# Justfile for amodem project

# List all available recipes
default:
    @just --list

# Install development dependencies
install:
    pip install -e ".[dev]"

# Format code with black and ruff
format:
    @echo "Formatting code with black..."
    black amodem/ scripts/
    @echo "Applying ruff auto-fixes..."
    ruff check --fix amodem/ scripts/

# Run linters and type checker
lint:
    @echo "Running ruff checks..."
    ruff check amodem/ scripts/
    @echo "Running mypy type checker..."
    mypy amodem/ --ignore-missing-imports

# Run tests with coverage
test:
    @echo "Running tests with coverage..."
    pytest -v --cov=amodem

# Format check without modifying files
check-format:
    @echo "Checking code format..."
    black --check amodem/ scripts/
    ruff check amodem/ scripts/

# Run all checks (format, lint, test)
check-all: check-format lint test

# Set up virtual PulseAudio pipes for testing
pipes:
    @echo "Setting up virtual PulseAudio pipes..."
    @echo "TODO: Create null sink and loopback module"

# Clear virtual PulseAudio pipes
pipes-clear:
    @echo "Clearing virtual PulseAudio pipes..."
    @echo "TODO: Unload loopback and remove null sink"

# Clean up Python cache files
clean:
    @echo "Cleaning up cache files..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
