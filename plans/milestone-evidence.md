# 里程碑執行紀錄

所有時間採 Asia/Shanghai，2026-10-29。

| 階段 | 實際增量 | 階段驗證 |
|---|---|---|
| M0 | 檢查空目錄、macOS/Xcode/Swift/Node/Python；SwiftPM、Vitest、pytest/CI、ADR | 最小 Swift app + XCTest 1 通過；依賴下載取得後 Vitest 基礎通過 |
| M1 | v0.3 schemas、共同 valid/invalid fixtures、Swift schema validator、SDK 骨架 | Swift schema 3 tests、Vitest 11、pytest 11 通過；revision conflict 後於 M3 接入 actor 驗證 |
| M2 | Network.framework loopback、Keychain、ACL、SQLite WAL/migration、Workspace/NSWindow | 階段 Swift 6 tests 通過；真實 transport 首次受沙箱拒絕，核准後 2 tests 通過 |
| M3 | React/Zod/ECharts、離線資產、受限 bridge、atomic patch | 階段 Swift 8、Vitest 13 通過；ES module 原生載入失敗後改 IIFE，WKWebView 實測通過 |
| M4 P0 | context collector/store、principal revisions、events、scoped resolver | 階段 Swift 13 通過；含焦點、選取、viewport、stale/ambiguity、ACL、來源偽造與資訊遮蔽 |
| M5 | detach/attach、layout/zoom 保存、data registry、SDK reconnect/resync | lifecycle 3 tests 通過；Python/TS 真實 native Host 互通通過 |
| M6 | 雙代理範例、分享撤銷 UI、安全回歸、封裝、文件 | 最終測試與 release/簽章結果見 docs/verification/report.md；不將 skip 視為通過 |

## 曾發生且已處理的問題
- SwiftPM 預設快取寫入沙箱外失敗 → 模組快取與 SwiftPM paths 改至 .build。
- 依賴下載 / loopback listener 受沙箱限制 → 經工具核准下載與執行本機測試；未擴大 Host 對外監聽範圍。
- Swift 6 WebKit callback 的 MainActor/Sendable 宣告不相符 → 修正後重新建置；導航 delegate 也以正確 signature 驗證。
- Vite ES module 在 WKWebView file URL 下空白 → IIFE 離線 bundle，真實 canvas/zoom/brush 測試通過。
- TS NodeNext 對 CommonJS default import 型別不相容 → 使用具名 Ajv2020 與明確 plugin 型別；編譯後 SDK 及實際 WebSocket 測試通過。
- 回歸檢查發現跨代理焦點變更可能夾帶私人 surface_id → 在事件與快照雙層遮蔽，加入安全測試。
- 新增敏感旗標時舊選取可能殘留 → 原子 patch 清除失效/敏感的 selection、viewport、interaction 與 focus。
- 額外 Keychain 實測回 OSStatus -50，定位為 macOS 不接受 kSecReturnData + kSecMatchLimitAll。依 Apple 文件改為先列屬性後逐筆讀取，實測註冊／輪替／認證／撤銷通過；保留原失敗與修正後 log。
