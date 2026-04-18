from pinecone import Pinecone
from utils.embeddings import get_embedding_model

class PineconeRetriever:
    def __init__(self, api_key, index_name):
        self.pc = Pinecone(api_key=api_key)
        self.index = self.pc.Index(index_name)
        self.embed = get_embedding_model()

    def search(self, query, top_k=5):
        vector = self.embed.embed_query(query)

        results = self.index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True
        )

        return results["matches"]