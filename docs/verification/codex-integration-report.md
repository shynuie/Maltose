# Codex 接入核心驗證

日期：2026-11-01。狀態：`in_progress`。範圍：[主計畫 M5](../../plans/maltose-unification-and-codex.md)。

## 已實作範圍

- `CodexConnection`：App 所擁有的私有 stdio 子程序、初始化握手、JSON-RPC request／notification／server request、串流順序、逾時、取消觀察、EOF／退出、子程序回收及重啟 generation。
- 批准與工具請求保留原連線及精確 request ID，數字與字串 ID 分開。相同請求去重、不同內容使用相同 ID 會中止連線。server resolution 及重啟會使過期人員回覆失效；傳輸層不自動批准。
- `CodexAdapter`：建立／恢復 thread、開始／steer／中斷回合、來源標記、訊息送達狀態、工具與文字結果保存。回合完成只標為 `awaitingReview`，不把產品任務標為完成，也不恢復 Maltose。
- `CodexTaskStore`：產品 task／原生 conversation／Codex thread／worktree／控制狀態對應。版本化 JSON、單一 writer lease、private mode 600、原子取代與同步、revision 衝突檢查；損壞時明確失敗，不重建空紀錄。逾時及斷線保留未確認操作，先讀回原任務，再允許新輸入。
- Python `CodexWorkspaceManager`：僅接受 controller 明確授權的精確 Git 根目錄；建立 detached worktree，保存原有 staged／unstaged／untracked 檔案的工作內容及刪除狀態。原專案的 HEAD、暫存區和工作檔案保持原狀，不為保全而建立使用者提交。
- 工作目錄的私有 baseline 以接手當下內容建立；結果逐檔比較 baseline，避免把使用者既有修改算成 Codex 新增的修改。保留 hash、binary 標記及有上限的文字 diff；來源在建立期間變動時保留 incomplete attempt，不覆寫或刪除。
- `.gitignore` 補上根目錄產生的 `data/logs/`，避免正式執行日誌被當成原始碼匯入或提交。

以上元件目前由測試呼叫，尚未連接 App 的收件人路由、主 Agent 委派工具或人員批准 UI，不能把這份報告當作整個 Codex 協作流程已可用。

## 協定依據與實際版本

本機 `codex-cli 0.155.1`。已透過該版本的 `app-server generate-json-schema` 核對使用到的欄位；產品不強制更換使用者設定的模型。Thread 使用 `workspace-write` 與 `on-request`，沒有啟用全面存取。

依據為 [官方 app-server 文件](https://learn.chatgpt.com/docs/app-server)。目前僅使用一般 API；未啟用 experimental dynamic tools。官方 [MCP 遷移說明](https://learn.chatgpt.com/docs/mcp-server) 指出原 Codex MCP server 已移除，且 app-server 仍有 experimental／production support 限制；本輪定位為本機試用整合，最終發行須重查支援狀態。

實測發現：空白 thread 在此版本尚無可恢復 rollout，不能只憑建立成功就宣稱可重啟恢復。未確認的建立操作保留供核對，不自動另建；恢復驗收使用已開始回合的 thread。中斷若遇到回合已結束／尚在註冊的競態，先讀回相同 thread／turn；只對已確認仍在進行的相同回合重試取消。舊儲存後端明確回覆 history method unsupported 時，改讀官方仍提供的完整 resume history；沒有歷史證據時維持待核對狀態。

## 驗證

```sh
MALTOSE_CODEX_TESTS=1 ./scripts/swift-test.sh --filter Codex
runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_codex_workspaces.py'
```

- Codex Swift 聚焦測試：21 項全數通過，無 skip。
- Workspace Python 聚焦測試：9 項全數通過，無 skip。
- 完整 Python：340 項，0 failures／errors，5 Docker integration skip。本機測試伺服器需執行環境提供 socket 權限；首次受限執行的 5 項 permission errors 與程式結果分開記錄。
- 完整 Swift：90 項，0 failures／errors，13 GUI skip。本輪未啟用 macOS GUI 測試，不把跳過項目當成通過；先前 M4 的 69 項桌面結果只作歷史證據。
- 已核對沒有遺留本輪 Codex fixture 子程序；未停止使用者正在使用的 App／runtime。
- `git diff --check` 無格式錯誤。

Swift 測試覆蓋握手順序、分段 UTF-8／JSON 訊框、並行回覆、null result、server request 去重／衝突／resolution、過期回覆、啟動逾時、觀察取消不冒稱已取消執行、子程序回收、持久紀錄權限／損壞／衝突、回合及產品狀態分離、跨程序核對、同一回合 steering、來源及送達狀態、重複工具結果 canonicalization、取消競態與舊歷史 API fallback。

另以丟失 start acknowledgement 的子程序驗證：必須在 history 找到相同 client message ID 才解除不確定、補上 turn 與送達狀態；找不到時維持待核對，不重送輸入。

Python 測試覆蓋 staged／unstaged／刪除／新增檔案保全、原 index／HEAD 不變、Git ignore 排除、相對 symlink、來源競態、baseline 完整性、路徑與 receipt 驗證、binary／有上限 diff，以及不執行 checkout filters／hooks。

完整回歸另重現既有排程測試的競態：schedule completed 代表單次排程已派發，不代表其背景 task 已產生結果。測試改以受控 worker 分別驗證兩個狀態並等待 task terminal，保留正式排程語意；相關 13 項 task 測試通過。Foundation 與 Python 的 UUID 大小寫差異亦有跨介面回歸，對應到同一工作目錄，不重建任務。

本機測試記錄：`/tmp/maltose-m5-final-codex-tests.log`、`/tmp/maltose-m5-final-workspace-tests.log`、`/tmp/maltose-m5-final-full-swift.log`、`/tmp/maltose-m5-final-full-python.log`。

## 真實程序與模型證據邊界

已實際啟動安裝的 Codex app-server，完成 `initialize → initialized → account/read → thread/start → turn/start → turn/interrupt → 程序退出 → 重啟 → thread/resume → thread/read`。Thread ID 和工作目錄相同，恢復的回合維持 interrupted。

這項測試使用空白臨時 `CODEX_HOME`、獨立 fixture 目錄、沒有認證需求的本機 fixture provider，且端點是刻意關閉的 localhost port。Plugins／apps 在此測試停用以避免背景下載。它證明實際 CLI 協定、中斷與恢復，**沒有證明真實模型成功開發**，也沒有讀取另一個客戶端的認證檔。傳輸及生命週期其餘測試使用腳本子程序。一般 App 的模型、帳號及 plugins 設定未因測試改動。

## 尚未完成與限制

- Native composer／語音輸入路由、`@codex` 收件人標記、主 Agent 的實際工具及排程暫停、同一聊天多輪交接、完成後主動確認意圖，仍屬 M6。
- 主 Agent 委派工具與工作目錄 controller 尚待接線；不能把這個內部 workspace service 直接暴露為不受限的模型檔案操作。
- Codex 人員批准／問題 UI、未登入時的支援登入流程、完成後 diff／測試成果呈現，以及 App 退出時的多程序協調尚未完成。
- 面板工具仍須接入同一原生能力核心；目前沒有另外建立 Codex 專用面板狀態。
- Workspace 僅包含 Git 列出的 tracked 及未忽略一般檔案；不搬用 ignored 環境／模型／憑證。Submodule、巢狀倉庫、特殊 tracked 檔案及絕對／越界 source symlink 會明確拒絕，需另行提供明確的依賴配置。
- 尚須在隔離 fixture 跑真實已認證模型的開發／測試流程，完成 M7 故障及 GUI 矩陣、最終根目錄更名、重新封裝與 Finder 驗收。此次新增來源尚未部署至正在使用的 `dist/Maltose.app`。
