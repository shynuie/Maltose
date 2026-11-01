# Codex 未登入與不可用的協調流程驗證

日期：2026-11-01。安裝版本：Codex CLI 0.155.1。狀態：核心驗證通過；正式 GUI 登入／交接仍待人員解鎖。

## 實際驗證範圍

沿用產品的 `AgentSessionCoordinator`、原生輸入路由、真正的 Echo runtime、持久 conversation/task store 及歷史紀錄。新增 fixture 的 Codex launch override，不修改既有 fixture 的預設行為。

未登入案例使用真正已安裝的 app-server 及現有 private runner／guardian。為子程序建立空白的臨時 `CODEX_HOME`，明確選擇 `cli_auth_credentials_store="file"`；僅繼承必要 OS 環境欄位，沒有繼承 API key、access token 或 workload identity 欄位。先透過 `account/read` 確認 `requiresOpenaiAuth=true`、`account=null`，才送入產品的開發要求；隔離未成立即停止測試。沒有執行登入或登出，也沒有複製使用者的認證資料。

上述設定及帳號回應的意義，已核對官方 [Credential storage](https://learn.chatgpt.com/docs/auth?surface=cli)、[app-server account/read](https://learn.chatgpt.com/docs/app-server) 與 [環境變數](https://learn.chatgpt.com/docs/config-file/environment-variables)。官方允許系統管理要求限制儲存方式；測試不繞過這些限制。

## 結果

| 情境 | 觀察結果 |
| --- | --- |
| 真實 CLI 未登入 | 呈現「尚未登入」，Maltose 維持 paused；收件人仍為 Codex，原輸入維持 queued；沒有 task、worktree 任務 ID 或完成問句 |
| 未登入時重試 | 再次呈現同一認證問題；輸入 ID 與聊天中的使用者訊息都只有一份；仍未建立開發任務；臨時 home 沒有 auth.json |
| Codex 執行檔不存在 | 錯誤可見，原需求保留且 Maltose 維持 paused；沒有 Codex 程序及 task |
| 不可用後明確輸入新的 @maltose 意圖 | Main 接納新意圖並恢復 active；舊 Codex 輸入改為 deferred，沒有被當作新指令重送；fixture 原檔保持 baseline |

程序停止後確認 Codex owned cleanup 已完成，再由既有 teardown 清理本次臨時目錄。未觸及正式 App、語音、模型設定或全域 Codex 設定。

檢查也發現未登入提示指向舊的「工作空間」選單，實際入口位於 `Codex → 登入 Codex…`。產品文字已更正為「請從『Codex』選單登入後重試」，沿用原本的選單與登入流程。

## 測試與封裝

- 兩項新流程首先通過，1.798 秒。第一次編譯因測試 closure 缺少顯式 self 而失敗，已修正；編譯失敗時沒有啟動 SDK 或送出要求。
- 完整 Swift 回歸：143 項、0 failures、15 GUI skip，152.646 秒，包含真實 Main／Codex 模型。日誌 `/tmp/maltose-auth-negative-full-swift.log`。
- 更正提示文字後，再跑兩項聚焦：2 項通過，1.612 秒。日誌 `/tmp/maltose-auth-negative-guidance-focused.log`。文字更正後未重複整套模型回歸；其餘產品邏輯沒有改動。
- Python runtime 與 build 13 逐檔相同，沿用已通過的 408 項 Python、七項 Docker 故障／恢復證據；本輪未重跑 Python。
- 試用包 0.7.0／build 14 獨立輸出至 `.cache/unification/releases/Maltose-0.7.0-14.app`。145 個 bundle／129 個 runtime 檔案來源相符，strict 簽章、受管理 Python 獨立 cwd 匯入及兩項已設定憑證值掃描通過。static verifier 沒有啟動 Agent／麥克風。

機器可讀結果見 [build 14 驗證](codex-auth-build14-results.json)。正式 dist 仍為 build 11，沒有覆蓋執行中的 bundle；build 13 的既有回復與驗證證據保留。

剩餘驗收：正式 build 14 Finder 冷啟動、退出／重啟、全 App 故障、UI 中的 Codex 工作閉環，真人語音／身分／裝置／中斷及人員問題矩陣，以及本機專案／聊天附件重新定位。以上仍依主計畫驗收，目標沒有完成。
