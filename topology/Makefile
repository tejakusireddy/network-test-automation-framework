.PHONY: lab-up lab-down lab-status lab-logs lab-shell

lab-up:
	docker compose up -d
	@echo "Waiting 15s for FRR to initialize..."
	@sleep 15
	@echo "Lab is up! Run 'make lab-status' to check."

lab-down:
	docker compose down

lab-status:
	@echo "=== Container Status ==="
	docker compose ps
	@echo ""
	@echo "=== BGP Summary (spine1) ==="
	docker exec clab-spine1 vtysh -c "show bgp summary" 2>/dev/null || echo "spine1 not ready"

lab-logs:
	docker compose logs -f

lab-shell:
	@echo "Usage: docker exec -it <container> vtysh"
	@echo "Containers: clab-spine1 clab-spine2 clab-leaf1 clab-leaf2 clab-leaf3 clab-leaf4 clab-wan-edge"
