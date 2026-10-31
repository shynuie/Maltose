# Agent 接入與雙向互動驗證報告

2026-10-29，Asia/Shanghai。原生 app **0.4.0 build 5**；協定 **MUP v0.3**。原 M0–M6 的記錄保留於 [初版報告](report.md)；本次完成 [I0–I6](../../plans/agent-integration.md)，並修改真正的 `/Users/Marvin/Workspace/MyAgent` 接入。

## 完成內容

| 里程碑 | 結果 |
|---|---|
| I0 | 盤點兩專案執行／工具／UI 入口；保留 MyAgent 原有 command-execution 的四個未提交變更。 |
| I1 | 空閒 port、私有 discovery、stable host-id／每次啟動 instance-id、配對 proof／期限／批准／拒絕／單次領取、防止覆寫既有 principal。 |
| I2 | 嚴格 runtime schemas、session／run／sequence 邊界、原生狀態／串流訊息／輸入面板、15 秒心跳逾時。 |
| I3 | 固定 publisher 公鑰驗證、預建純 Python wheel、獨立 uv 離線安裝、stdio worker、工具登錄、斷線重新探索與換埠重連。 |
| I4 | MyAgent opt-in CLI／TOML、真實模型／工具／播報 hooks、EventHub、原生文字回既有工作佇列、每回合自動讀授權 context。保留說話者政策。 |
| I5 | 真正 Host／uv／sidecar／MyAgent 假模型；實際 ECharts 框選到 TaskBrain 的 GUI 全流程；撤銷、篡改、失敗復原與跨代理隔離。 |
| I6 | release app 封裝、簽章及資源／Keychain smoke、重新開啟 app 並驗證動態探索；操作／架構／限制文件。 |

既有 P0 Awareness 保留並接入真正 Agent：focus、selection、viewport、reference evidence、scope ACL 並非本次才提出的新功能。本次另修正存活 renderer 下的情境新鮮度，保留原本 interaction 時間與 context_revision，不假造新互動。

## 實際測試結果

| 執行內容 | 實際結果 | 證據 |
|---|---|---|
| 完整 Swift debug build／XCTest，GUI／Keychain flags 開啟 | **38 通過，0 failures，0 skipped** | [Swift log](integration-swift-tests.log) |
| 真正 ECharts 框選 → Host → 簽章 wheel → uv → MyAgent TaskBrain | **通過**；另有單獨測試 log | [GUI 全流程](chart-to-myagent-gui.log) |
| 動態探索／配對／真實 model-speech 事件／換埠重連／撤銷 | 包含於上述 Swift 測試；6 個核心接入案例全數通過 | [接入階段 log](agent-integration-tests.log) |
| Vitest／共用 schema fixtures／SDK／renderer | **22 通過，4 files** | [Vitest](integration-vitest.log) |
| Python protocol／SDK integration／security | **37 通過**；包含 14 個 bootstrap 安全案例 | [pytest](integration-pytest.log)、[bootstrap 安全](bootstrap-security-tests.log) |
| MyAgent 新增原生 UI 整合案例 | **8 通過** | [新增測試](myagent-native-ui-tests.log) |
| MyAgent 相關回歸 | 65 執行：**62 通過、3 個既有失敗** | [相關回歸](myagent-focused-tests.log) |
| MyAgent 完整回歸 | 274 執行：**266 通過、3 個既有失敗、5 skipped**（Docker integration 未啟用） | [完整回歸](myagent-full-tests.log) |
| 未修改 MyAgent HEAD 的隔離基線 | 40 執行：37 通過，重現相同 **2 failures + 1 error** | [HEAD 基線](myagent-baseline-tests.log) |
| renderer／TypeScript SDK／Swift release／app ad-hoc 簽章 | **通過** | [renderer build](integration-renderer-build.log)、[封裝 log](integration-package-build.log) |
| 封裝 schemas／renderer／toolkit、固定公鑰簽章／雜湊、Info.plist／strict codesign | **通過**；MyAgent bootstrap 與公鑰亦核對相同 | [封裝 smoke](integration-package-smoke.log) |
| 封裝 app 真實 Keychain 建立／讀取／輪替／移除 | **通過**，使用隔離測試 service | [Keychain smoke](integration-package-keychain.log) |
| 重新開啟已封裝 app、由 bootstrap 探索到真正動態 endpoint | **通過**，原生 UI 顯示已連線；沒有代替使用者正式配對 | [探索 smoke](packaged-discovery-smoke.log) |
| MyAgent `git diff --check` | **通過** | 本次本機實際執行 |

MyAgent 原有三個失敗：

- `test_executes_tool_then_returns_final_response`：測試未提供已辨識身分，個人記憶工具受既有政策阻擋。
- `test_taskbrain_exposes_user_profile_tool`：同樣預期未驗證身分可讀個人 profile。
- `test_taskbrain_exposes_task_tools_and_scopes_plan_to_user`：工具返回身分錯誤，測試仍索引 tasks，產生 KeyError。

這三項不是本次整合新增的失敗；已從 Git HEAD 匯出原始 `myagent`／`tests` 到暫存目錄，使用相同 Python 環境重現。**完整 MyAgent suite 並未全綠。** 沒有透過放寬人類身分驗證來使其通過。

## 測試方法與限制

- 真實元件：Network.framework WebSocket listener、標準函式庫 WebSocket bootstrap、ECDSA 驗證、實際 uv 建環境／安裝 wheel、stdio IPC、MyAgent 原有 TaskBrain／ToolRegistry／VoiceAgent、真正 WKWebView／ECharts canvas zoom／brush、原生視窗及 Keychain。
- 替身元件：模型回覆與語音合成 provider。測試確認實際模型呼叫／合成入口產生事件，但沒有呼叫正式模型或播放真人語音。GUI 框選使用真正 ECharts 畫布事件；配對只批准隔離、記憶體憑證的測試 Host。
- MyAgent 回歸從暫存 working directory 執行；HEAD 基線亦隔離匯出。未執行正式 `./start`，未修改使用者設定、正式憑證、文件、模型或資料庫。首次從原專案目錄執行舊測試曾因沙箱拒絕寫入預設 memory 路徑，後續統一暫存目錄重跑。
- Python SDK 的第一次 loopback 測試受環境沙箱阻擋；取得本機 listener 執行核准後，最終 37 項通過。
- app 重新開啟後已確認使用動態 port。第一次正式 Agent 配對需由使用者核對代碼並批准，沒有自動授予正式存取。
- CI 設定更新，**沒有執行遠端 CI**；沒有執行 xcodebuild project build、macOS 14 實機或公證。
- 獨立 uv 為依賴隔離，並非 OS 沙箱。Host 使用 Keychain；Agent 端目前使用 0600 私有 token 快取。runtime 訊息與輸入為暫態，重啟不還原；斷線不自動重播可能已執行的使用者指令。
- 其他 Agent framework 仍需要一次性 registry／runtime adapter。不能宣稱單純取得套件就能自動改動任意框架。

## 主要重現指令

在 UI repository：

```sh
python3 scripts/build-toolkit.py
npm test
./scripts/bundle-renderer.sh
MALTOSE_GUI_TESTS=1 MALTOSE_KEYCHAIN_TESTS=1 ./scripts/swift-test.sh
.venv/bin/python -m pytest tests/protocol tests/integration tests/security -q
python3 scripts/verify-myagent.py maltose
python3 scripts/verify-myagent.py focused
python3 scripts/verify-myagent.py full
python3 scripts/verify-myagent.py baseline
./scripts/package.sh
'dist/Maltose UI Host.app/Contents/MacOS/MaltoseApp' --self-test-resources
'dist/Maltose UI Host.app/Contents/MacOS/MaltoseApp' --self-test-keychain
codesign --verify --strict 'dist/Maltose UI Host.app'
```

GUI／本機 listener／Keychain 需正常 macOS 桌面權限。MyAgent 相關腳本使用本機既有 `.venv`、離線模型設定與暫存工作目錄；其他電腦沒有該專案時 MyAgent 跨專案 Swift 測試會明確 skip，不能算成通過。

## 待辦與阻礙

本次 I0–I6 的實作與本機驗證已完成。使用者驗收仍待：`./start --maltose` 搭配真實麥克風、現有模型服務、正式原生批准及日常互動。MyAgent 原有三個測試與身分政策的落差應另行修正測試或確認產品政策。本次沒有改動既有 command-execution 開發中的行為。

操作見 [使用說明](../agent-integration.md)，架構與信任決策見 [ADR 002](../decisions/002-agent-bootstrap-runtime.md)。
