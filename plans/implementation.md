# Maltose UI Host 開發計畫

所有開發計畫集中於此目錄；架構決策與驗證證據另存 docs/。

## 原則
- 依 M0 → M6 完成可建置的增量；每階段執行建置及相關測試。
- Agent UI Awareness 為 P0；從狀態、授權與協定設計起納入。
- Host 掌握所有權、焦點、視窗幾何與事件順序；Renderer 只發送驗證過的語意互動。
- 不執行代理提供的 JavaScript、Swift、Shell；不擴大系統權限。
- 保留原始規格；不宣稱未執行的測試通過。

## 里程碑
- [x] M0：環境盤點、架構/部署目標、Swift/renderer/Python 測試基礎、CI。
- [x] M1：JSON Schema 2020-12、Swift/TS/Python 驗證、SDK 基礎、golden/invalid fixtures。
- [x] M2：loopback WebSocket、Keychain 註冊與認證、ACL、SQLite WAL、原生生命週期。
- [x] M3：離線 React/Zod/ECharts、受限 WKWebView bridge、文件與原子 patch。
- [x] M4：結構化 context、獨立 revision、focus/selection/viewport、訂閱與 reference candidates。
- [x] M5：detach/attach、持久化 layout、Python SDK、資料訂閱、reconnect/resync。
- [x] M6：雙代理 demo、分享/撤銷、安全回歸、封裝與完整操作/驗證文件。

## 已知起點
- 工作目錄僅有原始規格，並非 Git repository；無既有相容程式需遷移。
- macOS 26.2 (arm64)，Xcode 已安裝，Swift 6.3.3。
- 待確認 Node/Python、依賴取得、原生 GUI 的可驗證範圍。

## 完成
M0–M6 本機 MVP 已完成。最終實測：Swift 28（含 Keychain / GUI / 真實雙 SDK）、Vitest 14、pytest 15 通過；release app 與簽章 / 資源 smoke 通過。限制與未執行範圍見 docs/verification/report.md。

## 後續：真實 Agent 整合
M0–M6 完成僅涵蓋 Host/SDK，不包含 MyAgent 的 runtime 接線。已完成 [Agent 自動接入與雙向互動](agent-integration.md)，將既有 P0 context 接進 MyAgent，並實作動態 port 探索、原生批准配對、獨立 uv 工具程序與執行狀態同步。

2026-10-29 接入增量已完成 I0–I6，Host／SDK 與實際 MyAgent 已接線。最新建置與測試：Swift 38、Vitest 22、pytest 37 通過；MyAgent 完整 suite 有 3 個已由原始 HEAD 重現的既有失敗。詳見 docs/verification/agent-integration-report.md。
