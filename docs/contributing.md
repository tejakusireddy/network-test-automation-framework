# Contributing Guide

Thank you for your interest in contributing to the Network Test Automation Framework.

## Development Setup

```bash
# Fork and clone
git clone https://github.com/<your-username>/network-test-automation-framework.git
cd network-test-automation-framework

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all development dependencies
make dev-install
```

## Development Workflow

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the coding standards below.

3. **Run the quality checks**:
   ```bash
   make ci  # Runs lint + type-check + tests
   ```

4. **Commit** with a descriptive message:
   ```bash
   git commit -m "feat: add Nokia SRL driver support"
   ```

5. **Push** and open a Pull Request.

## Coding Standards

### Python Style
- Python 3.11+ features welcome
- Type hints on **every** function signature and return type
- Google-style docstrings on every class and public method
- Use `pathlib.Path` instead of string paths
- Use `logging` module — no `print()` statements
- Constants in `UPPER_SNAKE_CASE`

### Design Patterns
- New vendor drivers **must** subclass `BaseDriver`
- Register new drivers in `DriverFactory`
- Custom exceptions **must** inherit from `NetworkTestError`

### Testing
- Unit tests for all new public methods
- Mock all network I/O in unit tests
- Use `pytest.mark.parametrize` for multi-vendor scenarios
- Integration tests marked with `@pytest.mark.integration`

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation only
- `test:` — Adding or updating tests
- `refactor:` — Code change that neither fixes nor adds
- `chore:` — Build process or tooling changes

## Adding a New Vendor Driver

1. Create `src/drivers/your_vendor_driver.py`
2. Subclass `BaseDriver` and implement all abstract methods
3. Add to `VENDOR_DRIVER_MAP` in `driver_factory.py`
4. Add unit tests in `tests/unit/test_your_vendor_driver.py`
5. Add vendor-specific dependencies to `pyproject.toml`
6. Update the README and docs

## Code Review Checklist

- [ ] All type hints present
- [ ] Docstrings on public methods
- [ ] Unit tests pass
- [ ] No linting errors (`make lint`)
- [ ] No type errors (`make type-check`)
- [ ] No hardcoded credentials or secrets
