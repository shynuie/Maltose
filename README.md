# Maltose UI — 面板工作空間原型

目前專注於 UI：窗口、Glass 外框、Content 容器與面板排列。不接 Agent、不啟動 Host、不讀取資料庫或 Keychain、不建立 WebSocket listener。舊版基準保存在 Git 歷史 commit `8a73e7c`，目前工作樹已移除舊執行邏輯。

## 試用

```sh
./scripts/package-workspace-preview.sh
open 'dist/Maltose Workspace Preview.app'
```

需要 Xcode command line tools。macOS 26+ 使用系統 `NSGlassEffectView` Liquid Glass；macOS 14–25 使用 `NSVisualEffectView` 降級材質。純 UI 封裝不需要安裝 Node、Python 或其他依賴。

啟動後會自動要求進入原生全螢幕，與窗口綠色按鈕使用同一個 AppKit 功能。多螢幕依序進入，避免動畫相互干擾。無法進入或離開全螢幕時，使用填滿螢幕的半透明黑色背景。系統若未啟用各螢幕獨立 Spaces，僅主要窗口進入原生全螢幕，其他窗口以輔助窗口呈現。

可使用 `open -n 'dist/Maltose Workspace Preview.app' --args --windowed` 直接試用半透明黑色背景。

## 面板操作

- 拖曳 Glass 外框移動面板，可移至另一螢幕的窗口。
- 點擊面板會高光該面板；點擊工作區空白處會取消選取。在等大排列中拖曳空白處可用矩形框選面板，按住 `⌘` 框選可加入既有選取；也可按住 `⌘` 逐一點擊多選，再拖曳其中一個已選面板整批移到另一窗口。
- 雙擊 Glass 在等大排列與主面板間切換；主面板保留較窄的外框。
- 主面板模式中，在左緣停住滑鼠 1 秒展開縮圖側欄；離開即收起。
- 一般面板／主面板內容隨尺寸重新排列，縮圖保持完整畫面比例。
- 「聊天」面板使用本地示意資料；全局模式顯示目前 session，文字欄隨面板寬度伸縮、字級依可讀性調整；單一面板模式可在左側切換 session、右側閱讀對話。訊息支援 Markdown、連結與程式碼區塊；懸停訊息可複製整則內容，程式碼區塊可單獨複製。聊天面板不含輸入框，沿用窗口底部輸入欄。
- 「文檔」面板是唯讀 Markdown 瀏覽器，內建範例涵蓋文字、連結、程式碼、表格與本地圖片；文字可選取並用 `⌘C` 複製，圖片可由右鍵選單複製。全局模式中，文字欄和圖片隨面板寬度伸縮，圖片保持比例；文字低於最小可讀字級時隱藏。目前尚未開放載入任意本機 `.md` 文檔。
- 「圖表」面板可開啟或拖放 CSV：第一欄為 X 軸，中間的數值欄各畫成一條線，最右側 `note` 欄在資料點提示中顯示；內容底色透明，支援 X 軸縮放與平移、依可視範圍自動調整 Y 軸。Agent 可透過圖表生成參數指定線對與透明度，在兩條線之間顯示半透明區域；目前尚未接上 Agent。
- 在底部輸入 `test` 並送出，會播放形象核心五種狀態，並依序模擬工作區提示／設定、全局縮放、多選與重排、新增及關閉多個面板、聊天 session、側欄、Markdown、互動線圖、資料與畫布面板操作；形象與聊天維持單例，其餘內容面板可多開；結束後還原測試前的排列與面板設定。
- `⌘1` 或 Esc 返回等大排列；`⌃⌘F` 切換原生全螢幕，離開時使用半透明黑色背景。
- 從「面板 → 核心動畫測試…」或按 `⌥⌘0` 開啟獨立的 Visual Entity Playground；可切換狀態預設、調整九項視覺參數、觸發事件、模擬音量，並查看 Metal 渲染資訊。這是純 UI 測試，不會連接 Agent 或音訊服務。

示範內容只有原生畫布、可編輯筆記、曲線圖與資料表；所有狀態僅在記憶體中，重新啟動即重設。

## UI 驗證

```sh
./scripts/swift-test.sh --filter WorkspaceLayoutTests
MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh --filter Workspace
```

GUI 測試需可存取 macOS WindowServer，會暫時建立窗口與全螢幕 Space。規格與待確認項目見 [計劃](plans/glass-workspace.md)，驗證範圍見 [報告](docs/verification/glass-workspace-report.md)。
