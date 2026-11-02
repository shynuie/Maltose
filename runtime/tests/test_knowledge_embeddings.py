from __future__ import annotations

import unittest

from maltose.knowledge.embeddings import LazyEmbeddingProvider


class FakeProvider:
    def __init__(self, counter):
        self.counter = counter
        self.counter["created"] += 1

    def embed(self, text):
        return [float(len(text))]


class KnowledgeEmbeddingTests(unittest.TestCase):
    def test_lazy_provider_does_not_construct_until_first_embed(self):
        counter = {"created": 0}
        provider = LazyEmbeddingProvider(lambda: FakeProvider(counter))

        self.assertEqual(counter["created"], 0)
        self.assertEqual(provider.embed("hello"), [5.0])
        self.assertEqual(counter["created"], 1)
        self.assertEqual(provider.embed("world"), [5.0])
        self.assertEqual(counter["created"], 1)


if __name__ == "__main__":
    unittest.main()
