import ollama
import asyncio


class EmbeddingService:
    def __init__(self, host: str = "http://host.docker.internal:11434"):
        self.client = ollama.Client(host=host)
        self.model = "nomic-embed-text"

    async def embed(self, text: str) -> list[float]:
        response = await asyncio.to_thread(
            self.client.embeddings, model=self.model, prompt=text
        )
        embedding = response["embedding"]
        if len(embedding) == 768:
            embedding = embedding + [0.0] * 768
        return embedding