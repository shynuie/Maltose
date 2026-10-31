# MyAgent 喚醒詞環境遺失修復

狀態：done；2026-10-29。使用者執行 `./start --maltose` 在 UI 接入之前因 `/private/tmp/myagent-kws310/bin/python` 不存在而失敗。

- [x] 檢查 MyAgent instructions、KWS／voice 計畫、目前設定與啟動順序，確認是喚醒詞隔離環境遺失。
- [x] 以 uv 在持久位置重建 Python 3.10 KWS 環境，保持主 Python 3.12 與 ML/voice dependencies 不變。
- [x] 保存可重建的獨立依賴清單／工具，更新 KWS Python 設定，不更換模型或放寬喚醒策略。
- [x] worker 啟動失敗時提供可操作診斷；補上缺少 interpreter、失敗清理與 config path 回歸。
- [x] 真正載入現有模型，執行 READY／health／PCM／reset／shutdown smoke（不開麥克風、不讀私人錄音）。
- [x] 執行相關與完整 MyAgent 回歸，回寫實際結果與未驗證範圍。

所有本次檔案變更只套用到明確列出的 MyAgent 路徑；保留其他未提交變更與正式資料。

## 實際結果

- 持久 uv 環境與 66 個含雜湊的套件鎖定完成；重建工具實際重跑通過。
- 原有模型 READY 最終 3.75 秒；health／合成靜音 PCM／reset／shutdown 通過。
- 38 個相關測試通過，含 7 個新 startup 回歸。完整 MyAgent 281 個案例：273 通過、3 個原有失敗、5 skipped。
- 完整實測與未驗證範圍：[報告](../docs/verification/kws-startup-fix-report.md)。真人麥克風／完整 ./start 及正式模型服務尚未由本次代為執行。
