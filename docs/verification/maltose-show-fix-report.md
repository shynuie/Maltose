# `maltose_show` 建立畫布失敗修復報告

## 結果

MyAgent 第一次呼叫 `maltose_show` 時，UI Host 以 `forbidden / Surface unavailable` 回應 `surface.get`。Host 有意對「不存在」與「其他 Agent 擁有」使用相同回應；runtime 卻只把 `unavailable` 當作尚未建立，於是把錯誤拋回 TaskBrain，終止語音串流。

runtime 現在會在 `forbidden` 或 `unavailable` 後嘗試建立。Host 仍檢查 surface ID 與所有權：空 ID 會建立，外部 Agent 已使用的 ID 會被拒絕且不會被覆寫。MyAgent bridge 也會將 UI 工具例外轉成模型可處理的錯誤結果，不再讓 UI 連線問題關閉 Agent。

## 實際驗證

- runtime regression：**3 通過**。驗證首次建立、以現有 revision 更新，以及外部同名畫布不覆寫。
- MyAgent Maltose integration：**9 通過**。驗證工具例外回傳安全錯誤結果。
- `scripts/package.sh`：完成，產出更新後簽章 toolkit 與本機 app，codesign 驗證成功。
- 已重啟本機 Maltose UI Host，新程序視窗恢復、listener 啟動。

尚未重跑真人麥克風與正式模型的端到端流程。請在目前已更新的 UI Host 開啟後，再執行 `./start --maltose` 重試；第一次成功產生畫布後即可看見互動畫面。

## 後續診斷更新

使用者回報再次失敗後，確認 UI 畫面顯示 `agent.myagent` 已連線，但工作區仍無畫布。當時 bridge 將所有工具例外折成相同通用文字，因此單憑畫面無法判斷是 MUP 文件驗證、surface 衝突或連線錯誤。現在 Host 回覆含有 MUP 錯誤碼時，工具結果會附上有限長度的 code/reason，並記錄工具名稱、錯誤碼與例外種類；未知傳輸例外仍不輸出其文字或請求內容。

MyAgent Maltose 整合回歸 **10 通過**，包含 MUP 錯誤細節可見與一般傳輸細節仍隱藏。現有 MyAgent 程序需重新啟動才會載入這項診斷變更；下一次失敗會直接指出 Host 的實際拒絕原因。尚未把渲染成功列為端到端驗收完成。

使用者隨後提供的 `ConnectionResetError` traceback 來自 MyAgent 原有 `myagent.web.server`。`./start` 會一併啟動這個 HTTP UI；用戶端中途關閉連線時，標準 `ThreadingHTTPServer` 預設輸出 traceback。已讓 reset/abort/broken-pipe 僅記錄 debug，未改變 Maltose WebSocket 路徑。Web server 與 Maltose 整合測試共 **15 通過**（需本機 loopback 權限）。這只處理無害的 HTTP 斷線訊息；畫布是否能成功建立仍待下一次重啟後以 MUP 錯誤碼驗證。
