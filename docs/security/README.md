# 安全邊界與範圍

- 僅 IPv4 loopback listener；未開放 LAN、IPv6 或外部網路。Network.framework 處理 WebSocket frame、訊息上限、ping、握手；5 秒未認證即斷線。
- 登錄、輪替與撤銷由可信任本機 UI / CLI 發起。Keychain 保存憑證。每個指令及事件 pump 重新驗證憑證；Host 不信任 payload 內的 owner/principal。
- Agent 預設只有自身表面。跨代理 grant 是 read-only 明確 scopes；不會給寫入權限。summary 不包含文件、node ID、選取值或資料。撤銷清除未送事件及讀快取、終止舊訂閱。
- 不記錄 token、文件內容、選取值或原始鍵盤/游標資料；audit 僅時間、principal、動作。稽核最多 10000 筆。SQLite 檔案 0600，app support 目錄 0700；WAL 與資料同目錄。
- Renderer 只接受 stack / text / button / table / chart.line。禁止 agent-generated JS/Swift/shell、HTML、任意 URL、DOM dump、外部網路。React 的文字 escaping 與 schema allowlist 共同防護。
- bridge 綁定 surface、epoch、document revision、單調 sequence，驗證 frame/WebView/file 來源。敏感 node 不納入 awareness，不接受其 selection/action。變更敏感旗標或刪除 node 時清除暫態參照。
- 引用解析結果包含 evidence/freshness/ambiguity，不能作為自動破壞操作授權。過期候選排除。
- 未要求 Accessibility、Screen Recording、全域輸入監聽或其他應用程式內容。沒有交易功能。

部署限制：目前是本機開發用 ad-hoc 簽章，沒有 Developer ID / notarization / Hardened Runtime 發佈流程。資料庫未加密（依賴 macOS 使用者目錄與磁碟安全）；具同一 OS 使用者完整檔案權限的惡意程式不在此隔離模型內。Keychain 已以隔離 service 實測建立、輪替、認證與刪除；重裝、跨簽章身分後的存取提示與授權行為尚未驗證。
