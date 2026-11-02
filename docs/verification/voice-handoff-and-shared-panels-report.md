# 語音交回、訊息送達與 Codex 共用面板驗證

日期：2026-11-01（Asia/Shanghai）。來源基準 HEAD `28dded8` 加目前未提交修改；不是該提交本身已包含全部功能。新來源尚未重新封裝／部署到日常使用的 App，整體目標仍在進行。

## 本次改動

- 主 Agent 的 `submit_text` 回覆只代表入列，實際 `user_message` 才代表接納。交接競態造成的 runtime 轉交回覆保留原本的鍵盤來源，改為待確認，不把訊息轉送目前 Codex 任務，也不因入列回覆覆蓋待確認狀態。
- 聊天的使用者訊息、完整回答、完成問題及錯誤在確認保存前同步 journal；串流仍採批次事件序號預留。重啟後可跳過未用序號，不能重用已發出的序號。未確認接手的 durable delegation 會阻止恢復自主工作。
- 語音交回新增 runtime 內的單次驗證證據：綁定原始內容、runtime、說話者 scope 世代及 120 秒期限。App 只引用訊息與 runtime ID，不可自行送入 verified TurnContext。排隊後再驗證，過期或 scope 改變則保留待確認、不呼叫模型；同一人離開後再回來也不能復活舊證據。喚醒詞仍更新驗證 scope，但不成為開發指令。鍵盤輸入保持 unknown。
- 新 Codex thread 透過 experimental `dynamicTools` 註冊既有全部 36 個具名工具；`item/tool/call` 綁定 connection／task／thread／turn，轉交既有私有 native bridge，再使用相同 schema、FileService 及 MainActor 面板核心。沒有建立第二份面板狀態。
- 動態工具先保存 request，再執行，再保存 response。相同 call ID 及內容重用結果；衝突內容、未知工具、過期回合拒絕。已開始卻無結果的操作回報 `outcome_unknown`、不可盲目重送。結果不確定的失敗也會保存，不能因重複請求再執行一次。停止／交回會等待面板呼叫與 runtime controller 工作收尾。
- 私有 UI 讀取使用當次 runtime 已辨識的任務擁有者，或人員在「Codex → 允許 Codex 讀取面板內容…」明確給予的授權。授權只存在記憶體，綁定 task／runtime／paused lease，可撤回，交回或重啟失效；不改變 TaskBrain 的個人記憶身分、FileService 根目錄或寫入政策。
- 原生命令批准視窗補上 experimental `additionalPermissions` 的實際內容。既有秘密回答遮蔽及人員控制來源規則保留。

先前尚未寫入最新報告的模型選擇亦已核對：使用 app-server 分頁清單、自己的 preferredModel 設定及任務固定模型；不可用的明確選擇不會偷偷替換。曾觀察到全域預設模型不受此 CLI 帳號支援，修正只作用於 Maltose 的選擇，不修改全域 Codex 設定。

## 合約與真實服務證據

已查核 [官方 app-server 文件](https://learn.chatgpt.com/docs/app-server) 與本機 Codex 0.155.1 產生的 experimental JSON Schema。標準 schema 不含 `thread/start.dynamicTools`；experimental schema 為帶 `type=function`、name、description、inputSchema 的工具，回呼使用 `contentItems`／`success`。初始化明確啟用 experimentalApi，不能宣稱這是穩定發行介面。既有未註冊工具的 thread 保留原能力，不自動改寫。

兩種真實 Codex 驗證均使用既有官方 CLI 認證、隔離 fixture 與服務回報的可用模型；未輸出或複製憑證，沒有自動批准人員請求：

1. 實際模型修正 calculator 的加法錯誤並執行三項 unittest；宿主另行執行測試確認。來源 repository 保留原錯誤內容，工作發生在隔離 worktree；之後以新意圖交回 Maltose。
2. 實際模型呼叫 `maltose_create_panel` 與 `maltose_notes_set_text`，在真正原生工作區新增一個筆記面板並寫入隨機指定文字。兩筆工具結果成功保存及送達，workspace changes 為空。這不是要求模型在回覆中宣稱成功。

受控 Codex 程序另驗證 get_user_view、建立、寫入、read_panel、重複建立只執行一次、衝突內容與過期 turn 拒絕。使用真正 runtime、原生面板及 TaskBrain 委派；模型／說話者辨識結果在此案例受控，不能替代真人麥克風驗收。

## 測試結果

| 範圍 | 結果 |
| --- | --- |
| 完整 Python | 366 項，0 failures／errors，5 Docker integration skipped |
| 協作 Python 聚焦 | 13 項通過：包含真實 VoiceAgent／TaskBrain 的語音交回、unknown 鍵盤輸入、過期／偽造／重送／scope ABA 拒絕及共用面板權限 |
| Autonomy Python 聚焦 | 13 項通過，包含 wake-only scope 觀察及原活動 drain／worker 收尾 |
| 完整 Swift 桌面、本機 Codex、實際模型 | 124 項，無 skip；同一個全螢幕案例有 7 個失敗斷言，其餘案例通過，不能稱整套通過 |
| 真實模型開發／交回 | 完整回歸內通過；本輪已重複觀察到隔離修改、測試、來源不變及交回成立 |
| 真實模型操作原生面板 | 獨立聚焦及完整回歸內通過，實際兩次工具呼叫，原專案無修改 |
| 受控程序操作原生面板 | 聚焦及完整回歸內通過，包含重複／衝突／過期請求 |
| Adapter 不確定結果 | 聚焦及完整回歸內通過：呼叫一次，重複請求重用失敗，關閉／重開 task store 後紀錄一致 |
| 最終 Swift 協調／Adapter／互動聚焦 | 35 項，0 failures、無 skip，包含真實模型與原生面板；不包含仍失敗的全螢幕案例 |

完整 Python 第一次受沙盒禁止綁定 localhost 影響，5 項 fixture server 報錯；以可綁定本機端口的同一環境重跑後通過。5 個 Docker skip 另屬 daemon 未啟動，不能混稱已驗收。

本輪日誌位於 `/tmp/maltose-shared-panels-full-swift.log`、`/tmp/maltose-shared-panels-full-python.log`、`/tmp/maltose-shared-panels-final-focused.log` 及相關聚焦日誌。Codex fixture 的私有 task store／工作目錄保留於忽略的 `.cache/codex-live/`；不將私有 CLI rollout 或正式資料加入 Git。

## 全螢幕問題與限制

完整及聚焦測試均重現：UI-only 的真實 App 正在執行、窗口在 active Space，但 `NSApp.isActive=false`、`isKeyWindow=false`，原生全螢幕尚未成立。先前以已啟動的 App 取得通過的紀錄仍屬歷史證據，不代表目前已穩定。

現在等待實際啟用再切換，若系統保留其他 App 的焦點，就維持可使用的窗口，並在 didBecomeActive 後續做；不把尚未啟用直接記為永久失敗。快照會保留 awaiting-activation 與實際窗口狀態。換用系統 `open` 仍重現，因此撤回該無效實驗，保留 NSWorkspace 的隔離啟動方式。沒有移除 fullScreen styleMask、root 狀態或 opacity 斷言，也沒有把填滿螢幕視為原生全螢幕。

Apple 明確說明 [App 啟用是請求且不保證立即成功](https://developer.apple.com/documentation/macos-release-notes/appkit-release-notes-for-macos-14?language=objc)。目前證據尚不足以證明後續前景啟用與多螢幕 Space 的完整行為已修復；此項保留為 M7 未完成驗收。其餘三項 WorkspaceNative 測試在同次執行通過。

## 尚待完成

- 用正式主模型驗證交回後理解最新追加要求並主動確認；固定確認問句仍只是協調通知，不能冒充模型理解成果。
- 真人語音、身分切換、裝置切換、多任務、人員批准／登入、動態工具中斷／重啟及背景程序清理完整矩陣。
- 全螢幕啟用穩定性、Docker integration、最終根目錄／專案重新定位、新版封裝、Finder 冷啟動／重開／退出與發行包私有資料檢查。

正式目標維持進行中，不以本次新增能力或模擬測試縮小完成範圍。
