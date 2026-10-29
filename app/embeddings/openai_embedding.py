"""Real semantic embeddings through the configured OpenAI embeddings endpoint."""
from app.embeddings.provider import EmbeddingProvider
class OpenAIEmbedding(EmbeddingProvider):
    def __init__(self, model="text-embedding-3-small", dimension=1536, client=None):
        from openai import OpenAI
        self.model, self.dimension = model, dimension
        self.client = client or OpenAI(timeout=15, max_retries=1)
    def get_dimension(self):
        return self.dimension
    def embed_text(self, text):
        response = self.client.embeddings.create(model=self.model, input=text, dimensions=self.dimension)
        vector = response.data[0].embedding
        if len(vector) != self.dimension:
            raise ValueError("Embedding response dimension mismatch")
        return vector
