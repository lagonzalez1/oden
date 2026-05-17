# This is a full-line comment \




.PHONY: run-pipeline

run-pipeline:
	@echo "🚀 Starting Docker containers..."
	docker compose -f /home/luis/Documents/github/oden/docker-compose.yml up -d
	@echo "⏳ Waiting for Oden to start..."
	@until $$(curl --output /dev/null --silent --head --fail http://localhost:8000/api/v1/documents/health_check); do sleep 4; done
	@echo "✅ Oden is running!"
	@echo "📥 Triggering document ingestion..."
	curl -X POST http://localhost:8000/api/v1/ingest_documents
	@echo "\n🎉 Ingestion complete!"
