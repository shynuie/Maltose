"""Configuration for the local Document Knowledge Base."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeConfig:
    documents_root: Path = field(default_factory=lambda: Path("documents"))
    metadata_path: Path = field(default_factory=lambda: Path("data/knowledge/metadata.sqlite3"))
    vectors_path: Path = field(default_factory=lambda: Path("data/knowledge/vectors.lancedb"))
    queue_path: Path = field(default_factory=lambda: Path("data/knowledge/indexing_queue.sqlite3"))
    supported_extensions: tuple[str, ...] = (".pdf", ".txt", ".md")
    chunk_size: int = 1200
    chunk_overlap: int = 150
    watcher_poll_interval: float = 1.0
    indexing_max_attempts: int = 3

    def resolved(self, *, base_dir: Path | None = None) -> "KnowledgeConfig":
        base = (base_dir or Path.cwd()).expanduser().resolve()

        def resolve(path: Path) -> Path:
            return path.expanduser() if path.is_absolute() else base / path

        return KnowledgeConfig(
            documents_root=resolve(self.documents_root),
            metadata_path=resolve(self.metadata_path),
            vectors_path=resolve(self.vectors_path),
            queue_path=resolve(self.queue_path),
            supported_extensions=tuple(extension.lower() for extension in self.supported_extensions),
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            watcher_poll_interval=self.watcher_poll_interval,
            indexing_max_attempts=self.indexing_max_attempts,
        )
