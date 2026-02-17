
import os
import ollama
from dotenv import load_dotenv

# Load environment variables if not already loaded
load_dotenv()

def get_ollama_client() -> ollama.AsyncClient:
    """
    Returns an async Ollama client.
    Uses OLLAMA_HOST when provided, otherwise defaults to Ollama's local endpoint.
    """
    host = (os.getenv("OLLAMA_HOST") or "").strip()
    if host:
        return ollama.AsyncClient(host=host)
    return ollama.AsyncClient()
