
import os
import ollama
from dotenv import load_dotenv

# Load environment variables if not already loaded
load_dotenv()

def get_ollama_client() -> ollama.AsyncClient:
    """
    Returns an async Ollama client configured for local execution.
    """
    return ollama.AsyncClient()
