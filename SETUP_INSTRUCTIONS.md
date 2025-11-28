# 🚀 Setup Instructions

## Missing Dependencies

To get all features working, you need to install these additional packages:

### Required for Nomic Embeddings
```bash
uv pip install einops
```

### Complete Setup Command
```bash
# Install all missing dependencies
uv pip install sentence-transformers einops
```

## Current Status

### ✅ Working
- Ollama is running
- phi4:latest model installed
- gemma3:12b model installed
- sentence-transformers installed

### ⚠️ Needs Installation
- `einops` - Required by nomic embeddings

## Quick Start

1. **Install missing dependency:**
   ```bash
   cd /Users/ramkrishna.potdar/Downloads/S9
   uv pip install einops
   ```

2. **Test embeddings:**
   ```bash
   python -c "from modules.conversation_indexer_simple import ConversationIndexer; indexer = ConversationIndexer(); print('✅ All systems ready!')"
   ```

3. **Run the agent:**
   ```bash
   python agent.py
   ```

## Alternative: Use Ollama for Embeddings

If you prefer not to install additional dependencies, you can use Ollama for embeddings:

1. **Pull nomic embedding model in Ollama:**
   ```bash
   ollama pull nomic-embed-text
   ```

2. **Update config/models.json:**
   
   Add this to the "models" section:
   ```json
   "nomic-ollama": {
     "type": "ollama",
     "model": "nomic-embed-text",
     "embedding_model": "nomic-embed-text",
     "url": {
       "generate": "http://localhost:11434/api/generate",
       "embed": "http://localhost:11434/api/embeddings"
     }
   }
   ```
   
   Change the default:
   ```json
   "defaults": {
     "text_generation": "gemini",
     "embedding": "nomic-ollama"
   }
   ```

## Verification

After installing dependencies, verify everything works:

```bash
# Test embeddings
python demo_conversation_indexing.py

# Test the full agent
python agent.py
```

## Troubleshooting

### Issue: "No module named 'einops'"
**Solution:** Run `uv pip install einops`

### Issue: "trust_remote_code" error
**Solution:** Already fixed in the code. The models now use `trust_remote_code=True`

### Issue: Ollama connection refused
**Solution:** Make sure Ollama is running: `ollama serve`

### Issue: Model not found in Ollama
**Solution:** Pull the model: `ollama pull phi4` or `ollama pull gemma3:12b`
