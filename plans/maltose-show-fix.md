# Maltose `maltose_show` 建立失敗修正

## 計畫與狀態

- [x] 對照 Host 權限回應與 runtime 的 create-or-render 流程，找出首個畫布被拒絕的原因。
- [x] 讓不存在的畫布可在 Host 的隱私保護回應後建立；保持同名外部畫布不可覆寫。
- [x] 讓 MyAgent 的 UI 工具錯誤回到模型，避免工具例外停止語音 Agent。
- [x] 更新簽章 toolkit、重新封裝並重啟本機 UI Host。
- [x] 執行針對性 runtime 與 MyAgent 整合回歸。
- [x] 對 MUP 工具失敗回報安全錯誤碼與 Host 說明，方便定位後續拒絕原因。
- [x] 區分 MyAgent Web UI 的 HTTP 用戶端斷線 traceback，避免它和 Maltose 渲染錯誤混淆。
- [ ] 由使用者重試實際麥克風與模型流程，確認原生工作區出現互動畫面。

## 原因

Host 對不存在或不屬於呼叫 Agent 的 surface 都回 `forbidden / Surface unavailable`，以免洩漏其他 Agent 的 surface 是否存在。runtime 原本只在錯誤碼 `unavailable` 時建立畫布，因此第一個 `maltose_show` 直接失敗。MyAgent 的工具執行器會把未處理的 handler 例外傳回語音串流，造成整個 Agent 結束。

## 修正

runtime 在 `forbidden` 或 `unavailable` 時嘗試 `surface.create`；Host 的唯一 ID 與 owner 檢查仍負責拒絕同名碰撞，所以不會讀取或覆寫別的 Agent 的 surface。自己的 surface 仍以當前 revision 呼叫 `ui.render`。MyAgent bridge 將 UI 操作例外轉成工具結果。MUP 回覆含有錯誤碼時，結果附上有限長度的 code/reason；未知傳輸例外不回傳內部細節。

## 驗證

- runtime regression：3 項通過，涵蓋首次建立、既有 surface 更新、外部同名 surface 不覆寫。
- MyAgent Maltose 整合：10 項通過，含 MUP 診斷資訊可見、一般傳輸細節仍隱藏。
- `scripts/package.sh` 完成，更新 toolkit 簽章並成功建置、簽署 app。
- 使用者的 UI Host 已退出並從新封裝重新開啟；主視窗恢復且 listener 啟動。

真人麥克風、正式模型回合與實際配對後畫面尚待重啟 MyAgent 後重試，這次沒有宣稱已通過端到端語音驗收。

MyAgent 的 HTTP traceback 來源是 `./start` 同時啟用的 `myagent.web.server`。用戶端在送完 TCP 連線後取消請求時，Python 標準 server 會預設印出 traceback；這和 Maltose WebSocket 命令是兩條連線。已將 reset/abort/broken-pipe 降為 debug 記錄，其他 server 例外仍維持 traceback。Web UI + Maltose 共 15 項測試通過。本修正只清除斷線噪音，不代表畫布已渲染成功。
