.PHONY: run-pipeline fetch-insights

COMPOSE_FILE    = /home/luis/Documents/github/oden/docker-compose.yml
BASE_URL        = http://localhost:8000/api/v1
RABBIT_URL      = http://localhost:15672/api/queues/%2F
RABBIT_USER     = guest
RABBIT_PASS     = guest
QUEUE_NAME      = worker-1

run-pipeline:
	@echo "🚀 Starting Docker containers..."
	docker compose -f $(COMPOSE_FILE) up -d

	@echo "⏳ Waiting for Oden to be healthy..."
	@until curl --output /dev/null --silent --head --fail $(BASE_URL)/documents/health_check; \
	do \
		echo "   ...not ready, retrying in 5s"; \
		sleep 5; \
	done
	@echo "✅ Oden is running!"

	@echo "📥 Triggering document ingestion..."
	@curl -s -X POST $(BASE_URL)/ingest_documents
	@echo ""

	@echo "⏳ Waiting for queue to fill..."
	@sleep 10

	@echo "📊 Polling RabbitMQ queue until empty..."
	@while true; do \
		TOTAL=$$(curl -s -u $(RABBIT_USER):$(RABBIT_PASS) \
			$(RABBIT_URL)/$(QUEUE_NAME) \
			| python3 -c "import sys,json; q=json.load(sys.stdin); print(q.get('messages', 0))"); \
		READY=$$(curl -s -u $(RABBIT_USER):$(RABBIT_PASS) \
			$(RABBIT_URL)/$(QUEUE_NAME) \
			| python3 -c "import sys,json; q=json.load(sys.stdin); print(q.get('messages_ready', 0))"); \
		UNACKED=$$(curl -s -u $(RABBIT_USER):$(RABBIT_PASS) \
			$(RABBIT_URL)/$(QUEUE_NAME) \
			| python3 -c "import sys,json; q=json.load(sys.stdin); print(q.get('messages_unacknowledged', 0))"); \
		echo "   📬 Total: $$TOTAL | Ready: $$READY | Processing: $$UNACKED"; \
		if [ "$$TOTAL" = "0" ]; then \
			echo "✅ Queue drained — all documents processed!"; \
			break; \
		fi; \
		sleep 30; \
	done

	@$(MAKE) fetch-insights

fetch-insights:
	@echo "\n🏆 Fetching insights..."
	@curl -s $(BASE_URL)/fetch_best_trades      | python3 -m json.tool
	@curl -s $(BASE_URL)/fetch_speculative_trades | python3 -m json.tool