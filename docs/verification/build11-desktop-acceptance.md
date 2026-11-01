# Build 11 桌面與正式啟動驗收

日期：2026-11-01。版本：0.7.0／build 11。狀態：進行中。

## 當前證據

- 全開關完整 Swift 回歸：141 項、0 failures、0 skip，191.471 秒，於本機時間 13:11:42 完成。包含真實 Main／Codex 模型、共用面板動態工具、原生 AppKit 全螢幕，以及內容與多選跨窗口移動。目前 WindowServer 回報兩個實體顯示器；跨螢幕案例有第二窗口可用。日誌為 `/tmp/maltose-lifetime-unlocked-full-swift.log`。
- 正式 App 啟動前核對停寫備份：3,407 個資料／對話／協作／設定檔的 SHA-256 全部相符；備份留在私有 cache，沒有模型或執行環境。
- 透過 Finder 開啟新實體根目錄 `dist/Maltose.app`，核對實際 executable 為該封裝的 `Contents/MacOS/MaltoseApp`。未使用 UI-only、替代模型或文字限定模式。
- 原窗口與面板先顯示「主 Agent 啟動中」，之後更新為「主 Agent 已就緒」。正式 runtime 日誌確認原 KDB watcher、說話者後端、既有 STT warmup 及音訊啟動；觀察到 `active=True streams=1`。
- 從原輸入欄送出僅要求就緒回覆的文字，畫面確實顯示模型回答「Maltose 已就緒」。原生聊天面板放大後保留同一對話與回覆。

## 尚未完成

真人喚醒／聽感、裝置與身分／中斷矩陣、正常退出與再次啟動、原生 App 全體崩潰及正式 UI 中的完整開發任務驗收仍需逐項補證。已請人員進行真人語音；保留 App 開啟等待。既有無 UI 宿主故障與隔離模型測試不能替代以上正式流程。

桌面 App 的本機專案仍使用舊名稱與路徑。目的工具沒有修改路徑能力，電腦操作工具又明確禁止控制目前的 ChatGPT／Codex App，因此請人員手動重新定位；不修改其私有資料庫或繞過此限制。舊相容別名暫留。

整體 M0–M7 目標仍在進行中。套件靜態稽核與後續正式 App 啟動是不同階段，靜態 verifier 本身沒有啟動 Agent 或麥克風。機器可讀結果見 [build 11 結果](lifetime-build11-results.json)。
