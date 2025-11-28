# modules/conversation_indexer_simple.py
"""
Simple conversation indexer that works without sentence-transformers
Uses the existing embedding infrastructure from mcp_server_2.py
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import faiss
    import numpy as np

    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("Warning: faiss-cpu not installed. Conversation indexing will be disabled.")

try:
    from agent import log
except ImportError:

    def log(stage: str, msg: str):
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")


class ConversationIndexer:
    """
    Smart conversation indexer that:
    1. Indexes all historical conversations with embeddings
    2. Provides semantic search over past conversations
    3. Incrementally updates only new/changed conversations
    4. Retrieves relevant historical context for current queries
    """

    def __init__(
        self,
        memory_dir: str = "memory",
        index_dir: str = "conversation_index",
        top_k: int = 5,
    ):
        if not FAISS_AVAILABLE:
            raise RuntimeError("FAISS is required for conversation indexing")

        self.root = Path(__file__).parent.parent.resolve()
        self.memory_dir = self.root / memory_dir
        self.index_dir = self.root / index_dir
        self.index_dir.mkdir(exist_ok=True)

        self.index_file = self.index_dir / "conversations.bin"
        self.metadata_file = self.index_dir / "conversations_metadata.json"
        self.cache_file = self.index_dir / "conversation_cache.json"

        self.top_k = top_k

        # Initialize embedding function (using existing infrastructure)
        self._init_embedding_function()

        # Load or create index
        self.index = None
        self.metadata = []
        self.cache = {}
        self._load_index()

    def _init_embedding_function(self):
        """Initialize embedding function from config"""
        try:
            config_path = self.root / "config" / "models.json"
            with open(config_path, "r") as f:
                config = json.load(f)

            default_embed = config["defaults"]["embedding"]
            embed_config = config["models"][default_embed]

            if embed_config["type"] == "huggingface":
                # Use HuggingFace model
                try:
                    from sentence_transformers import SentenceTransformer

                    self.embedding_model = SentenceTransformer(
                        embed_config["model"], trust_remote_code=True
                    )
                    self.embed_type = "huggingface"
                    log(
                        "conversation_index",
                        f"Using HuggingFace model: {embed_config['model']}",
                    )
                except ImportError:
                    log(
                        "conversation_index",
                        "⚠️ sentence-transformers not installed, falling back to simple embeddings",
                    )
                    self._use_simple_embeddings()
            else:
                # For other types, use simple embeddings
                self._use_simple_embeddings()

        except Exception as e:
            log(
                "conversation_index",
                f"⚠️ Error loading embedding config: {e}, using simple embeddings",
            )
            self._use_simple_embeddings()

    def _use_simple_embeddings(self):
        """Fallback to simple TF-IDF-like embeddings"""
        self.embed_type = "simple"
        self.vocab = {}
        self.vocab_size = 1000  # Fixed vocabulary size
        log("conversation_index", "Using simple TF-IDF-like embeddings")

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text"""
        if self.embed_type == "huggingface":
            embedding = self.embedding_model.encode(text, convert_to_numpy=True)
            return embedding.astype(np.float32)
        else:
            # Simple bag-of-words embedding
            return self._simple_embedding(text)

    def _simple_embedding(self, text: str) -> np.ndarray:
        """Create simple TF-IDF-like embedding"""
        # Tokenize
        words = text.lower().split()

        # Build vocabulary dynamically
        for word in words:
            if word not in self.vocab and len(self.vocab) < self.vocab_size:
                self.vocab[word] = len(self.vocab)

        # Create sparse vector
        embedding = np.zeros(self.vocab_size, dtype=np.float32)
        word_counts = {}
        for word in words:
            if word in self.vocab:
                idx = self.vocab[word]
                word_counts[idx] = word_counts.get(idx, 0) + 1

        # TF (term frequency)
        for idx, count in word_counts.items():
            embedding[idx] = count / len(words) if len(words) > 0 else 0

        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    def _load_index(self):
        """Load existing index or create new one"""
        if self.index_file.exists() and self.metadata_file.exists():
            log("conversation_index", "Loading existing conversation index...")
            self.index = faiss.read_index(str(self.index_file))
            self.metadata = json.loads(self.metadata_file.read_text())
            if self.cache_file.exists():
                self.cache = json.loads(self.cache_file.read_text())
            log(
                "conversation_index",
                f"Loaded {len(self.metadata)} indexed conversations",
            )
        else:
            log("conversation_index", "No existing index found. Will create new one.")

    def _save_index(self):
        """Save index, metadata, and cache"""
        if self.index is not None:
            faiss.write_index(self.index, str(self.index_file))
        self.metadata_file.write_text(json.dumps(self.metadata, indent=2))
        self.cache_file.write_text(json.dumps(self.cache, indent=2))
        log(
            "conversation_index", f"Saved index with {len(self.metadata)} conversations"
        )

    def _get_file_hash(self, file_path: Path) -> str:
        """Get hash of file for change detection"""
        return hashlib.md5(file_path.read_bytes()).hexdigest()

    def _find_all_conversations(self) -> List[Path]:
        """Find all conversation JSON files in memory directory"""
        if not self.memory_dir.exists():
            return []
        return list(self.memory_dir.rglob("session-*.json"))

    def _extract_conversation_summary(self, session_data: List[Dict]) -> Dict[str, Any]:
        """Extract meaningful information from a conversation session"""
        if not session_data:
            return None

        # Get initial query
        initial_query = None
        for item in session_data:
            if item.get("type") == "run_metadata" and "run_start" in item.get(
                "tags", []
            ):
                # Extract from text field
                text = item.get("text", "")
                if "Started new session with input:" in text:
                    initial_query = (
                        text.split("Started new session with input:")[1]
                        .split(" at ")[0]
                        .strip()
                    )
                break

        # Get all tool calls and results
        tool_calls = [item for item in session_data if item.get("type") == "tool_call"]
        tool_outputs = [
            item for item in session_data if item.get("type") == "tool_output"
        ]

        # Get final answer
        final_answer = None
        for item in reversed(session_data):
            if item.get("type") == "final_answer":
                final_answer = item.get("final_answer") or item.get("text")
                break

        # Check if conversation was successful
        success = any(item.get("success") for item in tool_outputs)

        # Get timestamp
        timestamp = session_data[0].get("timestamp", time.time())

        return {
            "initial_query": initial_query,
            "tool_calls": [tc.get("tool_name") for tc in tool_calls],
            "final_answer": final_answer,
            "success": success,
            "timestamp": timestamp,
            "num_steps": len(tool_calls),
            "metadata": session_data[0].get("metadata", {}),
        }

    def _create_searchable_text(self, summary: Dict[str, Any]) -> str:
        """Create a comprehensive text representation for embedding"""
        parts = []

        if summary.get("initial_query"):
            parts.append(f"Query: {summary['initial_query']}")

        if summary.get("tool_calls"):
            parts.append(f"Tools used: {', '.join(summary['tool_calls'])}")

        if summary.get("final_answer"):
            # Truncate long answers
            answer = summary["final_answer"]
            if len(answer) > 500:
                answer = answer[:500] + "..."
            parts.append(f"Answer: {answer}")

        return "\n".join(parts)

    def index_conversations(self, force_reindex: bool = False):
        """
        Index all conversations in the memory directory.
        Only indexes new or changed conversations unless force_reindex=True
        """
        log("conversation_index", "Starting conversation indexing...")

        conversation_files = self._find_all_conversations()
        if not conversation_files:
            log("conversation_index", "No conversations found to index")
            return

        log("conversation_index", f"Found {len(conversation_files)} conversation files")

        new_embeddings = []
        new_metadata = []
        indexed_count = 0
        skipped_count = 0

        for conv_file in conversation_files:
            file_key = str(conv_file.relative_to(self.root))
            file_hash = self._get_file_hash(conv_file)

            # Skip if already indexed and unchanged
            if (
                not force_reindex
                and file_key in self.cache
                and self.cache[file_key] == file_hash
            ):
                skipped_count += 1
                continue

            try:
                # Load conversation
                session_data = json.loads(conv_file.read_text())

                # Extract summary
                summary = self._extract_conversation_summary(session_data)
                if not summary or not summary.get("initial_query"):
                    continue

                # Create searchable text
                searchable_text = self._create_searchable_text(summary)

                # Generate embedding
                embedding = self._get_embedding(searchable_text)

                new_embeddings.append(embedding)
                new_metadata.append(
                    {
                        "file_path": file_key,
                        "session_id": conv_file.stem.replace("session-", ""),
                        "initial_query": summary["initial_query"],
                        "final_answer": summary["final_answer"],
                        "tool_calls": summary["tool_calls"],
                        "success": summary["success"],
                        "timestamp": summary["timestamp"],
                        "num_steps": summary["num_steps"],
                        "searchable_text": searchable_text,
                    }
                )

                self.cache[file_key] = file_hash
                indexed_count += 1

            except Exception as e:
                log("conversation_index", f"Error indexing {file_key}: {e}")
                continue

        # Add new embeddings to index
        if new_embeddings:
            embeddings_array = np.stack(new_embeddings)

            if self.index is None:
                # Create new index
                dimension = embeddings_array.shape[1]
                self.index = faiss.IndexFlatL2(dimension)

            self.index.add(embeddings_array)
            self.metadata.extend(new_metadata)
            self._save_index()

            log(
                "conversation_index",
                f"✅ Indexed {indexed_count} new conversations, skipped {skipped_count} unchanged",
            )
        else:
            log(
                "conversation_index",
                f"✅ No new conversations to index (skipped {skipped_count} unchanged)",
            )

    def search_conversations(
        self, query: str, top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Search for relevant past conversations"""
        if self.index is None or len(self.metadata) == 0:
            log("conversation_index", "No conversations indexed yet")
            return []

        top_k = top_k or self.top_k

        # Generate query embedding
        query_embedding = self._get_embedding(query).reshape(1, -1)

        # Search index
        distances, indices = self.index.search(
            query_embedding, min(top_k, len(self.metadata))
        )

        results = []
        for idx, distance in zip(indices[0], distances[0]):
            if idx < len(self.metadata):
                result = self.metadata[idx].copy()
                result["similarity_score"] = float(1 / (1 + distance))
                results.append(result)

        log("conversation_index", f"Found {len(results)} relevant conversations")
        return results

    def get_relevant_context(
        self, current_query: str, top_k: Optional[int] = None
    ) -> str:
        """Get formatted context from relevant past conversations"""
        relevant_convos = self.search_conversations(current_query, top_k)

        if not relevant_convos:
            return None

        context_parts = ["## Relevant Past Conversations:\n"]

        for i, convo in enumerate(relevant_convos, 1):
            timestamp_str = datetime.fromtimestamp(convo["timestamp"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            context_parts.append(
                f"\n### {i}. Past Conversation (Similarity: {convo['similarity_score']:.2%})"
            )
            context_parts.append(f"**Date:** {timestamp_str}")
            context_parts.append(f"**Query:** {convo['initial_query']}")

            if convo.get("tool_calls"):
                context_parts.append(
                    f"**Tools Used:** {', '.join(convo['tool_calls'])}"
                )

            if convo.get("final_answer"):
                answer = convo["final_answer"]
                if len(answer) > 200:
                    answer = answer[:200] + "..."
                context_parts.append(f"**Result:** {answer}")

            context_parts.append(f"**Success:** {'✅' if convo['success'] else '❌'}")
            context_parts.append("")

        return "\n".join(context_parts)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about indexed conversations"""
        if not self.metadata:
            return {"total_conversations": 0}

        total = len(self.metadata)
        successful = sum(1 for m in self.metadata if m.get("success"))

        tool_usage = {}
        for m in self.metadata:
            for tool in m.get("tool_calls", []):
                tool_usage[tool] = tool_usage.get(tool, 0) + 1

        return {
            "total_conversations": total,
            "successful_conversations": successful,
            "success_rate": successful / total if total > 0 else 0,
            "most_used_tools": sorted(
                tool_usage.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "indexed_files": len(self.cache),
        }
