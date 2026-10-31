# Maltose UI Host 0.4.0（MUP v0.3）

macOS 原生、本機優先的多代理互動工作區。Swift 6 / SwiftUI / AppKit 管理表面與授權；離線 React / Zod / ECharts 呈現封閉式文件；P0 Agent UI Awareness 提供授權後的 focus、selection、viewport 與有證據的 reference candidates。

目前支援 macOS 14+（本次實測 macOS 26.2 arm64、Xcode 26.6、Swift 6.3.3）。完整測試結果與已知限制見 [完成報告](docs/verification/report.md)。

## 直接連接 MyAgent

開啟 app，在 `/Users/Marvin/Workspace/MyAgent` 執行 `./start --maltose`，再於原生 UI 核對代碼、按「允許並記住」。系統會探索當下的 port、安裝已驗證的工具到獨立 uv 環境，並自動登錄工具；不需要複製憑證。此功能需要 uv 與本機 Python 3.12。

UI 可顯示真實模型推論／工具／播報狀態與對話；每回合 MyAgent 自動取得已授權的 focus、selection、viewport。既有說話者身分規則與跨代理 ACL 仍然有效。操作與故障排除見 [接入說明](docs/agent-integration.md)，最新實測見 [接入驗證報告](docs/verification/agent-integration-report.md)。

## 建置與執行

需 Xcode command line tools、Node.js 22+、Python 3.11+。首次取得依賴需要網路；封裝完成後啟動不需網路。

```sh
npm ci --cache .cache/npm
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
./scripts/bundle-renderer.sh
./scripts/swift-test.sh
swift run --skip-build MaltoseApp
```

若開發環境有沙箱，本機 listener、WKWebView 與 GUI 測試可能需要由環境核准；Host 本身不要求螢幕錄製或 Accessibility 權限。Swift 測試腳本將快取限定於專案內。

封裝本機 app：

```sh
./scripts/package.sh
open 'dist/Maltose UI Host.app'
```

產物為本機 ad-hoc 簽章，尚未公證。原生 app 自動選用空閒 port。多個程序不可同時操作同一個 database；headless Host 保留可明確指定的 port。

## 兩代理示範

1. 啟動 Host。在「代理存取」分別建立 `agent.investment` 與 `agent.maltose`，憑證存入 Keychain；一次性顯示的 token 交給各自 SDK。輪替使舊 token 失效。
2. 執行 `.venv/bin/python examples/two-agents/demo.py`，依提示貼上兩個 token；使用 getpass 輸入，不把憑證放進 shell history。
3. 投資代理建立合成市場圖表並持續更新 120 秒。滾輪縮放、右上框選工具選取區間；Investment context 可讀到區間，Maltose 預設不可見。
4. 在「跨代理分享」指定 `market-demo` → `agent.maltose`，套用摘要授權。文件／選取內容／viewport 必須各別勾選；摘要不包含這些資訊。
5. 按「獨立視窗」，再關閉該視窗以回附 Workspace，選取、zoom 與 stream 保留。
6. 撤銷分享：排隊事件與舊訂閱立即失效。SDK 重連時重新訂閱並讀取完整 snapshot。重新啟動 Host 後，文件與視窗配置還原，focus／selection 不還原；資料來源需重新註冊，離線 stream 顯示過期。

單代理文字範例：`.venv/bin/python examples/hello-world/main.py`。無 GUI 的相同核心：

```sh
.build/debug/MaltoseHost --state /tmp/maltose-demo.sqlite --port 8765
```

`MaltoseHost --register agent.example` / `--revoke agent.example` 是本機使用者命令；register 只於終端一次性輸出新憑證。沒有遠端註冊／授權命令。

## 測試

```sh
npm test
./scripts/bundle-renderer.sh
./scripts/swift-test.sh
MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh --filter WKRendererTests
.venv/bin/python -m pytest tests/protocol tests/integration tests/security -q
./scripts/package.sh
```

Swift 互通測試使用 `.venv/bin/python` 與 PATH 上的 Node，先執行 renderer/SDK build。GUI 測試預設會明確 skip；只有設定 MALTOSE_GUI_TESTS=1 且實際通過才算 GUI 已驗證。CI 使用 macOS runner；本次有另外實際執行 GUI 測試，證據見 docs/verification。

## 目錄

```text
apps/macos/MaltoseApp/         SwiftUI shell / AppKit windows / restricted WK bridge
apps/headless/                同一 Host 核心的 CLI
native/                       Swift actor、Protocol、Transport、ACL、SQLite、Awareness、Data
packages/mup-protocol/         JSON Schema 2020-12 / golden fixtures
packages/renderer/             React + TypeScript + Zod + ECharts / Vite offline build
packages/sdk-python/           async WebSocket / validation / reconnect / resync
packages/sdk-typescript/       WebSocket / validation / reconnect
examples/                     hello-world / market-dashboard / awareness-demo / two-agents
tests/                        native / protocol / integration / security / e2e
plans/                        全部開發計畫與里程碑狀態
docs/                         architecture / decisions / mup-spec / ui-awareness / security / verification
scripts/                      schema generation / build / verify / packaging
```

協定與權限見 [MUP](docs/mup-spec/README.md)、[Awareness](docs/ui-awareness/README.md)、[安全](docs/security/README.md) 與 [架構決策](docs/decisions/001-architecture.md)。UI 不接受任意 agent-generated JavaScript、Swift、shell 或 HTML。
