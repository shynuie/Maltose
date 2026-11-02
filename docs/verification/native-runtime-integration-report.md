# 原生主 Agent 與面板工具整合驗證

日期：2026-11-01。範圍：M2／M3 階段的歷史驗證結果。後續正式資料、真實語音與 KWS 修正見 [M4 遷移報告](maltose-data-migration-report.md)；整體仍為 in_progress。

## 已實作

- App 先建立既有窗口，再啟動 Python 主 Agent；缺少受管理環境時顯示錯誤，可手動重試。`--ui-only` 明確保留面板試用模式。
- `maltose.desktop` 重用既有 CLI、VoiceAgent、TaskBrain。私有 NDJSON stdio 有版本、session、request ID、事件序號及就緒握手；diagnostics 使用 stderr，不另開瀏覽器或 listener。
- Supervisor 管理啟動逾時、初始化失敗、重試、合作式退出及必要的 owned process group 終止。kernel lease 防止同一設定啟動兩份 native runtime。ExitStack 在初始化失敗時也會清理已建立的資源；音訊 normalization／fallback wrapper 傳遞 worker 關閉。
- 啟用 KDB 的 native runtime 管理既有文件 watcher CLI，使用相同明確資料路徑。子程序以私有管線 EOF 感知父程序死亡；非預期退出會發布失敗事件，UI 保留背景服務故障提示。
- 沿用底部輸入與聊天面板，接收串流及實際工具／語音狀態，保存事件 journal 與輸入來源。關閉聊天面板不遺失事件；重開使用相同 live model。中斷尾行先備份再復原；完整紀錄損壞時不以示意資料取代。
- 36 個工具的 JSON Schema 與既有面板合約一致；新增 `read_panel`，讀取指定內容不切換使用者畫面。原生模型實例與 UI 操作共用。
- Agent 檔案操作經既有 FileService，傳輸內容上限 2 MiB。流程圖保存保留 hash 核對、文件身分及 dirty 保護；寫入成功但 UI 確認斷線時分開回報，避免誘發重複寫入。
- 檔案、命令與知識審核以原生確認控制回傳既有管理器，綁定當次 runtime session。專用 `native_approval` 事件只由審核管理器發出，一般模型 UI 卡片無法冒充；模型工具不能替使用者批准；重複通知不重複顯示，離線後的舊 callback 失效。
- App 主程序載入 owner-only mode 600 的私有 `.env`，只接受四種既有服務憑證變數，以資料方式解析並保留明確外部環境優先。不執行 shell，不匯入 PATH／Python 路徑等執行設定；symlink、FIFO、不安全權限、無效內容及重複設定拒絕。來源私有檔案的兩個既有服務設定已解析驗證，沒有輸出值，尚未搬移正式副本。
- 原生工具的參數、權限、檔案與連線錯誤回傳結構化結果，避免正常拒絕導致 Agent 程序退出。逾時標記為結果未知，不自動重試寫入。
- 原生傳輸合併執行中重複面板請求並快取最近 512 個結果；相同 ID 的不同操作拒絕。跨程序重啟沒有自動重送寫入。

## 證據

- 完整 Python：314 項，0 failures／errors，5 項 Docker integration skipped。日誌：`/tmp/maltose-native-stage-final-python.log`。
- 完整原生桌面 Swift：68 項全數通過，無 skip，包含既有全螢幕與跨螢幕測試。日誌：`/tmp/maltose-native-stage-final-swift.log`。
- 實際受管理 Python 子程序的 Echo 文字對話、現有 composer → chat → journal 重開、初始化失敗／逾時／重試／退出均通過。
- 腳本模型 fixture 經原本 TaskBrain 工具註冊與串流流程，跨實際 stdio 更新原生筆記 model，再回到聊天面板，通過；錯誤參數先被拒絕，模型能修正並繼續原任務。這驗證真實程序與操作鏈，模型回答本身是 fixture。
- 同一 pipe 的重複面板請求只執行一次；指定檔案不存在時，可使用經驗證的傳輸內容載入，App 不讀取該路徑。
- 實際空白 KDB watcher 在隔離 SQLite／LanceDB 資料啟動並合作式退出，SQLite integrity_check 通過；父程序突然退出的 worker 清理與 lease 釋放通過。
- 已產生包含 Python 原始碼資源的 `dist/Maltose.app` 並通過 strict ad-hoc codesign；從獨立 cwd 匯入確認使用發行包中的模組，133 個包內檔案通過私有憑證、資料庫、環境及模型目錄檢查，麥克風用途說明存在。日誌：`/tmp/maltose-native-stage-final-package.log`。最新版仍須於正式環境部署後完成 Finder 啟動驗收。

## 尚未完成的驗收

受管理主／KWS 環境部署、正式資料切換、根目錄更名、正式模型對話、真人麥克風及完整 App 冷啟動／崩潰恢復尚未驗收。Docker integration 未設定 opt-in 測試旗標而跳過，不能視為命令執行完整驗收；另以 `docker version` 確認 client 為 20.10.17，但無法連到本機 daemon（`/var/run/docker.sock`），尚未跑實際容器測試。Codex app-server、委派、持久任務與 @codex 交接仍待實作。

目前原生文字輸入不宣稱已完成聲紋驗證，私有內容讀取沿用既有身分政策。聊天 journal 是可重開的 UI 紀錄，不宣稱已還原 TaskBrain 的完整模型上下文；跨 runtime 的任務／控制狀態恢復仍屬後續協調層工作。沒有以模擬通過替代正式服務驗收。
