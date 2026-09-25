import os
import re
from pathlib import Path
from typing import List, Dict, Any
from rank_bm25 import BM25Okapi

# Point directly to enterprise-bi-copilot (parents[4])
ROOT_DIR = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = ROOT_DIR / "data" / "sample_contracts"
CHROMA_DIR = ROOT_DIR / "data" / "chroma_store"
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "user_123")

class HybridRetriever:
    def __init__(self):
        self.dense_enabled = os.getenv("ENABLE_DENSE_RAG", "true").lower() == "true"
        self.collection = None
        if self.dense_enabled:
            import chromadb

            self.chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self.collection = self.chroma_client.get_or_create_collection(name="enterprise_policies")
        self.documents: List[str] = []
        self.doc_ids: List[str] = []
        self.document_tenants: List[str] = []
        self.bm25 = None
        self._index_documents()

    def _index_documents(self):
        chunks = []
        ids = []
        tenants = []

        if not CONTRACTS_DIR.exists():
            print(f"[ERROR] Contracts directory does not exist: {CONTRACTS_DIR}")
            return

        for file in CONTRACTS_DIR.glob("*.txt"):
            raw_text = file.read_text(encoding="utf-8")
            text = raw_text.replace("\r\n", "\n")
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 30]

            for idx, p in enumerate(paragraphs):
                chunk_id = f"{file.stem}_chunk_{idx}"
                chunks.append(p)
                ids.append(chunk_id)
                tenants.append(DEFAULT_TENANT_ID)

        if not chunks:
            print(f"[WARN] No text chunks found in: {CONTRACTS_DIR}")
            return

        self.documents = chunks
        self.doc_ids = ids
        self.document_tenants = tenants

        # Tokenize for BM25
        tokenized_corpus = [re.findall(r'\w+', doc.lower()) for doc in chunks]
        self.bm25 = BM25Okapi(tokenized_corpus)

        if self.dense_enabled and self.collection is not None:
            self.collection.upsert(
                documents=chunks,
                ids=ids,
                metadatas=[{"source": "sample_contract", "tenant_id": DEFAULT_TENANT_ID} for _ in ids]
            )

    def add_documents(self, chunks: List[str], tenant_id: str, source: str) -> int:
        clean_chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
        if not clean_chunks:
            return 0

        start = len(self.documents)
        ids = [f"{tenant_id}_{source}_{start + index}" for index in range(len(clean_chunks))]
        self.documents.extend(clean_chunks)
        self.doc_ids.extend(ids)
        self.document_tenants.extend([tenant_id] * len(clean_chunks))
        self.bm25 = BM25Okapi([
            re.findall(r'\w+', document.lower()) for document in self.documents
        ])

        if self.dense_enabled and self.collection is not None:
            self.collection.upsert(
                documents=clean_chunks,
                ids=ids,
                metadatas=[{"source": source, "tenant_id": tenant_id} for _ in ids],
            )
        return len(clean_chunks)

    def search(self, query: str, tenant_id: str, top_k: int = 3) -> List[Dict[str, Any]]:
        results = []
        query_clean = query.strip()
        if not query_clean or not self.documents:
            return results

        # 1. Sparse BM25
        if self.bm25:
            tokens = re.findall(r'\w+', query_clean.lower())
            if tokens:
                bm25_scores = self.bm25.get_scores(tokens)
                tenant_indices = [
                    index for index, document_tenant in enumerate(self.document_tenants)
                    if document_tenant == tenant_id
                ]
                top_indices = sorted(
                    tenant_indices, key=lambda i: bm25_scores[i], reverse=True
                )[:top_k]
                for idx in top_indices:
                    if bm25_scores[idx] > 0:
                        results.append({
                            "text": self.documents[idx],
                            "source": "bm25",
                            "score": float(bm25_scores[idx])
                        })

        # 2. Dense ChromaDB
        if self.dense_enabled and self.collection is not None:
            try:
                chroma_res = self.collection.query(
                    query_texts=[query_clean],
                    n_results=top_k,
                    where={"tenant_id": tenant_id},
                )
                if chroma_res and chroma_res.get("documents") and chroma_res["documents"][0]:
                    for doc in chroma_res["documents"][0]:
                        if not any(r["text"] == doc for r in results):
                            results.append({"text": doc, "source": "chroma_dense", "score": 1.0})
            except Exception:
                pass

        return results[:top_k]

retriever = HybridRetriever()

def search_policy_documents(query: str, tenant_id: str, top_k: int = 3) -> Dict[str, Any]:
    matches = retriever.search(query, tenant_id=tenant_id, top_k=top_k)
    return {"query": query, "match_count": len(matches), "results": matches}
