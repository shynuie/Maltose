# Maltose Native UI Integration

狀態：done。跨專案開發計畫來源：`/Users/Marvin/Workspace/Maltose_UI/plans/agent-integration.md`。

- [x] opt-in CLI/config 與獨立 uv sidecar，不改 ML/voice dependencies。
- [x] 將真實 model/tool/speech、回答串流與 task progress 經 EventHub 同步至原生 UI。
- [x] 原生文字輸入回既有 submit_text，同一 Agent/session 邊界。
- [x] 已驗證使用者每回合取得授權新鮮 context；沿用 speaker identity，不能以 UI agent token 冒充人類身分。
- [x] 動態工具登錄、拒絕/撤銷/離線降級、原有 Web/voice regression。
- [x] 實際驗證與已知限制回寫此檔。

## 2026-10-29 實測

- 8 個新增 Maltose 整合案例全數通過；涵蓋自動情境、說話者隔離、工具事件、原生輸入、CLI/TOML、模型／工具失敗與未知 action。
- 相關回歸 65 個案例，62 通過、原有 3 個失敗。完整回歸 274 個案例，266 通過、原有 3 個失敗、5 個 Docker 整合明確 skip。
- 原有失敗為 test_agent 的記憶工具／profile／task 身分假設；未修改 HEAD 在暫存目錄重現相同 2 failures + 1 error，沒有放寬說話者政策。
- UI 專案已跑真正 native Host → 簽章 wheel → uv sidecar → 本專案 TaskBrain 假模型，包含實際 ECharts 框選、原生輸入與 model/speech 事件；換埠重連與憑證撤銷亦通過。
- 全部回歸從暫存工作目錄執行，未使用正式 memory/documents/models/credentials。原有 command-execution 未提交變更保留。git diff --check 通過。

架構決策：[ADR 003](../decisions/ADR-003-maltose-native-ui.md)。完整 logs 與驗證限制集中於 `/Users/Marvin/Workspace/Maltose_UI/docs/verification/agent-integration-report.md`。

下一步：以 `./start --maltose` 做真人麥克風與實際模型驗收；第一次正式配對由使用者在原生 UI 核對並批准。未宣稱這些真人／服務路徑已驗證。其他 framework 可重用 bootstrap，但仍需接上該 framework 的 registry/runtime callbacks。

## 2026-10-29 實際啟動環境修復

正式啟動回報的 FileNotFoundError 發生於 MaltoseBridge 建立前：原 KWS interpreter 使用 /private/tmp 下已遺失的實驗環境。已修為持久 `.venvs/kws310`，原模型與主環境不變；真正模型 READY／health／PCM／reset 已驗證。相關回歸 38 通過，完整 MyAgent 281 中 273 通過、3 原有失敗、5 skipped。修復計畫與完整證據集中 UI 專案的 `plans/myagent-kws-startup-fix.md` 與 `docs/verification/kws-startup-fix-report.md`。


## 2026-10-29 Maltose surface 建立錯誤修復

Host 對不存在的 surface 回 `forbidden / Surface unavailable`，保護其他 Agent 的 surface 隱私；runtime 原先只在 `unavailable` 時走建立分支。現已在兩種回應後嘗試建立，並讓 Host 拒絕外部同名 ID、不覆寫任何既有 surface。MyAgent bridge 將 UI handler 例外轉成模型工具錯誤結果，避免重現時終止語音 Agent。Maltose 整合案例累計 9 通過；runtime 建立／更新／碰撞案例 3 通過。更新 app 已本機重啟；真人麥克風與正式模型驗收仍待使用者重試。詳細證據：`/Users/Marvin/Workspace/Maltose_UI/docs/verification/maltose-show-fix-report.md`。


## 2026-10-29 HTTP reset traceback

使用者回報的 `ConnectionResetError` 來自 `./start` 同時啟用的 MyAgent HTTP Web UI；用戶端取消/關閉請求時，Python `ThreadingHTTPServer` 預設會印 traceback，和 Maltose 動態 WebSocket 不是同一條連線。已將 reset/abort/broken-pipe 降為 debug 訊息。Web server 與 Maltose 整合測試共 15 通過。這只消除 HTTP 斷線噪音；畫布建立仍需下一次 Agent 重啟後依 MUP code/reason 確認。
