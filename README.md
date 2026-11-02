# Maltose — 個人 Agent 與工作空間

產品整合進行中：主 Agent 已匯入 `runtime/maltose`，保留原生面板與 Python Agent 各自的程序。進度與驗收見 [整合計畫](plans/maltose-unification-and-codex.md)。

目前來源已將 `@codex`、主 Agent 委派、持久任務、隔離工作目錄及暫停／交回接到原對話框。真實 Main 與 Codex 已在隔離專案完成委派、修改、測試、使用者追加需求與主 Agent 意圖確認；Codex 也實際呼叫共用工具建立及編輯原生面板。實體根目錄已更名為 Maltose，開發環境依鎖檔離線重建。0.7.0／build 11 試用包在舊路徑別名不存在時通過 runtime 來源比對、簽章、獨立匯入及私有資料檢查；build 11 的完整桌面回歸 141 項全部通過、無跳過，正式 build 11 已從 Finder 啟動並收到主 Agent 真實文字回答；真人語音、退出／重啟、完整故障矩陣及 Codex 專案附件重新定位仍待驗收，見 [桌面驗收](docs/verification/build11-desktop-acceptance.md)。Codex server 崩潰的獨立守護、清理確認與來源驗證見 [生命週期報告](docs/verification/codex-lifetime-report.md)。其他範圍見 [主 Agent 理解及清理報告](docs/verification/main-review-and-cleanup-report.md)，先前證據見 [協調層報告](docs/verification/session-coordination-report.md) 與 [語音交接及共用工具驗證](docs/verification/voice-handoff-and-shared-panels-report.md)。

Codex 沿用底部輸入欄與聊天面板；`@codex` 後的追加訊息持續給同一任務，面板切換不改變收件人。`@maltose` 或「交回麥芽糖」送回新的意圖；執行中的操作須先停止並核對。新任務透過已驗證的 app-server experimental 動態工具使用同一套 36 種面板操作；私有面板內容需當次已驗證的任務擁有者，或使用「Codex → 允許 Codex 讀取面板內容…」明確授權。該授權綁定目前任務、runtime 及交接，不能取得 Memory 身分或繞過檔案政策。更早建立、未註冊動態工具的 thread 不會自動獲得面板能力。

沿用既有窗口、Glass 外框、內容與排列。原生 App 已具備主 Agent 子程序管理、共用聊天串流、36 種面板工具與人員批准橋接；主 Agent 重用 Python CLI／VoiceAgent／TaskBrain，透過私有 stdio 連線。正式資料與 App 專用主／KWS 環境已切換至 Application Support，Finder 啟動已連到既有模型與語音。Codex 協作的完整驗收及桌面專案附件重新定位尚未完成。驗證範圍見 [正式遷移報告](docs/verification/maltose-data-migration-report.md)。

根目錄搬移、開發環境與舊路徑別名的範圍見 [重新定位報告](docs/verification/project-relocation-report.md)。

修補版 build 13 已獨立封裝，補上主 Agent 忙碌斷線及 Docker daemon 的持久資源守護；七項真實故障／同目錄恢復矩陣通過，旁觀容器保持正常。Python 408 項通過；Swift 141 項無失敗、15 GUI skip。正式 dist 仍為 build 11，尚未切換；正式 GUI、真人語音及完整 App 驗收仍在進行。詳見 [Docker 生命週期與故障矩陣](docs/verification/native-docker-lifetime-report.md)。

本輪另完成真正 CLI 未登入及執行檔缺失的產品協調驗證，原需求會保留、Main 保持暫停，明確新意圖才交回。登入提示已指向現有 Codex 選單；獨立 trial 更新至 build 14，Python runtime 與 build 13 相同，正式 dist 尚未切換。範圍見 [認證失敗驗證](docs/verification/codex-auth-failure-report.md)。

聊天自動追蹤與 30 秒閱讀保護已更新至正式 build 15，保留 build 11 回復包；聊天聚焦測試通過，完整回歸仍有原生全螢幕失敗及實際手勢驗收限制，見 [聊天捲動報告](docs/verification/chat-autoscroll-report.md)。

## 試用

重建預設 `dist/Maltose.app` 前先退出 Maltose。若要保留目前執行版本，使用 `MALTOSE_PACKAGE_OUTPUT` 指定另一個 `.app` 輸出位置。

```sh
./scripts/package-maltose.sh
open 'dist/Maltose.app'
```

建置與測試可用 `MALTOSE_BUILD_DIRECTORY` 指定另一個編譯快取目錄；更名後的驗證使用新實體目錄及全新快取。

需要 Xcode command line tools。macOS 26+ 使用系統 `NSGlassEffectView` Liquid Glass；macOS 14–25 使用 `NSVisualEffectView` 降級材質。只試用面板時，請以 `open -n dist/Maltose.app --args --ui-only` 啟動；此模式不啟動主 Agent。一般啟動會查找 `~/Library/Application Support/Maltose/` 的設定與受管理 Python，缺少時顯示原因，面板仍可使用。

啟動後會自動要求進入原生全螢幕，與窗口綠色按鈕使用同一個 AppKit 功能。多螢幕依序進入，避免動畫相互干擾。無法進入或離開全螢幕時，使用填滿螢幕的半透明黑色背景。系統若未啟用各螢幕獨立 Spaces，僅主要窗口進入原生全螢幕，其他窗口以輔助窗口呈現。

可使用 `open -n 'dist/Maltose.app' --args --windowed` 直接試用半透明黑色背景。

## 面板操作

- 拖曳 Glass 外框移動面板，可移至另一螢幕的窗口。
- 點擊面板會高光該面板；點擊工作區空白處會取消選取。在等大排列中拖曳空白處可用矩形框選面板，按住 `⌘` 框選可加入既有選取；也可按住 `⌘` 逐一點擊多選，再拖曳其中一個已選面板整批移到另一窗口。
- 雙擊 Glass 在等大排列與主面板間切換；主面板保留較窄的外框。
- 主面板模式中，在左緣停住滑鼠 1 秒展開縮圖側欄；離開即收起。
- 一般面板／主面板內容隨尺寸重新排列，縮圖保持完整畫面比例。
- 「聊天」面板在 `--ui-only` 使用示意資料，正常啟動則載入本機對話紀錄並接收 runtime 串流；全局模式顯示目前 session，文字欄隨面板寬度伸縮、字級依可讀性調整；單一面板模式可在左側切換 session、右側閱讀對話。訊息支援 Markdown、連結與程式碼區塊；懸停訊息可複製整則內容，程式碼區塊可單獨複製。聊天面板不含輸入框，沿用窗口底部輸入欄。
- 聊天在全局、主面板及側欄模式都會隨新訊息與串流回答自動捲到最下方；手動捲離底部後保護閱讀位置 30 秒，每次手動捲動重新計時。手動回到底部立即恢復；滿 30 秒後在下一次訊息更新恢復。切換工作區模式保留同一對話的閱讀保護，其他對話各自計算。
- 「文檔」面板是唯讀 Markdown 瀏覽器，內建範例涵蓋文字、連結、程式碼、表格與本地圖片；文字可選取並用 `⌘C` 複製，圖片可由右鍵選單複製。全局模式中，文字欄和圖片隨面板寬度伸縮，圖片保持比例；文字低於最小可讀字級時隱藏。目前尚未開放載入任意本機 `.md` 文檔。
- 「圖片」面板內建六張比例不同的測試圖，也可在面板模式加入多張本機或 HTTP(S) 圖片。全局模式只顯示目前圖片；面板模式固定顯示前一張、目前圖片、下一張三個 16:9 畫框，清單起點的左側縮圖留空，水平滑動或點縮圖切換。雙擊任一圖片可放大，觸控板捏合縮放、直接拖曳平移，再雙擊返回預覽。
- 「畫布」面板是結構化流程圖，可新增開始、步驟、判斷、結束和註記節點，編輯文字、拖動與多選節點、建立方向連線、刪除選取內容，並平移／縮放畫布；內建一個可直接編輯的需求處理流程範例。可新增、開啟、儲存、另存與刪除 `.maltoseflow.json` 文件，切換文件前會提示處理未儲存變更；文件包含節點、位置、文字和連線，Agent 工具沿用同一個 model。
- 「網頁」面板以系統 WebKit 瀏覽網址或搜尋內容，支援基本返回、前進、停止／重新載入、頁面連結和原生媒體播放。預覽 app 預放 YouTube 影片與 Google 新聞兩個頁面；全局與側欄縮圖顯示站點資訊或最近瀏覽頁面的截圖，放大後才建立可互動網頁視圖；影片不會自動播放。
- 「圖表」面板可開啟或拖放 CSV：第一欄為 X 軸，中間的數值欄各畫成一條線，最右側 `note` 欄在資料點提示中顯示；內容底色透明，支援 X 軸縮放與平移、依可視範圍自動調整 Y 軸。Agent 可透過圖表生成參數指定線對與透明度，在兩條線之間顯示半透明區域；Agent 工具沿用相同的圖表操作入口。
- 在底部輸入 `test` 並送出，會播放形象核心五種狀態，並依序模擬工作區提示／設定、全局縮放、多選與重排、新增及關閉多個面板、聊天 session、側欄、Markdown、互動線圖、圖片瀏覽與縮放、資料與畫布面板操作；形象與聊天維持單例，其餘內容面板可多開；結束後還原測試前的排列與面板設定。
- `⌘1` 或 Esc 返回等大排列；`⌃⌘F` 切換原生全螢幕，離開時使用半透明黑色背景。
- 從「面板 → 核心動畫測試…」或按 `⌥⌘0` 開啟獨立的 Visual Entity Playground；可切換狀態預設、調整九項視覺參數、觸發事件、模擬音量，並查看 Metal 渲染資訊。這是純 UI 測試，不會連接 Agent 或音訊服務。
- 從「面板 → UI 感知測試…」或按 `⌥⌘V` 開啟 `get_user_view` 測試窗。按「發送」會讀取各螢幕窗口的模式、目前可見／隱藏面板、選取與面板內容摘要，並以 JSON 顯示。也可從「載入操作範例」逐項測試建立／關閉／選取／切換／移動面板及各面板操作，編輯 JSON 後按「執行指令」；操作會套用到目前工作區。主面板回傳內容摘要，全局格子／側欄縮圖／隱藏面板只回精簡資訊；本機模擬與原生 runtime 工具共用這套操作核心。

示範內容包含流程圖畫布、可編輯筆記、曲線圖與資料表；流程圖文件可另行保存，其他示範面板狀態在重新啟動後重設。

## UI 驗證

```sh
./scripts/swift-test.sh --filter WorkspaceLayoutTests
MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh --filter Workspace
```

GUI 測試需可存取 macOS WindowServer，會暫時建立窗口與全螢幕 Space。規格與待確認項目見 [計劃](plans/glass-workspace.md)，驗證範圍見 [報告](docs/verification/glass-workspace-report.md)。

Agent 合約、狀態盤點、36 種操作與模擬方式見 [共用面板介面](docs/architecture/workspace-agent-interface.md)，本次結果見 [驗證報告](docs/verification/workspace-agent-interface-report.md)。

## 主 Agent 開發環境

以 `./scripts/setup-runtime.sh` 依現有 lock 重建主環境，再使用 `runtime/.venv/bin/maltose`。新的設定檔名為 `maltose.toml`，沒有新檔時仍可讀取舊 `myagent.toml`；CLI 的 `--config` 可明確指定設定。App 的正式資料、受管理環境與 Finder 啟動已驗證，並已觀察到既有模型的真人語音多輪回答與原生面板操作。完整身分／中斷／裝置及協作恢復矩陣仍依整合計畫驗收；Echo／腳本模型測試與真實服務證據分開記錄。

## App 專用環境與資料遷移

`./scripts/setup-managed-runtime.sh` 在 `~/Library/Application Support/Maltose/environments/` 依原鎖檔建立主 Python 3.12.10 與 KWS Python 3.10.19，不安裝 editable checkout、不複製舊 venv。若 pyenv shim 不可用，可用 `MALTOSE_MAIN_PYTHON`／`MALTOSE_KWS_PYTHON` 指定已安裝且版本相符的實際 interpreter。

遷移工具為 `runtime/maltose/migration.py`，使用 `--source`、`--destination` 與 `--project` 明確指定來源、Application Support 及開發工作目錄。執行前必須退出新舊 Agent 並停止來源 writer；完成後保留原專案與私有停寫備份。已完成的匯入不覆寫後續資料，遇到中斷或衝突會保留可檢查的收據與副本。詳見 [遷移與回復報告](docs/verification/maltose-data-migration-report.md)。

App 預設使用 Application Support。隔離測試可用 `MALTOSE_DATA_DIR`（舊名 `MYAGENT_DATA_DIR` fallback）指定絕對路徑；設定路徑可明確指定 `MALTOSE_CONFIG`。新名稱優先，App 與 runtime 不依賴 Finder 的 cwd／互動 shell PATH。正式 `.env` 為 owner-only mode 600 的資料檔，不執行 shell，只接受既有服務憑證；不得加入 Git 或發行包。
