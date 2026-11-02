# Maltose Major Development Plan

> 這是全專案層級的 roadmap。各 feature 的詳細需求、架構、測試與進度，請以 `dev/features/` 下的 feature plan 為準。

## 文件狀態

- 狀態：`in_progress`
- 最後更新：2026-11-02
- 詳細文件規則：[dev/README.md](README.md)

## 專案方向

Maltose 是一個以語音互動為主的個人 Agent，核心開發方向如下：

1. 穩定的 voice loop：wake、STT、speaker identity、interruptible TTS 與 session lifecycle。
2. 可驗證的 TaskBrain：工具呼叫、Memory、個人資料與任務流程保持清楚邊界。
3. Document Knowledge Base：以原始文件為 source of truth，提供可追蹤、可修復的文件檢索能力。
4. 可觀測與可恢復的 background services：長時間運作時能看見狀態，重啟後不遺失重要工作。

現行產品整合見 [Maltose 產品整合](features/maltose_unification_dev_plan.md)，保留本頁既有語音、文件與隔離工作。

## Feature Roadmap

| Feature | 狀態 | 詳細計畫 | 下一個主要里程碑 |
| --- | --- | --- | --- |
| Document Knowledge Base | `in_progress` | [kdb_dev_plan.md](features/kdb_dev_plan.md) | stale job policy、worker concurrency、service boundary |
| Voice interaction loop | `in_progress` | [voice_dev_plan.md](features/voice_dev_plan.md) | TTS audio render/play pipeline |
| KWS sensitivity and audio front-end | `in_progress` | [kws_dev_plan.md](features/kws_dev_plan.md) | dataset、offline replay、AGC/NS evaluation |
| TaskBrain / Memory | `in_progress` | 待建立獨立 feature plan | 整理 Memory、tools 與 session 的長期邊界 |
| Task workflow / presentation | `in_progress` | [task_workflow_and_presentation_dev_plan.md](features/task_workflow_and_presentation_dev_plan.md) | build 21 已封裝：工作區恢復、固定形象／聊天、右下工作日誌與任務自動開板／捲動；完整原生 292 項通過，簽章／隔離啟動通過，真人試用與正式切換待辦 |
| Maltose App / main Agent / Codex | `in_progress` | [maltose_unification_dev_plan.md](features/maltose_unification_dev_plan.md) | 聊天捲動已部署 build 15；現行輸出層優化與真人語音、全螢幕、最終 App 驗收持續進行 |
| Legacy Host / MUP integration（歷史） | `done` | [maltose_ui_dev_plan.md](features/maltose_ui_dev_plan.md) | 保留舊方案與相容實測；現行 App 使用上列產品整合入口 |
| Web UI / Agent Runtime | `in_progress` | [web_ui_dev_plan.md](features/web_ui_dev_plan.md) | runtime events、local Web UI、统一输入边界 |
| Filesystem Sandbox | `done` | [filesystem_sandbox_dev_plan.md](features/filesystem_sandbox_dev_plan.md) | PathResolver、policy、approval、KDB bridge 與受控 file tools |
| Command Execution Sandbox | `in_progress` | [command_execution_sandbox_dev_plan.md](features/command_execution_sandbox_dev_plan.md) | restricted network backend、跨平台 hardening 與 package-install smoke test |
| Knowledge Curation | `done` | [knowledge_curation_dev_plan.md](features/knowledge_curation_dev_plan.md) | proposal、review、curated index 與 provenance |

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

### 2026-11-02 面板回執與已知無變更失敗接續（當前批次）

Main／Codex 既有面板操作新增獨立協商的 journal／私有接收 ACK，來源使用原要求／計畫與實際 dispatch execution 版本。舊面板可能已被修改而回覆遺失時先讀回，不盲目重做；已收到、確認沒有 UI 變更的失敗可沿原任務的有效 work continuation／新 Codex execution 繼續。真實 stdio 的 CSV 修復案例已完成原任務、不新增人員要求；模型在該案例受控。最後完整 Python 544 項通過；原生 265 案例中 264 通過、1 個全螢幕啟用案例失敗，同來源補驗通過。GUI／實際 Main／Codex／Docker 全啟用；不宣稱完整原生全綠。詳細範圍、未完成的一般未知副作用核對／其餘 P0–P5 與最後回歸見 [feature plan](features/task_workflow_and_presentation_dev_plan.md) 和 [直接資料](../../docs/verification/panel-operation-lifecycle-results.json)。正式 App 尚未替換。


### 2026-11-02 公開來源與半年資料自主呈現（當前批次）

Main 新增自有公開靜態原文讀取，完整表格可沿同一持久呈現規劃補出新圖，不使用搜尋片段冒充半年原資料。月份、方法差異及缺值保留；無產品任務問答也沿真實輸入提供來源，不建立假 owner。完成核對另以短證據引用與一次無工具的無效回覆修整減少內部格式錯誤卡住。最後完整 Python 560 項、原生 271 項全部通過，皆無 skip；GUI／實際 Main／Codex／Docker 啟用。一般模型過早 partial 與其餘工作流仍需後續驗收。範圍、來源及最後結果見 [feature plan](features/task_workflow_and_presentation_dev_plan.md)；正式 App 尚未替換，整體仍 in_progress。


### 2026-11-02 背景原成果跨獨立問答（當前批次）

已接真實 worker／attempt 的成果 metadata、真正 writer 守門與持久 ACK 後 followup。獨立答案送達後可回到原任務；鍵盤輸入仍 unknown，只取得該任務成果的窄範圍，不復活個人身分。較舊 body 晚到不重排原 outcome、不重做 worker，全部相關成果送達後才核對／綜整。修正後原生八項含實際主模型／舊 SIGKILL 與 Python 80 項聚焦通過；最後完整 Python 574 項通過，原生 277 案例中 276 通過、1 個研究收尾要求既有面板未修改的獨立證據。下一批先補精確原生操作邊界證據，不放寬完成條件。範圍／尚未完成的跨新 runtime、已生成 continuation 與其餘 P2–P5 見 [feature plan](features/task_workflow_and_presentation_dev_plan.md)。正式 App 未替換。


### 2026-11-02 舊面板負面要求的原生證據（當前批次）

主回答 prepare 封存原 input／runtime 的受控面板操作邊界，與結果面板實際交付分別核對；snapshot／版本不足不推定沒有操作。原研究收尾及反例通過，最後完整 Python 574／原生 280 項全部通過、無 skip（GUI／真正 Main／Codex／Docker 啟用）；詳見 [feature plan](features/task_workflow_and_presentation_dev_plan.md) 與 [直接摘要](../../docs/verification/panel-boundary-evidence-results.json)。原未完成工作流與正式 App 驗收保留。


### 2026-11-02 新 runtime 的未識別成果恢復（當前批次）

以獨立協商的原生 task-scope bootstrap 接回現有 worker／attempt 成果，不恢復舊 speaker、Memory 或人員輸入；pending body 與 generated continuation 的實際 SIGKILL／全新 store，以及真正 Main 在 unknown principal 下補讀均聚焦通過。最後完整回歸進行中；範圍／限制與下一步以 [feature plan](features/task_workflow_and_presentation_dev_plan.md)、[直接資料](../../docs/verification/cold-worker-scope-results.json) 為準。已生成成果跨插問、未知操作核對、其他呈現及真人／正式 App 驗收保留。

### 2026-11-02 依使用者要求先交付、收斂優化

本輪優先交付 build 18，採前一輪已完整回歸的產品程式；未完成的 cold scope／cold-ready 改動已可恢復地隔離。進階工作不再自動排入本輪，詳見 [目前範圍](features/task_workflow_and_presentation_dev_plan.md)。原正式版與上一份試用版保留。

已交付獨立試用 build 18；Release／簽章／包內來源、核心 Python 69／原生 28 與隔離 UI 啟動通過。正式 build 15 與試用 build 17 保留；[交付資料](../../docs/verification/task-presentation-build18-results.json)。
