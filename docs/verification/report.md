# Maltose UI Host v0.3 完成與驗證報告

本報告記錄初版 M0–M6。後續 0.4.0／MyAgent 接入與最新測試結果見 [接入驗證報告](agent-integration-report.md)。

日期：2026-10-29（Asia/Shanghai）。原始規格保留於 repository 根目錄；所有開發計畫集中 `plans/`。此目錄原本只有規格，已初始化為獨立 Git repository；未建立 commit、remote 或推送。

## 里程碑

- [x] M0：macOS / Xcode / Swift / Node / Python 盤點、部署目標、架構決策、SwiftPM / Vitest / pytest 與 CI 設定。
- [x] M1：MUP v0.3 command / response / event / document / surface / context / bridge JSON Schema 2020-12；Swift / TS / Python conformance、共同 golden / invalid fixtures 與 SDK。
- [x] M2：127.0.0.1 WebSocket、伺服器 session、Keychain 註冊 / 認證 / 輪替 / 撤銷、ACL、SQLite WAL 與 v1 migration、Workspace / NSWindow。
- [x] M3：離線 React / Zod / ECharts、文字 / 按鈕 / 表格 / 圖表、來源綁定 Native bridge、ui.render / atomic ui.patch 與互動事件。
- [x] M4 P0：具名 UIContextSnapshot、AppKit focus、semantic selection / viewport、獨立 principal context revisions、include / freshness / resync、bounded subscriptions、scoped reference candidates / evidence / ambiguity。
- [x] M5：detach / attach 保留 node / selection / zoom / stream、Host 蒐集螢幕配置、視窗 / user overrides 保存、data registry、SDK reconnect / event dedup / snapshot resync。
- [x] M6：兩代理合成資料 demo、明確 scopes 分享與即時撤銷、security regressions、release app 封裝與操作文件。

增量與各階段實際證據見 `plans/milestone-evidence.md`。M1 的 revision conflict fixtures / 測試於 M3 接上真正 actor 之後驗證，未以 schema 測試代替狀態機測試。

## 環境與最終結果

macOS 26.2 / arm64，Xcode 26.6 (17F113)，Apple Swift 6.3.3，Node 25.1.0，npm 11.6.2，Python 3.12.12。宣告部署目標 macOS 14；未在 macOS 14 實機驗證。

| 實際執行 | 結果 | 證據 |
|---|---|---|
| SwiftPM debug build + XCTest（含 GUI / Keychain flags） | **28 tests 通過，0 failures，0 skipped**，2026-10-29 12:45:18 | [完整 Swift log](swift-final-tests.log) |
| Vitest | **14 tests 通過**，4 files | [Vitest log](vitest.log) |
| pytest protocol / integration / security | **15 tests 通過** | [Python log](python-final-tests.log) |
| React / TypeScript / Vite + TS SDK build | 通過，全資產離線打包 | [renderer build](renderer-build.log)、[package build](package-build.log) |
| Swift release build / app bundle / ad-hoc codesign | 通過；簽章 strict verification 通過 | [package build](package-build.log) |
| 已封裝 app 的 schema / renderer resource smoke、Info.plist | 通過 | [package smoke](package-smoke.log) |

Swift 的實測包含真實 Network.framework listener 與 URLSession WebSocket、Python 與 TypeScript SDK 對同一 native Host 互通、隔離 service 的真實 Keychain 建立 / 輪替 / 認證 / 刪除、2 個真正 macOS GUI 測試。GUI 走過離線 WKWebView 畫布載入、ECharts 滾輪縮放、工具列框選 / 拖曳、結構化選取回傳、外部導航拒絕、NSWindow 獨立 / 回附與幾何保存。這些項目不是僅模擬 Host 訊息。

本次使用 SwiftPM 及 Xcode 隨附的 Swift compiler 在 macOS 實際建置；**沒有執行 Xcode project / xcodebuild app build**，也沒有宣稱其通過。GitHub Actions 設定已建立，**尚未在遠端 CI 執行**。完整互動 GUI 測試使用 debug resource bundle；release `.app` 本次執行了封裝資源 smoke 與簽章驗證，未另外完整手動重走兩代理示範。

## 實際指令

均在 repository 根目錄執行；測試證據的最後一次採下列指令（log 以 `>` 儲存）：

```sh
sw_vers
xcode-select -p
swift --version
xcodebuild -version
node --version
npm --version
python3 --version
npm install --cache .cache/npm --no-audit --no-fund --fetch-retries=0
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check pytest jsonschema websockets
python3 scripts/generate-schemas.py
python3 scripts/generate-ts-schema.py
npm test
./scripts/bundle-renderer.sh
./scripts/swift-test.sh --skip TransportTests
./scripts/swift-test.sh --filter TransportTests
MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh --filter WKRendererTests
MALTOSE_KEYCHAIN_TESTS=1 ./scripts/swift-test.sh --filter KeychainTests
MALTOSE_GUI_TESTS=1 MALTOSE_KEYCHAIN_TESTS=1 ./scripts/swift-test.sh
.venv/bin/python -m pytest tests/protocol tests/integration tests/security -q --tb=short
./scripts/package.sh
'dist/Maltose UI Host.app/Contents/MacOS/MaltoseApp' --self-test-resources
codesign --verify --strict 'dist/Maltose UI Host.app'
plutil -lint 'dist/Maltose UI Host.app/Contents/Info.plist'
git init -b main
```

`swift-test.sh` 明確設定專案內 module / SwiftPM cache paths；`package.sh` 內執行 `swift build -c release` 與資源複製、簽章。npm / Python 依賴下載、loopback 與 GUI / Keychain 測試曾使用環境核准的執行方式；未開放 Host 的 LAN listener，未變更 OS 觀察權限。

## 失敗與修正

- 初始 SwiftPM cache 路徑不可寫：改用專案 `.build`；初始依賴下載 / listener 被沙箱拒絕：使用經核准的依賴下載與本機測試執行。
- Swift 6 WebKit 回呼 signature 不符：修正 MainActor / Sendable 後重建；導航拒絕經 GUI 驗證。
- file URL 下 ES module 空白：改 IIFE 離線 bundle，實際 WKWebView canvas / zoom / brush 通過。
- Keychain OSStatus -50：是原始程式錯誤，不是環境權限。macOS 密碼項目不可同時查 kSecMatchLimitAll / kSecReturnData；先列 attributes 再逐筆讀取後通過。原 [失敗](keychain-test.log) 與 [修正後證據](keychain-fixed-test.log) 均保留。
- 焦點事件跨代理身分、變更 sensitive 旗標後的舊選取：加入遮蔽與暫態清除、安全回歸。
- 最後新增 data_stale 時 TS SDK 舊產物與 schema 不同步：重建 SDK，再跑最後完整測試，28 tests 通過。後續驗證必須先跑 renderer / SDK build。

## 安全決策

預設 own-surfaces-only；不信任客戶端 principal/owner；跨代理只能本機使用者給 read-only 明確 scopes。summary 不給文件、選取或資料值，查詢、事件、引用解析均重新套 ACL；撤銷終止舊訂閱及清除排隊資料。Focus / selection 與文件 revision 分離；principal revisions 不洩漏私人代理活動。Sensitive node 不進 awareness。bridge 驗證主 frame / file 來源、surface、epoch、文件版本與 sequence。只允許已登錄 action。

憑證保存在 Keychain，Registry 僅快取雜湊。文件與 idempotency 以同筆 SQLite 交易提交，DB 0600 / app support 0700；audit 不含文件、選取值與憑證。沒有 agent-generated executable UI、外部網路資產、Screen Recording 或全域 Accessibility。

## Repository 結構

```text
apps/{macos/MaltoseApp,headless}/
native/{Protocol,Transport,AgentRegistry,Permissions,StateStore,SurfaceManager,
        ContextCollector,ContextStore,ReferenceResolver,EventRouter,DataRegistry}/
packages/{mup-protocol,renderer,sdk-python,sdk-typescript}/
examples/{hello-world,market-dashboard,awareness-demo,two-agents}/
tests/{native,protocol,integration,security,e2e}/
docs/{architecture,decisions,mup-spec,ui-awareness,security,verification}/
plans/{implementation.md,milestone-evidence.md}
scripts/  .github/workflows/ci.yml  Package.swift  README.md
```

## 操作示範與剩餘工作

啟動 `dist/Maltose UI Host.app`，建立 agent.investment / agent.maltose 的 Keychain 憑證，再執行 `.venv/bin/python examples/two-agents/demo.py`，依序縮放、框選、分享摘要、獨立視窗、撤銷、重連。完整逐步說明在 [README](../../README.md)。不使用真實交易或市場憑證。

目前無阻止本機 MVP 建置與已列測試的阻礙。以下仍需後續工作，未當成已驗證功能：

1. Developer ID / Hardened Runtime / notarization 與跨簽章重裝後的 Keychain 授權驗證；目前只有本機 ad-hoc 簽章。
2. macOS 14 實機、遠端 CI、真實多螢幕拖放 / 螢幕拔除與長時間效能、磁碟壓力測試；目前螢幕配置 collector / clamp 邏輯存在，未在多螢幕實機走測。
3. `visible_nodes` 目前是可見 surface 中可呈現的非敏感節點，尚無一般 DOM intersection / scroll / 遮擋感知。chart 有實際 x_domain。
4. TypeScript SDK 以 needsResync / context() 提供缺口同步，呼叫端需在事件通知後採用新 snapshot；Python events() 可自動 yield resync snapshot。撤銷後的訂閱必須明確重新建立。
5. SQLite 未加密、沒有應用層磁碟總量配額。無畫面或外部應用程式感知；IPv6、overlay / Companion polish 保留為後續擴充，capabilities 明確回 overlays=false。

## 0.3.1 憑證建立修復（2026-10-29）

使用者回報的視窗仍是 12:41 啟動的舊程序，早於 12:44 完成的 Keychain release 修正版。已重新封裝為 0.3.1 / build 4、重新開啟並確認 listener 正常；保留使用者輸入 maltose.main。

新增憑證錯誤提示的 2 個 controller tests 通過，並實際以封裝 App 的簽章身分執行隔離 Keychain read/write/rotation/revocation，結果見 [packaged-keychain-smoke.log](packaged-keychain-smoke.log)。未替使用者點擊正式憑證建立或輪替。完整修復計畫及驗證見 plans/credential-registration-fix.md。
