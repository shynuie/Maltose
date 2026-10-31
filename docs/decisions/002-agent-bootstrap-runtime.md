# ADR 002：Agent 探索、配對、可信工具派送與雙向互動

日期：2026-10-29。狀態：accepted。實作計畫：[I0–I6](../../plans/agent-integration.md)。

## 決定

原生 Host 向 OS 申請空閒 port，只監聽 `127.0.0.1`。每個啟動 instance 將 descriptor 發布到同一使用者的私有 discovery 目錄，正常結束移除自身檔案。`host-id` 為安裝身分，`instance_id` 每次啟動更新；同時啟動採不可覆寫的原子發布保留同一 host-id。探索會驗證 owner／檔案權限／存活 PID／真正連線回傳的 instance，排除舊紀錄。這不是 IP broadcast、mDNS 或 LAN 探索，也不需要掃描固定 port。

未認證端只能探索、申請與查詢配對。配對有效 120 秒，最多八筆；Agent 產生不可預測的 claim，UI 顯示自報名稱、識別碼與核對碼。只有可信任原生介面能批准／拒絕；憑證結果限持有 claim 的端點取得一次。不能用配對覆寫既有 principal、輪替其憑證或繼承其授權。探索成功不代表已授權。

bootstrap 固定並隨 Agent 部署 publisher 公鑰。取得 toolkit 時驗證 ECDSA P-256/SHA-256 簽章、manifest 合約、wheel 大小及 SHA-256，才呼叫 uv。預建純 Python wheel 不含外部依賴；安裝時禁用索引、build、網路與 Python 自動下載。每個版本／雜湊使用私有獨立 uv 環境，先在 staging 安裝及健康檢查，再原子發布；失敗保留先前環境。不改 MyAgent 的 ML／voice dependencies。

工具程序為 stdio sidecar；token 只經管道初始化，不出現在程序參數、工具說明或模型回覆。工具登錄由 Agent 自身的 adapter／registry API 完成，套件只提供固定工具定義及允許的 MUP 操作。UI 文件仍是封閉式 schema，不能攜帶任意可執行 JavaScript、Python、Swift、shell 或 HTML。

## 狀態與情境的責任

MyAgent 的模型呼叫、工具執行、實際語音合成／播放、回答串流、任務進度都在原有執行入口發出事件，經 EventHub 非阻塞轉送。心跳來自 Agent 主程序，不能由仍存活的 sidecar 假冒 Agent 健康。模型推論與播報可以同時 active；不顯示模型未提供的內部思考內容或虛構百分比。

Host 依認證 principal、session、run-id 和單調 sequence 接受 runtime。另一個存活 session 不能覆寫狀態；原生面板能檢視所有已連接代理，但沒有讓 Agent 查其他 Agent runtime 的遠端 API。文字輸入綁定目前該代理 session；不自動重播可能已執行的指令。斷線後重新探索、認證及建立新 worker；拒絕／過期／撤銷需明確重試或重新授權。

P0 Awareness 沿用原本 Host 的 focus、selection、viewport、references 與 ACL。TaskBrain 每回合自行取得當下快照，不依賴模型記得呼叫工具；仍沿用 MyAgent 人類說話者身分政策。Agent 連線 token 不能取代人類身分驗證。情境字串明確標為不可信資料，禁止把文件文字當作指令。

`captured_at`／stale 依目前綁定 renderer 的存活回報更新；最後 interaction 時間仍保留原值，不假造新操作或增加語意版本。舊 epoch 不能刷新情境。這讓使用者停在同一個選取區間思考後仍可提問；renderer 停止回報才會過期。

## 信任與限制

獨立 uv 環境提供依賴隔離，**不是 OS 檔案系統沙箱**。只能安裝固定受信 publisher 的套件；本次沒有遠端更新平台、憑證撤銷清單或公證發行。私人簽章 key 僅在忽略的 `.cache/toolkit-signing/publisher.key`，不能放進 app／Agent／Git。遺失 key 時可封裝未變更的既有簽章 wheel；修改 toolkit 後須恢復 key 或明確更新所有 bootstrap 的信任，不會默默換 key。

Host token 存 macOS Keychain。Agent 端目前以 owner-only `credentials.json` 快取（0600、父目錄 0700），不是 Keychain；同一使用者本來就擁有此執行環境的權限。runtime 對話及待收指令只在記憶體，重啟不還原。工具呼叫狀態只上傳工具名稱，不上傳引數或結果。

目前 MyAgent adapter 已接線；其他 Agent framework 仍須一次性接上工具 registry 與 runtime callbacks。僅派送套件無法自動修改任何框架的工具清單。支援標準 callback 後，可共用相同 bootstrap、安裝與傳輸，不須重做探索／配對／SDK。
