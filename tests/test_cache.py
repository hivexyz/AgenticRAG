from types import SimpleNamespace

import pytest

from app.models.embedding import EmbeddingManager, embedding_cache


class FakeEmbeddingClient:
    def __init__(self):
        self.calls = []
        self.embeddings = self

    async def create(self, *, model, input, encoding_format):
        self.calls.append({"model": model, "input": input, "encoding_format": encoding_format})
        if isinstance(input, list):
            data = [SimpleNamespace(embedding=[float(index), 0.0]) for index, _ in enumerate(input, 1)]
        else:
            data = [SimpleNamespace(embedding=[1.0, 0.0])]
        return SimpleNamespace(data=data)


@pytest.mark.asyncio
async def test_embedding_manager_reuses_cached_single_embedding():
    embedding_cache.clear()
    manager = EmbeddingManager()
    client = FakeEmbeddingClient()
    manager.client = client

    first = await manager.create_embedding("重复问题")
    second = await manager.create_embedding("重复问题")

    assert first == second == [1.0, 0.0]
    assert len(client.calls) == 1
    stats = embedding_cache.snapshot()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
