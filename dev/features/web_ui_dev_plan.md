# Web UI Development Plan

> 狀態：`in_progress`
> 最後更新：2026-09-30

## 目標

為 MyAgent 提供一個本地 Web UI，讓使用者能：

- 看見 Agent 的即時狀態與對話內容。
- 透過文字輸入送出指令，與語音入口共用 Agent session。
- 接收 Markdown、程式碼、表格、進度與後續可擴充的 UI 事件。

UI 是 Agent Runtime 的觀察與互動層，不直接耦合 TaskBrain、Voice 或 KDB 的內部實作。

## 邊界

第一階段聚焦於單機、本地、單使用者場景：

- 使用標準庫 HTTP server，避免先引入前端框架與額外部署負擔。
- 使用 SSE 推送 Agent 事件；使用 HTTP POST 接收 Web UI 輸入。
- 不在本階段處理遠端登入、多人 session、TLS 或完整插件市場。
- 不改動 KWS 的偵測與音訊演算法。

## 設計

```text
Web / Voice / CLI input
          │
          ▼
     Agent Runtime
          │
          ▼
  typed events / state
          │
          ▼
       Web UI
```

事件至少包含 `type`、`timestamp` 與可序列化 payload。第一批事件類型：

- `state_changed`
- `user_message`
- `assistant_message`
- `error`

## 里程碑與驗收

### M1：Runtime 事件骨架

- [x] 建立 thread-safe event hub 與事件資料模型。
- [x] 為 state、user input、assistant output 定義事件 payload 介面。
- [x] 事件測試涵蓋訂閱、取消訂閱與慢速 subscriber。

驗證：4 個 focused unit tests 通過、`git diff --check` 通過。

### M2：本地 Web server

- [x] 提供靜態首頁。
- [x] `GET /api/events` 使用 SSE 推送事件。
- [x] `POST /api/input` 接收文字指令並交給 runtime。
- [x] `GET /api/state` 回傳目前狀態。

驗證：3 個 HTTP integration tests 通過，不啟動真實 microphone 或模型。

### M3：Agent 整合

- [x] Web input 與 voice input 進入同一個 session boundary。
- [x] 保留現有 VoiceAgent 行為與測試。
- [x] CLI 增加可選 Web UI 啟動參數。

驗證：25 個 focused regression/integration tests 通過；原有完整 `test_agent.py` 仍有 5 個與本變更無關的既有 optional dependency/TaskBrain failures。

### M4：可呈現內容

- [x] Streaming reply 以 `assistant_start`、`assistant_delta`、`assistant_end` 事件增量呈現。
- [ ] Markdown、code block、table 維持安全的前端渲染。
- [ ] 增加 progress 與 confirmation event schema。
- [ ] 補充 ADR，固定 runtime 與 UI 的責任邊界。

## 目前進度

- [x] 從 `kws` 的已提交 HEAD 建立獨立 `web-ui` branch/worktree。
- [x] 建立本 feature plan。
- [x] 實作 M1。
- [x] 實作 M2 的本地 Web server 與最小 UI。
- [x] 實作 M3 的 text command queue、Agent event publishing 與 CLI wiring。
- [x] 實作 streaming SSE delta 與前端即時追加文字。

## 下一步

將 Web input 接入 Agent Runtime，先定義統一的 text command queue，再讓 VoiceAgent 和 Web UI 共用 session 與狀態事件。
