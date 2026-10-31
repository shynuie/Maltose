from __future__ import annotations

import argparse
from collections import deque
import logging
import os
import sys
from pathlib import Path

from myagent.kws_protocol import ERROR, HEALTH, PCM, READY, RESET, RESPONSE, SHUTDOWN, json_bytes, read_message, write_message


logger = logging.getLogger("myagent.alibaba_kws_worker")


class TailLineFileHandler(logging.Handler):
    """Keep a bounded diagnostic log without rotating by approximate bytes."""

    def __init__(self, path: Path, max_lines: int = 3000) -> None:
        super().__init__()
        self.path = path
        self.max_lines = max_lines
        self._pending: list[str] = []
        self._line_count = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.path.open("r", encoding="utf-8", errors="replace") as stream:
                self._line_count = sum(1 for _ in stream)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._pending.append(self.format(record))
            if len(self._pending) >= 25 or record.levelno >= logging.ERROR:
                self.flush()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        if not self._pending:
            return
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(self._pending) + "\n")
        self._line_count += len(self._pending)
        self._pending.clear()
        if self._line_count <= self.max_lines:
            return
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            lines = deque(stream, maxlen=self.max_lines)
        with self.path.open("w", encoding="utf-8") as stream:
            stream.writelines(lines)
        self._line_count = len(lines)

    def close(self) -> None:
        self.flush()
        super().close()


def _configure_logging() -> None:
    log_path = Path(os.environ.get("MYAGENT_KWS_LOG", "data/logs/kws.log"))
    handler = TailLineFileHandler(log_path, max_lines=3000)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("worker_logging_started path=%s max_lines=3000 pid=%d", log_path, os.getpid())


class AlibabaKWSRuntime:
    def __init__(self, model_dir: Path) -> None:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks

        self.model_dir = model_dir
        self.pipeline = pipeline(Tasks.keyword_spotting, model=str(model_dir))
        self.model = self.pipeline.model
        self.sample_rate = 16000
        self._mono_buffer = bytearray()
        self._samples_per_block = self.model.size_in // (3 * 2)

    def process(self, pcm: bytes) -> dict:
        import numpy

        buffered_before = len(self._mono_buffer)
        self._mono_buffer.extend(pcm)
        hits = []
        blocks_processed = 0
        block_bytes = self._samples_per_block * 2
        while len(self._mono_buffer) >= block_bytes:
            mono = numpy.frombuffer(bytes(self._mono_buffer[:block_bytes]), dtype=numpy.int16)
            del self._mono_buffer[:block_bytes]
            blocks_processed += 1
            frames = numpy.stack((mono, mono, numpy.zeros_like(mono)), axis=1)
            result = self.model.forward_decode(frames.tobytes())
            if "kws" in result:
                hits.append(result["kws"])
        result = {"hit": hits[0] if hits else None, "blocks": blocks_processed}
        input_samples = numpy.frombuffer(pcm, dtype=numpy.int16)
        logger.info(
            "pcm_processed bytes=%d rms=%d peak=%d buffered_before=%d buffered_after=%d blocks=%d hit=%s",
            len(pcm),
            int(numpy.sqrt(numpy.mean(input_samples.astype(numpy.float64) ** 2))) if len(input_samples) else 0,
            int(numpy.max(numpy.abs(input_samples))) if len(input_samples) else 0,
            buffered_before,
            len(self._mono_buffer),
            blocks_processed,
            result["hit"] or "",
        )
        return result

    def reset(self) -> None:
        # SoundConnect exposes no reset API, but rebuilding only its state is
        # much cheaper than reloading the ModelScope/PyTorch model.
        import gc
        import os
        import py_sound_connect

        config_file = os.path.join(self.model.tmp_dir.name, self.model.SC_CONFIG)
        state_before = self.model._sc.kwsState() if self.model._sc is not None else None
        logger.info(
            "reset_started buffered_bytes=%d kws_state_before=%s",
            len(self._mono_buffer),
            state_before,
        )
        old_sc = self.model._sc
        self.model._sc = None
        del old_sc
        gc.collect()
        self.model._sc = py_sound_connect.SoundConnect(config_file)
        self._mono_buffer.clear()
        logger.info("reset_completed kws_state_after=%s", self.model._sc.kwsState())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    _configure_logging()
    try:
        runtime = AlibabaKWSRuntime(args.model_dir)
        logger.info(
            "worker_ready model_dir=%s sample_rate=%d samples_per_block=%d",
            args.model_dir,
            runtime.sample_rate,
            runtime._samples_per_block,
        )
        write_message(sys.stdout.buffer, READY, json_bytes({"model_dir": str(args.model_dir), "sample_rate": 16000}))
        while True:
            message = read_message(sys.stdin.buffer)
            if message is None:
                break
            kind, payload = message
            if kind == PCM:
                write_message(sys.stdout.buffer, RESPONSE, json_bytes(runtime.process(payload)))
            elif kind == RESET:
                runtime.reset()
                write_message(sys.stdout.buffer, RESPONSE, json_bytes({"reset": True}))
            elif kind == HEALTH:
                state = runtime.model._sc.kwsState()
                logger.info("health_requested kws_state=%s buffered_bytes=%d", state, len(runtime._mono_buffer))
                write_message(
                    sys.stdout.buffer,
                    RESPONSE,
                    json_bytes({"healthy": True, "kws_state": state, "buffered_bytes": len(runtime._mono_buffer)}),
                )
            elif kind == SHUTDOWN:
                logger.info("shutdown_requested")
                break
            else:
                write_message(sys.stdout.buffer, ERROR, json_bytes({"error": f"unknown message kind {kind}"}))
    except Exception as exc:
        logger.exception("worker_failed")
        try:
            write_message(sys.stdout.buffer, ERROR, json_bytes({"error": str(exc)}))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
