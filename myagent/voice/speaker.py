from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
import wave
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeakerResult:
    user_id: str | None
    score: float | None
    status: Literal["identified", "unknown", "ambiguous"]


class SpeakerIdentifier(Protocol):
    def identify(self, audio_path: Path) -> SpeakerResult:
        """Identify the speaker from a completed utterance recording."""
        ...


class SpeakerIdentityManager:
    """Asynchronously track the current speaker with hysteresis."""

    def __init__(
        self,
        identifier: SpeakerIdentifier,
        *,
        low_threshold: float = 0.2,
        high_threshold: float = 0.35,
    ) -> None:
        if not 0.0 <= low_threshold < high_threshold <= 1.0:
            raise ValueError("Speaker identity thresholds must satisfy 0 <= low < high <= 1.")
        self.identifier = identifier
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speaker-id")
        self._state = SpeakerResult(None, None, "unknown")

    def snapshot(self) -> SpeakerResult:
        with self._lock:
            return self._state

    def submit(self, audio_path: Path) -> Future[SpeakerResult]:
        # Do not let a previous identity authorize this turn while the new
        # utterance is still being evaluated.  A completed mid-band result
        # may hold the user as ``ambiguous``; an unfinished result must also
        # remain non-authorizing.
        with self._lock:
            if self._state.user_id is not None:
                self._state = SpeakerResult(
                    self._state.user_id, None, "ambiguous"
                )
        future = self._executor.submit(self.identifier.identify, audio_path)
        future.add_done_callback(self._apply_result)
        return future

    def _apply_result(self, future: Future[SpeakerResult]) -> None:
        try:
            result = future.result()
        except Exception:
            logger.exception("speaker_identity_worker_failed")
            result = SpeakerResult(None, None, "unknown")
        with self._lock:
            self._state = self._transition(self._state, result)
            logger.info(
                "speaker_identity_state user_id=%s score=%s status=%s",
                self._state.user_id,
                self._state.score,
                self._state.status,
            )

    def _transition(
        self, current: SpeakerResult, candidate: SpeakerResult
    ) -> SpeakerResult:
        score = candidate.score
        if score is None or score < self.low_threshold:
            return SpeakerResult(None, score, "unknown")
        if score >= self.high_threshold and candidate.user_id is not None:
            return SpeakerResult(candidate.user_id, score, "identified")
        if current.user_id is not None:
            return SpeakerResult(current.user_id, score, "ambiguous")
        return SpeakerResult(None, score, "unknown")

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class SpeakerEmbeddingEncoder(Protocol):
    """Backend that turns a completed utterance into a normalized embedding."""

    model_name: str

    def encode(self, audio_path: Path) -> list[float]:
        ...


def _normalize(values: Iterable[float]) -> list[float]:
    vector = [float(value) for value in values]
    norm = sum(value * value for value in vector) ** 0.5
    if norm <= 0.0:
        raise ValueError("Speaker embedding cannot be zero-valued.")
    return [value / norm for value in vector]


class SpeakerProfileStore:
    """Small SQLite store for enrolled, normalized speaker voiceprints."""

    def __init__(self, path: str | Path = "data/speaker_profiles.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, timeout=30
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS speaker_profiles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL UNIQUE,
                    embedding_json TEXT NOT NULL,
                    embeddings_json TEXT,
                    embedding_model TEXT NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in self._connection.execute(
                    "PRAGMA table_info(speaker_profiles)"
                ).fetchall()
            }
            if "embeddings_json" not in columns:
                self._connection.execute(
                    "ALTER TABLE speaker_profiles ADD COLUMN embeddings_json TEXT"
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS speaker_id_counters (
                    prefix TEXT PRIMARY KEY,
                    next_number INTEGER NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def next_user_id(self, prefix: str = "user") -> str:
        """Return the next stable system user id without reusing ids."""
        next_number = self._next_user_number(prefix)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO speaker_id_counters(prefix, next_number) VALUES (?, ?) "
                "ON CONFLICT(prefix) DO UPDATE SET next_number = excluded.next_number",
                (prefix, next_number + 1),
            )
        return f"{prefix}-{next_number:03d}"

    def peek_next_user_id(self, prefix: str = "user") -> str:
        """Return the next ID without reserving it until enrollment is confirmed."""
        return f"{prefix}-{self._next_user_number(prefix):03d}"

    def _next_user_number(self, prefix: str) -> int:
        if not prefix or not re.fullmatch(r"[a-z][a-z0-9_-]*", prefix):
            raise ValueError("Speaker id prefix must contain lowercase letters, digits, _ or -.")
        with self._lock:
            counter = self._connection.execute(
                "SELECT next_number FROM speaker_id_counters WHERE prefix = ?",
                (prefix,),
            ).fetchone()
            if counter is None:
                rows = self._connection.execute(
                    "SELECT user_id FROM speaker_profiles WHERE user_id LIKE ?",
                    (f"{prefix}-%",),
                ).fetchall()
                numbers = []
                for row in rows:
                    match = re.fullmatch(
                        rf"{re.escape(prefix)}-(\d+)", row["user_id"]
                    )
                    if match:
                        numbers.append(int(match.group(1)))
                return max(numbers, default=0) + 1
            return int(counter["next_number"])

    def enroll(
        self,
        user_id: str,
        embeddings: Iterable[Iterable[float]],
        *,
        model_name: str,
    ) -> dict[str, object]:
        user_id = user_id.strip()
        if not user_id:
            raise ValueError("Speaker user_id cannot be empty.")
        vectors = [_normalize(embedding) for embedding in embeddings]
        if not vectors:
            raise ValueError("At least one speaker embedding is required.")
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("Speaker embeddings must have the same dimension.")
        averaged = _normalize(
            sum(vector[index] for vector in vectors) for index in range(dimension)
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT id, created_at, sample_count FROM speaker_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            profile_id = existing["id"] if existing else str(uuid.uuid4())
            created_at = existing["created_at"] if existing else now
            self._connection.execute(
                """
                INSERT INTO speaker_profiles (
                    id, user_id, embedding_json, embedding_model, sample_count,
                    embeddings_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    embedding_json = excluded.embedding_json,
                    embeddings_json = excluded.embeddings_json,
                    embedding_model = excluded.embedding_model,
                    sample_count = excluded.sample_count,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_id,
                    user_id,
                    json.dumps(averaged),
                    model_name,
                    len(vectors),
                    json.dumps(vectors),
                    created_at,
                    now,
                ),
            )
        return {
            "user_id": user_id,
            "embedding_model": model_name,
            "sample_count": len(vectors),
            "dimension": dimension,
            "updated_at": now,
        }

    def list_profiles(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT user_id, embedding_model, sample_count, created_at, updated_at "
                "FROM speaker_profiles ORDER BY user_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def profiles(self) -> list[tuple[str, list[float], str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT user_id, embedding_json, embedding_model FROM speaker_profiles"
            ).fetchall()
        return [
            (row["user_id"], json.loads(row["embedding_json"]), row["embedding_model"])
            for row in rows
        ]

    def profile_embeddings(self) -> list[tuple[str, list[list[float]], str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT user_id, embedding_json, embeddings_json, embedding_model "
                "FROM speaker_profiles"
            ).fetchall()
        result = []
        for row in rows:
            embeddings = (
                json.loads(row["embeddings_json"])
                if row["embeddings_json"]
                else [json.loads(row["embedding_json"])]
            )
            result.append((row["user_id"], embeddings, row["embedding_model"]))
        return result


class ProfileSpeakerIdentifier:
    """Identify a speaker against enrolled profiles using cosine similarity."""

    def __init__(
        self,
        store: SpeakerProfileStore,
        encoder: SpeakerEmbeddingEncoder,
        *,
        threshold: float = 0.35,
    ) -> None:
        if not -1.0 <= threshold <= 1.0:
            raise ValueError("Speaker threshold must be between -1 and 1.")
        self.store = store
        self.encoder = encoder
        self.threshold = threshold

    def identify(self, audio_path: Path) -> SpeakerResult:
        profiles = self.store.profile_embeddings()
        if not profiles:
            return SpeakerResult(None, None, "unknown")
        try:
            embedding = _normalize(self.encoder.encode(audio_path))
        except Exception:
            logger.exception("speaker_identification_failed path=%s", audio_path)
            return SpeakerResult(None, None, "unknown")
        best_user_id: str | None = None
        best_score = -1.0
        for user_id, profile_embeddings, _model_name in profiles:
            for profile in profile_embeddings:
                if len(profile) != len(embedding):
                    logger.warning("speaker_profile_dimension_mismatch user_id=%s", user_id)
                    continue
                score = sum(left * right for left, right in zip(embedding, profile))
                if score > best_score:
                    best_user_id, best_score = user_id, score
        if best_user_id is None or best_score < self.threshold:
            return SpeakerResult(None, best_score if best_score >= -1.0 else None, "unknown")
        return SpeakerResult(best_user_id, best_score, "identified")


class SpeechBrainECAPAEncoder:
    """Lazy SpeechBrain ECAPA-TDNN encoder for local speaker embeddings."""

    model_name = "speechbrain/spkrec-ecapa-voxceleb"

    def __init__(
        self,
        *,
        source: str = model_name,
        savedir: str | Path = "data/models/speechbrain-ecapa",
        device: str = "cpu",
    ) -> None:
        self.model_name = source
        self.savedir = str(savedir)
        self.device = device
        self._classifier = None

    def _load(self):
        if self._classifier is None:
            try:
                import torch
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError as exc:
                raise RuntimeError(
                    "SpeechBrain speaker support is not installed. "
                    "Run: uv sync --extra speaker"
                ) from exc
            self._torch = torch
            self._classifier = EncoderClassifier.from_hparams(
                source=self.model_name,
                savedir=self.savedir,
                run_opts={"device": self.device},
            )
        return self._classifier

    def encode(self, audio_path: Path) -> list[float]:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "PyTorch is required for SpeechBrain speaker support. "
                "Run: uv sync --extra speaker"
            ) from exc
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            pcm = wav_file.readframes(frame_count)
        if sample_width != 2:
            raise ValueError("Speaker enrollment WAV must use 16-bit PCM.")
        waveform = torch.frombuffer(bytearray(pcm), dtype=torch.int16).to(torch.float32)
        if channels > 1:
            waveform = waveform.reshape(-1, channels).mean(dim=1)
        waveform = waveform.unsqueeze(0) / 32768.0
        if sample_rate != 16000:
            target_length = round(waveform.shape[-1] * 16000 / sample_rate)
            waveform = torch.nn.functional.interpolate(
                waveform.unsqueeze(1),
                size=target_length,
                mode="linear",
                align_corners=False,
            ).squeeze(1)
        classifier = self._load()
        with self._torch.no_grad():
            embedding = classifier.encode_batch(waveform.to(self.device))
        return _normalize(embedding.squeeze().detach().cpu().tolist())


class NullSpeakerIdentifier:
    """Fallback until a concrete local speaker model is configured.

    When ``trusted_user_id`` is provided by the CLI, the application is
    explicitly running in single-user fallback mode, so the result is treated
    as identified even though no acoustic verification score exists.
    """

    def __init__(self, trusted_user_id: str | None = None) -> None:
        self.trusted_user_id = trusted_user_id

    def identify(self, audio_path: Path) -> SpeakerResult:
        if self.trusted_user_id:
            return SpeakerResult(
                user_id=self.trusted_user_id,
                score=None,
                status="identified",
            )
        return SpeakerResult(user_id=None, score=None, status="unknown")
