## To start the application you must have the following..


1. Docker desktop
2. .env file created on the root of the file strucure.
```bash
# App
APP_NAME=FastAPI Service
APP_VERSION=0.1.0
DEBUG=false

# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=app_db

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=yourpassword


# RabbitMQ
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT= 5672
RABBITMQ_USER=admin
RABBITMQ_PASSWORD=password
RABBITMQ_VHOST=/
```

3. then run the following commands to start up each compoent in docker-compose.yml
4. In terminal in path of project
```bash
    docker compose up --build

```