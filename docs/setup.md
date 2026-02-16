# Setup Guide

## Prerequisites

- Python 3.11 or later
- Docker (for Batfish and Containerlab)
- [Containerlab](https://containerlab.dev/) (for lab topology)
- Juniper cRPD container image (for the default topology)

## Quick Install

```bash
# Clone the repository
git clone https://github.com/example/network-test-automation-framework.git
cd network-test-automation-framework

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with all dependencies
make dev-install
```

## Vendor-Specific Installation

Install only the vendor SDKs you need:

```bash
# Juniper only
pip install -e ".[juniper,test]"

# Cisco only
pip install -e ".[cisco,test]"

# Arista only
pip install -e ".[arista,test]"

# All vendors
pip install -e ".[all-vendors,test]"
```

## Environment Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your values
vim .env
```

Key variables:
- `DEVICE_USER` / `DEVICE_PASS`: Default device credentials
- `ANTHROPIC_API_KEY`: Required for AI-powered triage
- `BATFISH_HOST`: Batfish service address (default: localhost)

## Lab Topology Setup

### Start the Containerlab Topology

```bash
# Deploy the 7-node leaf-spine fabric
make topology-up

# Verify the topology is running
make topology-inspect
```

### Start Batfish

```bash
# Start the Batfish container
docker-compose up -d batfish

# Or use the make target
make run-batfish
```

## Running Tests

```bash
# Unit tests
make test

# All tests including integration
make test-all

# Integration tests (requires running topology)
make test-integration

# Robot Framework tests
make run-robot

# Full CI pipeline
make ci
```

## Troubleshooting

### Cannot connect to devices
- Verify the topology is running: `make topology-inspect`
- Check management IP reachability: `ping 172.20.20.2`
- Verify SSH/NETCONF is enabled on the device

### Batfish connection refused
- Ensure the container is running: `docker ps | grep batfish`
- Wait 30 seconds after starting for initialization
- Check port 9997 is not in use: `lsof -i :9997`

### Import errors
- Ensure you installed the correct vendor extras: `pip install -e ".[all-vendors]"`
- Check Python version: `python --version` (must be 3.11+)
