from utils.embeddings import get_embedding_model

class PatentRetriever:
    def __init__(self, pinecone_index):
        self.index = pinecone_index
        self.embed = get_embedding_model()

    def enhance_query(self, query):
        # simple enhancement (can replace with LLM later)
        return f"technical patent description: {query}"

    def search(self, query, top_k=5):
        enhanced_query = self.enhance_query(query)
        vector = self.embed.embed_query(enhanced_query)

        results = self.index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True
        )

        return results["matches"]