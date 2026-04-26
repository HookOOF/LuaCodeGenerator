from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b-instruct-q4_K_M"
    ollama_num_ctx: int = 4096
    ollama_num_predict: int = 256
    qdrant_url: str = ""
    qdrant_local_path: str = "./qdrant_storage"
    qdrant_collection: str = "lua_knowledge"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    chat_storage_dir: str = "./chat_storage"
    summary_max_tokens: int = 400
    context_reserve_ratio: float = 0.9

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
