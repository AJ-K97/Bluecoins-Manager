import os
from pathlib import Path
from typing import List, Optional

import ollama
from dotenv import load_dotenv, set_key

# Load environment variables if not already loaded
load_dotenv()
_OLLAMA_CLIENT = None
_DEFAULT_CHAT_MODEL = "llama3.1:8b"
_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"


def get_default_ollama_model() -> str:
    value = (os.getenv("OLLAMA_MODEL") or "").strip()
    return value or _DEFAULT_CHAT_MODEL


def get_default_embedding_model() -> str:
    value = (os.getenv("OLLAMA_EMBEDDING_MODEL") or "").strip()
    return value or _DEFAULT_EMBEDDING_MODEL


def get_env_file_path() -> Path:
    # src/ai_config.py -> project root/.env
    return Path(__file__).resolve().parents[1] / ".env"


def set_default_ollama_model(model_name: str, env_path: Optional[Path] = None) -> Path:
    model_name = (model_name or "").strip()
    if not model_name:
        raise ValueError("Model name cannot be empty.")

    target_path = Path(env_path) if env_path else get_env_file_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_path.exists():
        target_path.touch()

    set_key(str(target_path), "OLLAMA_MODEL", model_name, quote_mode="never")
    os.environ["OLLAMA_MODEL"] = model_name
    return target_path


def _extract_model_name(row) -> str:
    if isinstance(row, dict):
        return str((row.get("model") or row.get("name") or "")).strip()
    return str((getattr(row, "model", None) or getattr(row, "name", None) or "")).strip()


async def list_available_ollama_models() -> List[str]:
    response = await get_ollama_client().list()
    raw_models = []
    if isinstance(response, dict):
        raw_models = response.get("models") or []
    else:
        raw_models = getattr(response, "models", []) or []

    names = []
    for row in raw_models:
        name = _extract_model_name(row)
        if name:
            names.append(name)
    return sorted(set(names))


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
