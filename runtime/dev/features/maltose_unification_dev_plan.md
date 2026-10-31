# Maltose 產品整合

狀態：in_progress。最後更新：2026-11-01。

詳細規格與驗收以 [主計畫](../../../plans/maltose-unification-and-codex.md) 為準。決策見 [ADR 004](../decisions/ADR-004-unified-maltose.md)。

- [x] 保全原始歷史、未提交修改與私有資料，執行原生／Python 基準。
- [x] 以子目錄匯入來源歷史，按校驗清單保留現有工作，來源倉庫不變。
- [x] 改名為 `maltose` 套件與公開命令，保留舊設定讀取相容。
- [x] 按現有 lock 重建主 Python 3.12 與 KWS Python 3.10 環境。
- [x] 修正三項既存測試缺少已驗證身分的前提，補上未驗證時的拒絕檢查；不改正式政策。
- [x] 新設定優先、舊設定 fallback、CLI override 與相對路徑測試。
- [ ] 原生 App 自動啟動、就緒握手、退出與故障恢復。
- [ ] 真實聊天、共用面板工具、正式資料遷移。
- [ ] Codex 委派、@codex 交接與完成後主動確認。

驗證：新主環境完整套件 289 項，0 failures／errors，5 項 Docker integration 明確 skip；原生桌面 49 項全數通過；重建 KWS 使用既有模型通過 READY、health、靜音 PCM、reset。尚未驗收真人麥克風、正式模型對話、正式資料切換或 Codex。

下一步：以受管理 stdio 合約連接既有 CLI／VoiceAgent，接上 App supervisor，沿用現有事件與身分邊界。
