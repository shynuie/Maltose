# Maltose 正式資料與執行環境切換

日期：2026-11-01。狀態：資料與環境已切換；整體產品整合仍為 in_progress。

## 切換結果

日常執行資料位於 `~/Library/Application Support/Maltose/`。原始文件、模型、錄音、Memory、Knowledge、聲紋與任務資料已複製到新位置；原 MyAgent 專案保留，不再被新 App 當作執行來源。正式設定的相對／絕對路徑已轉換，Memory 與 KDB 仍分離。

先以 M0 保全副本完成隔離演練，再核對 writer、備份並停用 `com.myagent.kws-monitor` 舊診斷排程。該工作退出是非同步的，已另外以 job lookup 與 lsof 確認服務及資料寫入者消失；沒有停止使用者的 terminal、編輯器或其他獨立程序。

正式切換 ID：`6c1f4dd2503c4506884185043dbcc006`。私有收據與停寫備份位於：

- `~/Library/Application Support/Maltose/migrations/agent-import-v1.json`
- `~/Library/Application Support/Maltose/migrations/6c1f4dd2503c4506884185043dbcc006/backup/`
- 舊排程 plist、先前狀態與還原命令：專案忽略目錄 `.cache/unification/cutover-20261101/`

備份與收據不進 Git 或 App 包。設定最後才發布，且整個遷移持有 native runtime 相同的 kernel lease。中斷可續跑；準備期間來源變動、未知目的地資料、文件 symlink 擴張及不支援的設定會停止，不會覆寫或以空資料取代。再次執行完成的遷移不會重設使用者後續編輯。

## 逐筆驗證

演練與正式切換均通過：

| 資產 | 證據 |
| --- | --- |
| SQLite | 4 個資料庫、43 筆記錄逐欄比較；除宣告的文件路徑外保持一致，integrity_check 通過 |
| Memory／Knowledge LanceDB | 4 張表、221 筆記錄與 schema 保持一致，沒有重新建立空表 |
| 原始文件 | 4 份文件 hash 與索引相符，SourceReader 能從新文件根讀取原文；沒有用摘要取代文件 |
| 知識路徑 | 4 筆 metadata 文件路徑、3 筆 queue 路徑已更新，文件 ID、其他內容與狀態保留 |
| 設定與憑證 | 原模型及語音參數保留；兩個既有服務憑證以資料解析並複製為 mode 600，未輸出值 |
| 模型 | 既有模型保留；外部 cache 的模型檔案連結已實體化，新 App 不必經過舊專案找模型 |
| 定位 helper | 新位置可執行、簽章通過，顯示名稱為 Maltose；保留既有 bundle identifier 與前一版備份，未發出定位請求 |

驗證工具：`runtime/dev/tools/verify_agent_migration.py`，只輸出統計，不輸出使用者內容、姓名或聲紋資料。日誌：`/tmp/maltose-migration-rehearsal-verification.log`、`/tmp/maltose-migration-cutover-verification.log`。

## 執行環境與實際 App

- App 專用主 Python 3.12.10、KWS Python 3.10.19 已依既有 lock／hash 重新建立；主環境載入 App 包內程式，沒有 editable checkout 或搬動舊 venv。離線 cache 安裝通過。
- 使用已遷移的隔離資料、真實 Qwen embedding 與原 TaskBrain 設定，通過 initialize／ready／shutdown，沒有送出模型提示或使用麥克風。KWS 的既有模型通過 READY、health、PCM、reset。
- 以 sandbox 明確禁止讀取 `/Users/Marvin/Workspace/MyAgent` 後，隔離 runtime 仍可冷啟動並正常退出；先確認對舊設定的實際讀取被拒絕。沒有為這項驗證搬走使用者仍開啟的舊專案。
- 已從 Finder 雙擊 `Maltose.app`，主 Agent 自動就緒，使用既有 `gpt-5.6-luna` 與 `https://api.openai.com/v1/chat/completions`。實際 UI／journal 已觀察到真人語音、模型串流回答及原生面板操作；不是 Echo 或腳本模型結果。
- 開啟、退出與再次開啟已驗證；退出後曾逐一檢查 App 與受管理程序均已消失。最新版本另外記錄實際音訊 stream 開啟／關閉，正常退出會先送完收尾事件。
- 舊 `Maltose UI Host.app` 與 `Maltose Workspace Preview.app` 已移至忽略的 `.cache/unification/legacy-application-bundles-20261101/`，保留還原資料；`dist/` 僅保留現行 App。

來源參考：[既有模型功能](https://developers.openai.com/api/docs/models/gpt-5.6-luna)、[Chat Completions 串流事件](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)。維持原本 API／模型，不因整合改換方案。

## 實際發現並修正的問題

一輪對話後曾在 KWS reset 發生 20 秒逾時；worker 日誌顯示 reset 已完成，之後更嚴格的 frame 檢查捕捉到非協定輸出。原生 SDK 的 stdout 會破壞管線，Python 層的 stdout 指派不足以隔離 C/C++ 輸出。

修正為預留獨立協定 descriptor，將 fd 1 的診斷轉至 stderr；App 主 runtime 也使用相同隔離。KWS 使用無緩衝管線、完整 write/read 交易鎖及涵蓋 header／payload 的整體 deadline。加入 native stdout 噪音、合併 frame、部分 payload、跨執行緒 PCM／reset／health 與退出收尾事件測試。修正後的實際語音多輪對話與面板操作已能回到喚醒待機，未再觀察到同一協定錯誤。

另修正真實聊天仍顯示「示意內容」的標籤。原生模式不應宣告未渲染的舊 Web presentation tools，已在原始碼與測試分開 Web／native 工具集合；此最後一項需隨下一次 App 更新／重啟套用。

## 回歸與未完成事項

- Python 完整套件：330 項，0 failures／errors、5 Docker integration skipped。日誌：`/tmp/maltose-m4-final-python.log`。
- Swift 真實桌面：69 項全數通過、無 skip。日誌：`/tmp/maltose-m4-full-swift.log`。
- 最新已驗證發行包：`/tmp/maltose-m4-transport-package.log`，strict ad-hoc codesign 通過。最新 Python 工具宣告調整仍需下一次封裝。
- Docker daemon 尚未啟動，容器整合仍待驗證。真實語音的逐項身分／中斷／裝置切換驗收還需 M7 測試矩陣，不能由一般多輪對話推定全部通過。
- 專案根目錄仍為 `Maltose_UI`；最終更名、專案附件／工具工作目錄重新定位與更名後回歸尚未完成。Codex app-server、持久任務與 @codex 交接仍待完成。

## 回復原則

先退出新 App 並核對實際程序／writer，再保全新位置切換後的新增資料。原 MyAgent 專案仍完整保留，可恢復原啟動流程；舊排程是否重啟依私有收據的先前狀態處理。不要讓新舊 Agent 同時寫同一資料，也不要把備份直接覆蓋已產生新記錄的目的地。
