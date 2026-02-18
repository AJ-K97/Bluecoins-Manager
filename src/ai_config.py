
import os
import ollama
from dotenv import load_dotenv

# Load environment variables if not already loaded
load_dotenv()
_OLLAMA_CLIENT = None

def get_ollama_client() -> ollama.AsyncClient:
    """
    Returns an async Ollama client.
    Uses OLLAMA_HOST when provided, otherwise defaults to Ollama's local endpoint.
    """
    global _OLLAMA_CLIENT
    if _OLLAMA_CLIENT is not None:
        return _OLLAMA_CLIENT

    host = (os.getenv("OLLAMA_HOST") or "").strip()
    if host:
        _OLLAMA_CLIENT = ollama.AsyncClient(host=host)
    else:
        _OLLAMA_CLIENT = ollama.AsyncClient()
    return _OLLAMA_CLIENT


async def close_ollama_client():
    """
    Gracefully close the shared AsyncClient transport to avoid socket warnings.
    """
    global _OLLAMA_CLIENT
    if _OLLAMA_CLIENT is None:
        return
    try:
        transport = getattr(_OLLAMA_CLIENT, "_client", None)
        if transport is not None and hasattr(transport, "aclose"):
            await transport.aclose()
    except Exception:
        pass
    finally:
        _OLLAMA_CLIENT = None
