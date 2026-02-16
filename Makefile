.PHONY: help install dev-install test lint format type-check clean topology-up topology-down run-robot run-batfish report

PYTHON := python3
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy
BLACK := $(PYTHON) -m black
ROBOT := $(PYTHON) -m robot
COVERAGE := $(PYTHON) -m pytest --cov=src --cov-report=html --cov-report=term-missing

TOPOLOGY_FILE := topology/containerlab-topology.yml
REPORT_OUTPUT := output/report.html

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install the package in production mode
	$(PIP) install .

dev-install: ## Install the package with all development dependencies
	$(PIP) install -e ".[all-vendors,nornir,batfish,triage,reporting,robot,dev,test,docs]"
	pre-commit install

test: ## Run unit tests with coverage
	$(COVERAGE) tests/unit/

test-all: ## Run all tests including integration
	$(COVERAGE) tests/ -m ""

test-integration: ## Run only integration tests
	$(PYTEST) tests/integration/ -m integration -v

lint: ## Run ruff linter
	$(RUFF) check src/ tests/

lint-fix: ## Auto-fix linting issues
	$(RUFF) check --fix src/ tests/

format: ## Format code with black and ruff
	$(BLACK) src/ tests/
	$(RUFF) format src/ tests/

format-check: ## Check formatting without making changes
	$(BLACK) --check src/ tests/
	$(RUFF) format --check src/ tests/

type-check: ## Run mypy type checker
	$(MYPY) src/

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov/ .coverage coverage.xml
	rm -rf output/ snapshots/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

topology-up: ## Start the containerlab topology
	sudo containerlab deploy --topo $(TOPOLOGY_FILE) --reconfigure

topology-down: ## Destroy the containerlab topology
	sudo containerlab destroy --topo $(TOPOLOGY_FILE) --cleanup

topology-inspect: ## Show containerlab topology status
	sudo containerlab inspect --topo $(TOPOLOGY_FILE)

run-robot: ## Run Robot Framework test suites
	$(ROBOT) --outputdir output/robot \
		--loglevel DEBUG \
		--variable DEVICE_USER:admin \
		--variable DEVICE_PASS:admin123 \
		robot_tests/

run-robot-smoke: ## Run only smoke-tagged Robot tests
	$(ROBOT) --outputdir output/robot \
		--include smoke \
		robot_tests/

run-batfish: ## Start Batfish and run offline analysis
	docker-compose up -d batfish
	@echo "Waiting for Batfish to start..."
	@sleep 10
	$(PYTHON) -c "from src.analysis.batfish_validator import BatfishValidator; \
		bf = BatfishValidator(); bf.connect(); \
		print('Batfish is ready')"

report: ## Generate HTML test report
	@mkdir -p output
	$(PYTHON) -c "from src.reporting.report_generator import ReportGenerator; \
		gen = ReportGenerator(); \
		gen.set_title('Network Test Automation Report'); \
		gen.generate('$(REPORT_OUTPUT)'); \
		print('Report generated: $(REPORT_OUTPUT)')"

ci: lint type-check test ## Run full CI pipeline locally

pre-commit: ## Run pre-commit hooks on all files
	pre-commit run --all-files
