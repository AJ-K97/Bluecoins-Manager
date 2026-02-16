
import os
import ollama
from dotenv import load_dotenv

# Load environment variables if not already loaded
load_dotenv()

def get_ollama_client() -> ollama.AsyncClient:
    """
    Returns an async Ollama client configured with the OLLAMA_HOST environment variable.
    Defaults to 127.0.0.1:11434 if not set.
    """
    host = os.getenv("OLLAMA_HOST")
    if host:
        # print(f"DEBUG: Connecting to Ollama at {host}")
        return ollama.AsyncClient(host=host)
    else:
        # print("DEBUG: Connecting to Ollama at default localhost")
        return ollama.AsyncClient()
