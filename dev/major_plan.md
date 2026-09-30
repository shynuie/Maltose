# MyAgent Major Development Plan

> 這是全專案層級的 roadmap。各 feature 的詳細需求、架構、測試與進度，請以 `dev/features/` 下的 feature plan 為準。

## 文件狀態

- 狀態：`in_progress`
- 最後更新：2026-09-29
- 詳細文件規則：[dev/README.md](README.md)

## 專案方向

MyAgent 是一個以語音互動為主的個人 Agent，核心開發方向如下：

1. 穩定的 voice loop：wake、STT、speaker identity、interruptible TTS 與 session lifecycle。
2. 可驗證的 TaskBrain：工具呼叫、Memory、個人資料與任務流程保持清楚邊界。
3. Document Knowledge Base：以原始文件為 source of truth，提供可追蹤、可修復的文件檢索能力。
4. 可觀測與可恢復的 background services：長時間運作時能看見狀態，重啟後不遺失重要工作。

## Feature Roadmap

| Feature | 狀態 | 詳細計畫 | 下一個主要里程碑 |
| --- | --- | --- | --- |
| Document Knowledge Base | `in_progress` | [kdb_dev_plan.md](features/kdb_dev_plan.md) | stale job policy、worker concurrency、service boundary |
| Voice interaction loop | `in_progress` | [voice_dev_plan.md](features/voice_dev_plan.md) | TTS audio render/play pipeline |
| KWS sensitivity and audio front-end | `in_progress` | [kws_dev_plan.md](features/kws_dev_plan.md) | dataset、offline replay、AGC/NS evaluation |
| TaskBrain / Memory | `in_progress` | 待建立獨立 feature plan | 整理 Memory、tools 與 session 的長期邊界 |
| Web UI / Agent Runtime | `in_progress` | [web_ui_dev_plan.md](features/web_ui_dev_plan.md) | runtime events、local Web UI、统一输入边界 |

## 目前優先級

### P0：可靠性與可恢復性

- KDB durable queue 的 stale job policy。
- indexing worker 的並行度與資源限制。
- 長時間 watcher runtime 的 shutdown、錯誤與狀態監控。
- TTS 句子間音訊預先產生與連續播放，降低 process handoff gap。

### P1：功能完整度

- KDB batch embedding。
- 更完整的 repair / consistency checks。
- Memory 與 KDB 的跨功能使用規則。

### P2：架構演進

- 評估是否將 KDB watcher/indexer 拆成獨立 background service。
- 建立統一的 runtime health/status interface。
- 必要時產生 HTML 文件網站；不改變 Markdown source of truth。

## 開發流程

1. 先在對應 feature plan 定義目標、邊界與驗收條件。
2. 需要架構決策時先建立 ADR。
3. 實作與測試同步進行。
4. 完成後更新 feature plan 與本文件的摘要狀態。
5. 重大階段完成後再建立 progress entry 或 commit。
