import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import faiss
import numpy as np
import pymupdf4llm
import requests
import trafilatura
from markitdown import MarkItDown
from mcp.server.fastmcp import FastMCP, Image
from pydantic import BaseModel
from tqdm import tqdm

# Try to import sentence_transformers, but make it optional
try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None

from models import (
    AddInput,
    AddOutput,
    ChunkListOutput,
    ExpSumInput,
    ExpSumOutput,
    FilePathInput,
    MarkdownInput,
    MarkdownOutput,
    PythonCodeInput,
    PythonCodeOutput,
    SearchDocumentsInput,
    SqrtInput,
    SqrtOutput,
    StringsToIntsInput,
    StringsToIntsOutput,
    UrlInput,
)

mcp = FastMCP("Calculator")

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config" / "models.json"
with open(CONFIG_PATH, "r") as f:
    MODEL_CONFIG = json.load(f)

# Get default embedding model from config
DEFAULT_EMBED_MODEL = MODEL_CONFIG["defaults"]["embedding"]
EMBED_MODEL_CONFIG = MODEL_CONFIG["models"][DEFAULT_EMBED_MODEL]

# Initialize embedding model based on type
if EMBED_MODEL_CONFIG["type"] == "huggingface":
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Run 'uv pip install sentence-transformers einops' or change embedding to Ollama in config/models.json"
        )
    EMBEDDING_MODEL = SentenceTransformer(
        EMBED_MODEL_CONFIG["model"], trust_remote_code=True
    )
    USE_OLLAMA_EMBEDDINGS = False
elif EMBED_MODEL_CONFIG["type"] == "ollama":
    EMBED_URL = EMBED_MODEL_CONFIG["url"]["embed"]
    EMBED_MODEL = EMBED_MODEL_CONFIG["embedding_model"]
    USE_OLLAMA_EMBEDDINGS = True
else:
    raise ValueError(f"Unsupported embedding model type: {EMBED_MODEL_CONFIG['type']}")

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_URL = "http://localhost:11434/api/generate"
GEMMA_MODEL = "gemma3:12b"
PHI_MODEL = "phi4:latest"
QWEN_MODEL = "qwen2.5:32b-instruct-q4_0 "
CHUNK_SIZE = 256
CHUNK_OVERLAP = 40
MAX_CHUNK_LENGTH = 512  # characters
TOP_K = 3  # FAISS top-K matches
ROOT = Path(__file__).parent.resolve()


def get_embedding(text: str) -> np.ndarray:
    """Get text embeddings using configured model (HuggingFace or Ollama)"""
    if USE_OLLAMA_EMBEDDINGS:
        result = requests.post(EMBED_URL, json={"model": EMBED_MODEL, "prompt": text})
        result.raise_for_status()
        return np.array(result.json()["embedding"], dtype=np.float32)
    else:
        # Use HuggingFace sentence-transformers
        embedding = EMBEDDING_MODEL.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    for i in range(0, len(words), size - overlap):
        yield " ".join(words[i : i + size])


def mcp_log(level: str, message: str) -> None:
    sys.stderr.write(f"{level}: {message}\n")
    sys.stderr.flush()


# === CHUNKING ===


def are_related(chunk1: str, chunk2: str, index: int) -> bool:
    prompt = f"""
You are helping to segment a document into topic-based chunks. Unfortunately, the sentences are mixed up.

CHUNK 1: "{chunk1}"
CHUNK 2: "{chunk2}"

Should these two chunks appear in the **same paragraph or flow of writing**?

Even if the subject changes slightly (e.g., One person to another), treat them as related **if they belong to the same broader context or topic** (like cricket, AI, or real estate).

Also consider cues like continuity words (e.g., "However", "But", "Also") or references that link the sentences.

Answer with:
Yes – if the chunks should appear together in the same paragraph or section
No – if they are about different topics and should be separated

Just respond in one word (Yes or No), and do not provide any further explanation.
"""
    print(f"\n🔍 Comparing chunk {index} and {index + 1}")
    print(f"  Chunk {index} → {chunk1[:60]}{'...' if len(chunk1) > 60 else ''}")
    print(f"  Chunk {index + 1} → {chunk2[:60]}{'...' if len(chunk2) > 60 else ''}")

    result = requests.post(
        OLLAMA_CHAT_URL,
        json={
            "model": PHI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
    )
    result.raise_for_status()
    reply = result.json().get("message", {}).get("content", "").strip().lower()
    print(f"  ✅ Model reply: {reply}")
    return reply.startswith("yes")


@mcp.tool()
def search_stored_documents(input: SearchDocumentsInput) -> list[str]:
    """Search documents to get relevant extracts. Usage: input={"input": {"query": "your query"}} result = await mcp.call_tool('search_stored_documents', input)"""

    ensure_faiss_ready()
    query = input.query
    mcp_log("SEARCH", f"Query: {query}")
    try:
        index_path = ROOT / "faiss_index" / "index.bin"
        metadata_path = ROOT / "faiss_index" / "metadata.json"
        
        if not index_path.exists():
            return ["ERROR: FAISS index not found. Please ensure documents are indexed."]
            
        index = faiss.read_index(str(index_path))
        metadata = json.loads(metadata_path.read_text())
        
        mcp_log("SEARCH", f"Generating embedding for query: {query}")
        query_vec = get_embedding(query).reshape(1, -1)
        
        mcp_log("SEARCH", f"Searching index with {index.ntotal} vectors")
        D, I = index.search(query_vec, k=5)
        
        results = []
        for idx in I[0]:
            if idx == -1: continue
            if idx >= len(metadata):
                mcp_log("WARN", f"Index {idx} out of bounds for metadata (len={len(metadata)})")
                continue
                
            data = metadata[idx]
            results.append(
                f"{data['chunk']}\n[Source: {data['doc']}, ID: {data['chunk_id']}]"
            )
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        mcp_log("ERROR", f"Search failed: {str(e)}")
        return [f"ERROR: Failed to search: {str(e)}"]


def caption_image(img_url_or_path: str) -> str:
    mcp_log("CAPTION", f"🖼️ Attempting to caption image: {img_url_or_path}")

    if not img_url_or_path or not img_url_or_path.strip():
        return ""

    full_path = Path(__file__).parent / "documents" / img_url_or_path
    full_path = full_path.resolve()

    if not full_path.exists() or not full_path.is_file():
        mcp_log("ERROR", f"❌ Image file not found or is a directory: {full_path}")
        return f"[Image file not found: {img_url_or_path}]"

    try:
        if img_url_or_path.startswith("http"):  # for extract_web_pages
            result = requests.get(img_url_or_path)
            encoded_image = base64.b64encode(result.content).decode("utf-8")
        else:
            with open(full_path, "rb") as img_file:
                encoded_image = base64.b64encode(img_file.read()).decode("utf-8")

        # Set stream=True to get the full generator-style output
        with requests.post(
            OLLAMA_URL,
            json={
                "model": GEMMA_MODEL,
                "prompt": "If there is lot of text in the image, then ONLY reply back with exact text in the image, else Describe the image such that your result can replace 'alt-text' for it. Only explain the contents of the image and provide no further explaination.",
                "images": [encoded_image],
                "stream": True,
            },
            stream=True,
        ) as result:
            caption_parts = []
            for line in result.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    caption_parts.append(data.get("result", ""))
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue  # silently skip malformed lines

            caption = "".join(caption_parts).strip()
            mcp_log("CAPTION", f"✅ Caption generated: {caption}")
            return caption if caption else "[No caption returned]"

    except Exception as e:
        mcp_log("ERROR", f"⚠️ Failed to caption image {img_url_or_path}: {e}")
        return f"[Image could not be processed: {img_url_or_path}]"


def replace_images_with_captions(markdown: str) -> str:
    def replace(match):
        alt, src = match.group(1), match.group(2)
        if not src or not src.strip():
            return match.group(0)

        try:
            caption = caption_image(src)
            # Attempt to delete only if local and file exists
            if not src.startswith("http"):
                img_path = Path(__file__).parent / "documents" / src
                if img_path.exists() and img_path.is_file():
                    img_path.unlink()
                    mcp_log("INFO", f"🗑️ Deleted image after captioning: {img_path}")
            return f"**Image:** {caption}"
        except Exception as e:
            mcp_log("WARN", f"Image deletion failed: {e}")
            return f"[Image could not be processed: {src}]"

    return re.sub(r"!\[(.*?)\]\((.*?)\)", replace, markdown)


@mcp.tool()
def convert_webpage_url_into_markdown(input: UrlInput) -> MarkdownOutput:
    """Return clean webpage content without Ads, and clutter. Usage: input={{"input": {{"url": "https://example.com"}}}} result = await mcp.call_tool('convert_webpage_url_into_markdown', input)"""

    downloaded = trafilatura.fetch_url(input.url)
    if not downloaded:
        return MarkdownOutput(markdown="Failed to download the webpage.")

    markdown = (
        trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            include_images=True,
            output_format="markdown",
        )
        or ""
    )

    markdown = replace_images_with_captions(markdown)
    return MarkdownOutput(markdown=markdown)


@mcp.tool()
def extract_pdf(input: FilePathInput) -> MarkdownOutput:
    """Convert PDF to markdown. Usage: input={"input": {"file_path": "documents/sample.pdf"} } result = await mcp.call_tool('extract_pdf', input)"""

    if not os.path.exists(input.file_path):
        return MarkdownOutput(markdown=f"File not found: {input.file_path}")

    ROOT = Path(__file__).parent.resolve()
    global_image_dir = ROOT / "documents" / "images"
    global_image_dir.mkdir(parents=True, exist_ok=True)

    # Actual markdown with relative image paths
    markdown = pymupdf4llm.to_markdown(
        input.file_path, write_images=True, image_path=str(global_image_dir)
    )

    # Re-point image links in the markdown
    markdown = re.sub(
        r"!\[\]\((.*?/images/)([^)]+)\)", r"![](images/\2)", markdown.replace("\\", "/")
    )

    markdown = replace_images_with_captions(markdown)
    return MarkdownOutput(markdown=markdown)


def semantic_merge(text: str) -> list[str]:
    """Splits text semantically using LLM: detects second topic and reuses leftover intelligently."""
    WORD_LIMIT = 512
    words = text.split()
    i = 0
    final_chunks = []

    while i < len(words):
        # 1. Take next chunk of words (and prepend leftovers if any)
        chunk_words = words[i : i + WORD_LIMIT]
        chunk_text = " ".join(chunk_words).strip()

        prompt = f"""
You are a markdown document segmenter.

Here is a portion of a markdown document:

---
{chunk_text}
---

If this chunk clearly contains **more than one distinct topic or section**, reply ONLY with the **second part**, starting from the first sentence or heading of the new topic.

If it's only one topic, reply with NOTHING.

Keep markdown formatting intact.
"""

        try:
            result = requests.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": PHI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            reply = result.json().get("message", {}).get("content", "").strip()

            if reply:
                # If LLM returned second part, separate it
                split_point = chunk_text.find(reply)
                if split_point != -1:
                    first_part = chunk_text[:split_point].strip()
                    second_part = reply.strip()

                    final_chunks.append(first_part)

                    # Get remaining words from second_part and re-use them in next batch
                    leftover_words = second_part.split()
                    words = leftover_words + words[i + WORD_LIMIT :]
                    i = 0  # restart loop with leftover + remaining
                    continue
                else:
                    # fallback: if split point not found
                    final_chunks.append(chunk_text)
            else:
                final_chunks.append(chunk_text)

        except Exception as e:
            mcp_log("ERROR", f"Semantic chunking LLM error: {e}")
            final_chunks.append(chunk_text)

        i += WORD_LIMIT

    return final_chunks


def process_documents():
    """Process documents and create FAISS index using unified multimodal strategy."""
    mcp_log("INFO", "Indexing documents with unified RAG pipeline...")
    ROOT = Path(__file__).parent.resolve()
    DOC_PATH = ROOT / "documents"
    INDEX_CACHE = ROOT / "faiss_index"
    INDEX_CACHE.mkdir(exist_ok=True)
    INDEX_FILE = INDEX_CACHE / "index.bin"
    METADATA_FILE = INDEX_CACHE / "metadata.json"
    CACHE_FILE = INDEX_CACHE / "doc_index_cache.json"

    def file_hash(path):
        return hashlib.md5(Path(path).read_bytes()).hexdigest()

    CACHE_META = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    metadata = json.loads(METADATA_FILE.read_text()) if METADATA_FILE.exists() else []
    index = faiss.read_index(str(INDEX_FILE)) if INDEX_FILE.exists() else None

    for file in DOC_PATH.glob("*.*"):
        fhash = file_hash(file)
        if file.name in CACHE_META and CACHE_META[file.name] == fhash:
            mcp_log("SKIP", f"Skipping unchanged file: {file.name}")
            continue

        mcp_log("PROC", f"Processing: {file.name}")
        try:
            ext = file.suffix.lower()
            markdown = ""

            if ext == ".pdf":
                mcp_log("INFO", f"Using MuPDF4LLM to extract {file.name}")
                markdown = extract_pdf(FilePathInput(file_path=str(file))).markdown

            elif ext in [".html", ".htm", ".url"]:
                mcp_log("INFO", f"Using Trafilatura to extract {file.name}")
                markdown = extract_webpage(
                    UrlInput(url=file.read_text().strip())
                ).markdown

            else:
                # Fallback to MarkItDown for other formats
                converter = MarkItDown()
                mcp_log("INFO", f"Using MarkItDown fallback for {file.name}")
                markdown = converter.convert(str(file)).text_content

            if not markdown.strip():
                mcp_log("WARN", f"No content extracted from {file.name}")
                continue

            if len(markdown.split()) < 10:
                mcp_log(
                    "WARN",
                    f"Content too short for semantic merge in {file.name} → Skipping chunking.",
                )
                chunks = [markdown.strip()]
            else:
                mcp_log(
                    "INFO",
                    f"Running semantic merge on {file.name} with {len(markdown.split())} words",
                )
                chunks = semantic_merge(markdown)

            embeddings_for_file = []
            new_metadata = []
            for i, chunk in enumerate(tqdm(chunks, desc=f"Embedding {file.name}")):
                embedding = get_embedding(chunk)
                embeddings_for_file.append(embedding)
                new_metadata.append(
                    {"doc": file.name, "chunk": chunk, "chunk_id": f"{file.stem}_{i}"}
                )

            if embeddings_for_file:
                if index is None:
                    dim = len(embeddings_for_file[0])
                    index = faiss.IndexFlatL2(dim)
                index.add(np.stack(embeddings_for_file))
                metadata.extend(new_metadata)
                CACHE_META[file.name] = fhash

                # ✅ Immediately save index and metadata
                CACHE_FILE.write_text(json.dumps(CACHE_META, indent=2))
                METADATA_FILE.write_text(json.dumps(metadata, indent=2))
                faiss.write_index(index, str(INDEX_FILE))
                mcp_log(
                    "SAVE",
                    f"Saved FAISS index and metadata after processing {file.name}",
                )

        except Exception as e:
            mcp_log("ERROR", f"Failed to process {file.name}: {e}")


def ensure_faiss_ready():
    from pathlib import Path

    index_path = ROOT / "faiss_index" / "index.bin"
    meta_path = ROOT / "faiss_index" / "metadata.json"
    if not (index_path.exists() and meta_path.exists()):
        mcp_log("INFO", "Index not found — running process_documents()...")
        process_documents()
    else:
        mcp_log("INFO", "Index already exists. Skipping regeneration.")


if __name__ == "__main__":
    print("STARTING THE SERVER AT AMAZING LOCATION")

    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()  # Run without transport for dev server
    else:
        # Start the server in a separate thread
        import threading

    from pathlib import Path

    index_path = ROOT / "faiss_index" / "index.bin"
    meta_path = ROOT / "faiss_index" / "metadata.json"
    if not (index_path.exists() and meta_path.exists()):
        mcp_log("INFO", "Index not found — running process_documents()...")
        process_documents()
    else:
        mcp_log("INFO", "Index already exists. Skipping regeneration.")


if __name__ == "__main__":
    print("STARTING THE SERVER AT AMAZING LOCATION")

    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()  # Run without transport for dev server
    else:
        # Start the server in a separate thread
        import threading

        server_thread = threading.Thread(target=lambda: mcp.run(transport="stdio"))
        server_thread.daemon = True
        server_thread.start()

        # Wait a moment for the server to start
        time.sleep(2)

        # Process documents after server is running
        process_documents()

        # Keep the main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
