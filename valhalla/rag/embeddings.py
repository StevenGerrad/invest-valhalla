"""bge-small-zh-v1.5 embedding 封装"""
import numpy as np


class BGEEmbedder:
    """bge-small-zh-v1.5 向量化器，单例懒加载"""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        self._model_name = model_name
        self._model = None

    @property
    def dim(self) -> int:
        return 512

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        return self._model.encode(texts, normalize_embeddings=True)

    def encode_single(self, text: str) -> np.ndarray:
        return self.encode([text])[0]
