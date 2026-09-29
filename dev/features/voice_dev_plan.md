# Voice Interaction Development Plan

> 本文件追蹤 VoiceAgent、TTS、STT、wake、interrupt 與語音互動 lifecycle 的開發。

## 文件狀態

- 狀態：`in_progress`
- 目前階段：Phase 1 - TTS Playback Pipeline
- 最後更新：2026-09-29

## 目標

讓語音互動在保持低延遲的同時，降低串流回答中句子與句子之間的停頓，並維持：

- 可中斷 TTS。
- LLM 串流與 TTS 並行。
- 原有「等等」回到 listening 的行為。
- Agent session 與 standby lifecycle。

## 目前問題

LLM 很早就產生後續句子，但目前每個句子都會重新建立 TTS thread 與 macOS `say` process：

```text
sentence N 播放完成
→ 結束 say process
→ 建立下一個 TTS thread
→ 啟動新的 say process
→ 播放 sentence N+1
```

這造成句子切換時的 process startup gap。

## 目標架構

採用「預先產生音訊，再連續播放」：

```text
LLM stream
    ├── sentence queue
    └── TTS render worker
            ├── render sentence N+1 to audio buffer/file
            └── playback worker 播放 sentence N
```

核心原則：

- 播放中的句子與下一句的音訊準備可以並行。
- 播放端不應每句重新建立 `say` process。
- `stop()` 必須能中斷目前播放與取消尚未播放的音訊。
- 暫存音訊必須在播放或取消後清理。
- 不將完整回答寫入永久 recordings，除非使用者明確要求錄音。

## Phase 1 - TTS Audio Rendering Abstraction

狀態：`in_progress`

- [x] 抽出 render-to-audio 與 play-audio 的 provider interface。
- [x] 定義 audio buffer/file lifecycle 與 cleanup contract。
- [x] 保留既有 `TTSProvider.synthesize()` 相容路徑。
- [x] 定義 render/play/stop/error 的 log events。

## Phase 2 - Streaming Sentence Audio Pipeline

狀態：`in_progress`

- [x] sentence N 播放時背景 render sentence N+1。
- [x] 播放 queue 支援 backpressure，避免長回答無限制佔用磁碟或記憶體。
- [x] 支援 stream 結束、TTS error 與 LLM error 的基本清理流程。
- [ ] 支援「等等」中斷並完整清除尚未播放的 audio queue。

## Phase 3 - Runtime Validation

狀態：`planned`

- [x] 加入 sentence render/play timestamp logging。
- [ ] 測量相鄰句子的實際 gap。
- [ ] 驗證短句、長句、快速串流與長時間回答。
- [ ] 驗證 macOS `say` provider 與既有測試 fake TTS。
- [ ] 驗證不影響 standby timeout 與 conversation session。

## 非目標

- 暫不更換 STT、wake word 或 LLM provider。
- 暫不改變句子切分規則。
- 暫不將所有 TTS 改成永久背景服務。

## 驗收標準

- [ ] LLM 已產生下一句時，下一句音訊可在目前句子播放期間完成準備。
- [ ] 正常連續回答的句子間 gap 明顯低於目前 process-per-sentence 流程。
- [ ] 「等等」可停止目前播放，且不會播放取消前已排隊的句子。
- [ ] TTS error 不會讓 Agent runtime 卡死。
- [ ] 暫存 audio artifacts 在成功、取消、例外與 shutdown 後都會清理。
- [ ] 既有 VoiceAgent、interrupt、session 測試維持通過。

## 2026-09-29 Progress Update

- 狀態：`in_progress`
- 完成：
  - [x] 確認主要停頓發生在句子間 TTS process handoff，而非 LLM 產生速度。
  - [x] 選定「預先產生音訊，再連續播放」作為下一個實作方向。
  - [x] 建立 `TTSAudioRenderer`、`AudioPlayer` 與 `RenderedAudio` contract。
  - [x] 實作 macOS `say -o` renderer 與 `afplay` player。
  - [x] 驗證暫存 audio cleanup、playback stop 與非 macOS 錯誤行為。
  - [x] 接入 `_speak_stream()` 的背景 render / 順序 playback pipeline。
  - [x] 驗證 fake speaker 的 render-ahead、playback ordering 與 artifact cleanup。
  - [x] 加入 render/play monotonic timestamp logs。
  - [x] 加入 audio queue max size 與 render stop handling。
- 進行中：
  - [ ] 完善 interruption 時 renderer process 與 pending audio cleanup。
- 驗證：`uv run python -m unittest tests.test_tts tests.test_tts_pipeline tests.test_agent.VoiceAgentTest`
- 結果：24 tests passed。
- 阻塞：無。
- 下一步：測試「等等」發生在 render/play 不同階段時的 cleanup，並完成 macOS runtime gap measurement。

### Decision Note - Defer afplay Handoff Optimization

- 目前 render-ahead pipeline 已將主要停頓降低到約 48ms 的 `afplay` process handoff。
- 不再為現有 macOS `afplay` provider 加入更多尾端靜音或 process overlap workaround。
- 若未來更換 TTS provider，優先在新的 renderer/player adapter 中解決連續播放問題。
- 目前保留的待辦只限於 interruption cleanup 與實際 runtime validation。
