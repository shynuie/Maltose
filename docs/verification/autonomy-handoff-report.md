# 主 Agent 執行權與交接核心驗證

日期：2026-11-01。狀態：`in_progress`。範圍：[整合主計畫 M2／M6](../../plans/maltose-unification-and-codex.md)。

## 實作與邊界

`AutonomyControl` 為原生 runtime 的共用執行權控制。關閉新動作的派發後，保留已准入操作的 lease；只有實際操作全部離開，狀態才從 pausing 轉為 paused。主對話、模型請求／串流、工具、通知播報、TTS render／play／synthesize、排程派發及 TaskManager worker 都使用同一個控制物件。

這個控制不等待 IPC reader 內的工具完成。面板 RPC 仍可回覆，觀察、語音辨識與事件保存仍可繼續。狀態包含 owner／lease、epoch、version 及實際 in-flight 計數；App 端驗證 paused 必須沒有未完成活動。恢復需要目前的 owner／lease 及明確的新意圖標記，並先將舊排隊工作和 active schedules 標為 held，交由既有已驗證使用者的 retry／resume 工具重新檢查。

一般啟動沿用原排程行為。只有恢復一個原本就在交接中的 runtime，才會在啟動時保留舊工作為 held；不因加入這個功能而停用所有日常排程。Epoch 與 execution attempt ID 阻止舊佇列在恢復後偷跑或覆蓋新 retry。

Native private RPC 新增 pause／resume／snapshot 控制結果，支援 startup owner 與 input routing capability。這些方法沒有註冊成 Agent 工具，模型不能自行恢復自主執行。RuntimeSupervisor 可非同步取得結果，處理逾時、取消觀察、程序 generation 與過期結果；它不因沒有收到回覆而重送控制操作。

## 對話、語音與資料

- 中斷時保留已完成的工具結果。沒有結果的呼叫標為 unconfirmed，要求核對狀態後再重試；不把暫停描述成回滾，也不聲稱所有未知操作都未執行。
- 部分串流在交接時有 assistant_end／interrupted 收尾，不把未顯示的新 token 接到舊回答。
- 播音與 rendering 自己持有 lease，即使 UI 或主消費迴圈已返回，也不能以此冒稱音訊活動結束。
- 暫停期間輸入送回協調層事件，保留 message ID、來源、speaker status／score／user ID 及 capture epoch。交接前排隊的輸入標為 deferred，不當作新的 Codex 指令。UI 連線或文字來源不會自動變成 identified。
- 沿用原 KWS／STT；暫停期間的單純喚醒詞只開啟聆聽，不送給 Codex，也不重設 Maltose 的短期對話。新的 verification／user scope 不沿用前一個已驗證使用者的私有短期歷史；插話分類不再更動主要對話身分。
- `AgentComposerMessage` 定義前綴 `@codex`／`@maltose` 及目前收件人的解析。引文、程式碼、正文或 `@codexfoo` 不觸發切換；面板的選取不參與解析。
- 根目錄產生的 Memory／task／speaker／Knowledge 資料已加入忽略清單，原有 `data/imgs` 資產保留。

## 程序生命週期

原生模式的 TaskManager 在退出時等待受管理 worker，App supervisor 仍保有既有的 grace／TERM／KILL 上限。Native runtime 的 kernel lease 保留到 interpreter shutdown，避免主函式先返回、背景工作仍在收尾時，就讓另一個 runtime 取得同一設定的寫入權。一般 CLI 的退出選擇不因此改成原生模式。

## 測試結果

```sh
runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_autonomy_control.py'
./scripts/swift-test.sh --filter RuntimeControlTests
runtime/.venv/bin/python -m unittest discover -s runtime/tests
MALTOSE_CODEX_TESTS=1 ./scripts/swift-test.sh
```

- Python control 聚焦：13 項通過，無 skip。
- Swift control 聚焦：5 項通過，無 skip。
- 完整 Python：353 項，0 failures／errors，5 Docker integration skip。執行環境需允許既有測試建立臨時本機伺服器。
- 完整 Swift：95 項，0 failures／errors，13 GUI skip。包括本機 Codex CLI 的 fixture 程序測試，沒有將跳過的桌面測試當成通過。
- `git diff --check` 通過。

Python 測試覆蓋真實執行中的工具／speech lease、背景佇列與新 retry、排程重新檢查、正常及 paused 啟動、工具結果保全、串流關閉、實際 VoiceAgent 的文字／語音迴圈、喚醒詞、speaker provenance 及跨 verification scope 隔離。另以真正子程序讓主函式先返回、ThreadPoolExecutor worker 繼續等待，驗證 kernel lease 在 worker 結束前仍阻止另一個 writer。

Swift 測試實際啟動 native Python 子程序，驗證初始 paused、文字路由、舊 lease／缺少意圖拒絕、正確恢復後的新對話、面板回覆在 draining 期間仍能完成，以及逾時操作重啟後沒有重送。收件人測試涵蓋多輪維持與文字誤觸邊界。

本機記錄：`/tmp/maltose-m6-control-tests.log`、`/tmp/maltose-m6-runtime-control-tests.log`、`/tmp/maltose-m6-full-python.log`、`/tmp/maltose-m6-full-swift.log`。

## 尚未完成

以下保留本核心階段的歷史邊界。後續已有協調層接線與恢復驗證，最新狀態見 [協調層報告](session-coordination-report.md)；仍未以 fixture 取代正式服務與發行驗收。

這份報告證明的是執行權核心與 private IPC，**不是完整 `@codex` 產品流程已完成**。正式 App 尚未啟用 input routing capability，也尚未將 composer 接到 Codex；目前的 App 仍沿用原本的 Maltose 文字入口。

接下來需要把持久 conversation／收件人／pending input 狀態、workspace controller、Codex adapter、主 Agent 委派、批准／問題 UI 及完成後確認意圖接成單一 SessionCoordinator。語音路由目前有事件來源及 epoch，跨 App／runtime 崩潰的 durable outbox、去重、恢復與 human intent UI 仍須整合驗證。不能以目前的模擬或核心測試取代這些驗收。

目前沒有部署這些來源到正在使用的發行包。根目錄更名、完整 GUI／音訊／故障矩陣、真實 Codex 模型開發及 M7 最終封裝驗收仍未完成。
