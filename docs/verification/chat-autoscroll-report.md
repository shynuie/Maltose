# 聊天自動追蹤與手動閱讀保護

日期：2026-11-01（Asia/Shanghai）。版本：0.7.0／build 15。此追加功能已實作並部署；完整 M0–M7 目標尚未完成。

## 行為與實作

- 沿用原聊天視圖，grid／focused／sidebar 收到使用者、Main、Codex 或系統訊息時追蹤底部，串流內容增長及最後內容替換也會追蹤。
- 手動捲離底部後保留閱讀位置 30 秒，從最後一次實際手動移動重新計時；手動回到底部立即恢復。逾時後在下一次訊息更新恢復，不用計時器在安靜時強行拉走畫面。
- 閱讀狀態由原聊天 model 按 session 保存，模式切換不清除，其他對話獨立計算。模式重建後嘗試還原近期閱讀位置。
- 原生 observer 只接聊天 transcript 的 scroll view，區分手動輸入／live-scroll 與單純 bounds／排版改變；不攔截事件，不把工作區、session 清單或 Ctrl 縮放當作聊天閱讀。取消掛載時移除觀察及本機事件監聽。
- 底部使用穩定標記，訊息 revision 包含同 ID 的串流更新；排版後再次核對手動保護，避免已排程的捲動蓋過新發生的手動意圖。

## 驗證

| 範圍 | 結果與限制 |
| --- | --- |
| 聚焦聊天回歸 | 10 項通過、無 skip／failure；包含 2 項政策、3 項實際 NSHostingView／NSScrollView 版面測試及 5 項既有聊天／journal 案例 |
| 三種模式 | 使用者訊息、開始／增長／完成的長回答可跟隨；live-scroll 通知與實際 clip 移動測試閱讀保護、模式重建、逾時及立即恢復 |
| 完整 Swift | 148 項、2 skip、1 個雙螢幕全螢幕案例有 4 個失敗斷言；其餘案例沒有失敗。真實 Main／Codex 流程已執行。此輪不能報成完整回歸通過 |
| 兩項 skip 補驗 | 初次未設定 MALTOSE_CODEX_TESTS；補開後真正未登入／握手／中斷／thread 恢復兩項通過，1.260 秒 |
| 全螢幕單獨重現 | 同案例仍失敗，7 個斷言，27.205 秒；包含等待 activation 及未進入 system Space。沒有因重跑而抹除首次失敗，尚未證明原因或修復 |
| Release | build 15 編譯 37.33 秒，145 個 bundle／129 個 Python runtime 檔案相符、strict 簽章、獨立匯入與兩個既有憑證值掃描通過 |
| 正式 App | 舊 App、Main、KWS、watcher 共 4 個自有程序正常退出；停寫／kernel lease 下 4,444 個資料／設定檔備份校驗相符。保留 build 11 回復包，正式切換 build 15 |
| 真實回答與畫面 | Finder 開啟後核對實際 dist executable，Main 自動就緒；原輸入送出測試要求，看到真實回答及末尾標記，自動移至底部 |
| 實際手勢限制 | CUA 在全螢幕／多螢幕的 scroll 操作回 windowNotFoundAtPosition，未成功送出實際 wheel。手動保護有政策與原生版面測試，但未將通知模擬宣稱為真人觸控板驗收 |

最初使用舊 `.build` 時，Swift compiler 因 Maltose_UI／Maltose 兩份 module-cache 路徑崩潰；改用實體根目錄的 `.build-relocated` 後編譯成功。新測試初次缺少 explicit self 的編譯錯誤已修正。備份首次遇到歷史 migrations/backup 的模型符號連結而中止，當時正式 App 尚未更換；重做現行資料備份，排除不會變更且仍原地保留的歷史備份／模型／環境後成功。以上不是正式資料遷移，也沒有重建依賴。

日誌：`/tmp/maltose-chat-autoscroll-focused-relocated.log`、`/tmp/maltose-chat-autoscroll-full-swift.log`、`/tmp/maltose-chat-autoscroll-installed-codex.log`、`/tmp/maltose-chat-autoscroll-fullscreen-focused.log`、`/tmp/maltose-chat-autoscroll-build15-package.log`。私有停寫備份、來源 manifest 與回復包依收據保留在忽略的 .cache/unification，沒有加入 Git／發行包。

Python 未修改，沒有為這個原生聊天變更重跑 408 項歷史回歸。下一步仍須修正／釐清原生雙螢幕全螢幕問題，補齊真人、完整協作 UI、App 故障與專案重新定位等主計畫驗收。
