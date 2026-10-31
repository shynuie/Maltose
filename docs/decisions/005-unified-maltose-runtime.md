# ADR 005：單一 Maltose 產品與分開的執行程序

日期：2026-11-01。狀態：accepted；執行中。主計畫：[產品整合與 Codex](../../plans/maltose-unification-and-codex.md)。

Maltose 原生面板及原 MyAgent 主 Agent 合併成同一個倉庫與產品。原生 App 保有窗口與面板的既有模型；Python 保有 Agent、語音、身分、Memory、KDB 及工具邊界。App 管理子程序與生命週期，協調層管理訊息路由、任務和 @codex 交接；不由模型自行決定實際控制權。

來源歷史以不 squash 的雙親匯入提交 `c07b15a` 保存，兩個父提交為 `1195340` 與 `9632baf`；原始各分支保存在 `legacy-myagent/*` refs。原始碼的未提交修改另依私有 manifest 校驗後還原。來源工作樹未改動。完整備份與私有資料清單位於被忽略、權限受限的 `.cache/unification/baseline-20261101/`，不能加入 Git 或發行包。

套件與公開 CLI 為 `maltose`，舊持久身分、surface ID 等不因品牌改名任意替換。設定優先序為 CLI 明確路徑、新環境變數、舊環境變數、新設定檔、舊設定檔；設定內相對路徑跟隨設定檔位置。新舊設定檔不做隱式合併。新環境按原 lock 重建，主 Python 3.12 與 KWS Python 3.10 分離。

資料切換尚未進行。Memory 與 KDB 狀態分開、文件仍是 source of truth。正式資料遷移須停止相關 writer、備份與驗證，保留可重試的遷移紀錄；不能讓新舊 Agent 同時寫同一份資料。M0 備份校驗發現兩個既有 KWS monitor 日誌在持續附加，其餘 4820 個保全路徑與來源相符；這不構成正式資料切換或停機備份的證據。

原生 App 與受管理 runtime 的雙向傳輸優先採用標準輸入／輸出、NDJSON 訊息。這是計畫允許的本機 IPC 替代：無 listener、無公開 port，子程序連線的擁有者明確，也便於退出時偵測 EOF。未來需要獨立程序重新附著時，再增加受限 Unix socket，沿用相同版本化 request／event 合約。

Codex app-server 按需啟動，使用其正式認證和 thread 生命週期；MCP 僅供面板工具。@codex 接手同一個 task／thread／worktree，Maltose 暫停自主執行但保持觀察與資料同步；Codex 結束後先確認使用者意圖，再恢復自主工作。

回復方式：原專案及私有備份在完成驗收前保留；歷史 bundle、原生工作樹 archive、binary patch、來源完整副本及匯入 manifest 都有保存。任一資料遷移失敗時停止新 writer，按紀錄復原，不能以建立空資料庫掩蓋失敗。
