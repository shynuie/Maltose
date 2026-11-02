# 單一對話中的 Maltose／Codex 協調驗證

日期：2026-11-01。狀態：`in_progress`。範圍：[整合主計畫 M5／M6](../../plans/maltose-unification-and-codex.md)。本報告記錄來源實作及隔離驗證，不代表整個產品已交付。

## 本輪變更

- `AgentSessionCoordinator` 已接到原 App 的 composer、runtime 事件及既有聊天 journal。切換面板不改變收件人；前綴、後續訊息、來源、任務及控制狀態使用持久 conversation。新窗口沿用目前的收件人與狀態。
- `@codex` 先關閉主 Agent 新動作的准入，等待實際活動結束，再準備隔離工作目錄、建立／接回原 thread。追加需求沿用同一任務及 worktree；新任務及選取舊任務有明確入口。
- 原生輸入與語音路由共用 durable outbox。App 保存後才確認接收；重放不重套舊 `@mention`。未辨識語音、舊 epoch／其他 conversation 輸入及送達不明的訊息保留待確認；人工移至草稿／略過的處置不會把 uncertain 偽裝成 accepted。
- 主 Agent 新增有範圍的 `delegate_to_codex`。要求已驗證身分及已設定的 Git 專案，保存目標、限制、驗收與相關資料後才交接；工具不在目前回合內等待 App，避免自己阻止 drain。未確認的委派在 runtime 重啟時先保持 paused。
- 增加開發專案選取。只有原生人員控制入口可變更授權的 Git 根目錄；已選過的來源授權保留，原任務仍可檢查成果。模型工具不能任意呼叫這個 controller 方法。
- Codex 完成的單一回合先進 awaitingReview。只有明確的完成報告且沒有剩餘項目，才回收 baseline diff 並提出下一步問題；問題成功保存到聊天後才確認交付。使用者交回 Maltose 前不恢復自主派發，舊工作仍須重新檢查。
- 停止意圖持久化並經同一個序列協調流程處理。回合開始尚未回覆時按停止，會等結果可核對後中斷；尚未送出的追加需求轉為待確認。中斷不代表還原修改，也不等於產品任務完成。
- App 加入 Codex 登入、重試、專案／任務選取、待確認訊息、停止及交回入口。登入透過正式 app-server account API，僅開啟核對過的官方 HTTPS 登入頁，不讀取其他 App 的私有憑證。
- Codex 批准與問題使用原生人員控制，綁定原 connection／thread／turn／request。過期、重複及取消後的 callback 不能批准新請求。請求／回覆留存來源，秘密回答只在轉送給 Codex 時保留原值，產品 journal 遮蔽保存。
- 主 Agent 的舊批准入口也納入活動 gate，避免交接後的批准觸發 artifact promotion 或 knowledge 發布。交接時關閉舊批准視窗，恢復後仍需新的明確檢查。
- 不完整的 Codex 回覆也會同步給主 runtime；同步只提供有來源且標示截斷的資料與摘要，不變成 user／system 指令，不授予 Memory 或聲紋身分。完整產品紀錄保留在 task store。
- Codex 管理入口沿用獨立程序群組，修正 macOS 已建立群組時再次 setsid 的啟動失敗。正常停止及 server 先退出時會清理同群組的受管理子程序。

## 驗證

```sh
runtime/.venv/bin/python -m unittest discover -s runtime/tests -p test_native_collaboration.py
./scripts/swift-test.sh --filter 'AgentSessionCoordinatorTests|CodexAdapterTests|CodexTaskStoreTests|CodexInteractionTests'
runtime/.venv/bin/python -m unittest discover -s runtime/tests
MALTOSE_GUI_TESTS=1 MALTOSE_CODEX_TESTS=1 ./scripts/swift-test.sh
git diff --check
```

| 驗證 | 結果 |
| --- | --- |
| Python collaboration 聚焦 | 8 項通過，無跳過 |
| Swift 協調／adapter／store／人員控制聚焦 | 31 項，30 通過、1 項已安裝 Codex opt-in 測試依預設跳過；該項在完整桌面套件啟用並通過 |
| 完整 Python | 361 項，0 failures／errors，5 Docker integration skip |
| 完整 Swift 桌面及已安裝 Codex | 113 項，0 failures／errors，0 skip |
| 格式檢查 | `git diff --check` 通過 |

協調測試使用真正 native Python 子程序、Git fixture、隔離 worktree、journal 與可控制事件順序的假 Codex 程序。涵蓋直接交接、來源保全、多輪追加、完成早於 RPC 回覆、建立 thread 與綁定任務之間的 crash gap、整個程序／store 重啟後接回同一任務、停止與開始競態、UI 保存失敗及完成問題的持久交付。另驗證 schema 1 任務紀錄升級至 schema 2 不丟失原任務。

實際 Codex 0.155.1 測試仍使用隔離的 localhost fixture provider，證明程序及 thread 生命週期；**沒有以此宣稱正式帳號或真實模型已完成開發工作**。原生桌面測試實際涵蓋全螢幕、跨螢幕、面板／內容保存與既有 TaskBrain 呼叫面板。

最初並行回歸曾出現一次 owner EOF 退出逾時及桌面全螢幕／窗口時序失敗。聚焦重現均通過，其後完整 Python 通過，兩次完整桌面回歸（106 項及最終 113 項）通過；沒有放寬斷言或把失敗改成跳過，也不宣稱已修掉尚未穩定重現的時序問題。M7 仍需冷啟動與故障矩陣驗收。

本機原始記錄：`/tmp/maltose-collaboration-tests.log`、`/tmp/maltose-session-final-focused.log`、`/tmp/maltose-session-full-python.log`、`/tmp/maltose-session-final-desktop.log`。

## 尚未完成

- 尚未重新封裝／部署本輪來源；不能把既有 M4 發行包當成新協調流程已啟用的證據。
- 尚需驗證正式 Codex 認證與真實模型在 fixture 完成開發，以及既有主模型在交回後理解新增需求。主動確認目前由 Maltose 協調層產生固定問句，資料同步到既有主 Agent；不宣稱已有主模型審核成果的證據。
- Codex 面板工具 adapter／MCP 接入仍待完成。MCP elicitation 尚未提供完整表單流程；目前會明確回覆不支援，不自動同意。
- 需補多任務切換、所有批准／問題 UI 的桌面實際操作、真人語音交接及完整故障矩陣；目前的來源、fixture 與單元測試不能代替這些驗收。
- 根目錄更名、移除舊開發路徑依賴、最後封裝／Finder 啟動與 M7 完整交付仍待完成。Docker daemon 未連通，5 項容器測試仍未驗收。

Codex 合約以安裝版本 schema 及 [官方 app-server 文件](https://learn.chatgpt.com/docs/app-server) 核對。這輪維持本機整合，未加入外部帳號代管或商用託管服務。
