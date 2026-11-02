# Maltose 產品整合、主 Agent 啟動與 Codex 協作計畫

後續需求的計畫入口：[任務工作流與資訊輸出](task-workflow-and-presentation.md)。新增計畫涵蓋任務銜接、結果核對、簡短語音及成果面板預設新增；目前僅規劃，沿用本計畫成果並保留原 M0–M7 未完成驗收。

狀態：`in_progress`。2026-11-01 人員已解鎖桌面，先完成新增聊天捲動需求，再續做其餘驗收。

本文件是整合工作的主計畫，已依使用者設定的執行目標續做。保留專案已記錄的實作進度；再次啟動時先核對程式與驗證證據，依未完成項目續做。

## 可直接貼入的執行目標

依照 `/Users/Marvin/Workspace/Maltose/plans/maltose-unification-and-codex.md` 完成 Maltose 整合。先核對目前 Git、未提交修改、程式及測試證據，再從未完成項目續做，完整範圍為 M0–M7。保留既有面板 UI、已匯入的 Agent、正式資料與環境；不得重跑已完成的搬移或覆寫使用者資料。

產品採同一倉庫、分開程序：啟動 Maltose.app 時自動啟動主 Agent；主 Agent 可委派開發工作給 Codex。沿用同一聊天輸入欄，`@codex` 切入同一任務的直接互動，後續訊息持續送給 Codex；期間主 Agent 停止自主推進但持續同步紀錄。Codex 完成後，由主 Agent 根據實際成果與追加需求主動確認下一步意圖，確認前不恢復舊工作。兩個 Agent 共用既有面板狀態與操作核心，涵蓋全螢幕／非全螢幕視圖、面板生命週期、各面板能力及逐項模擬。

逐階段實作、執行適當測試並更新驗證報告，完成真實開發委派、直接互動、交回、Finder 啟動、正常退出及故障恢復驗收。需要真人、裝置或帳號的項目明列並取得實際證據；不得以模擬或跳過測試宣稱完成。保留回復方式，全部必要驗收成立後才結束目標。

## 執行時的交付與完成判定

架構採「同一產品／倉庫、分開程序」：原生 App 管理既有面板，Python 主 Agent 管理 Maltose 的推理、語音與記憶，協調層決定訊息收件人與執行權，Codex 按需處理開發任務。開啟 App 即啟動主 Agent；Codex 不必隨 App 啟動，也不預設增加第二個聊天面板。

| 階段 | 具體交付 | 通過條件 |
| --- | --- | --- |
| M0 保全與盤點 | Git／未提交修改備份、狀態與操作入口清單、當前測試基準 | 現有內容可回復，已完成成果與剩餘工作有據可查 |
| M1 整併與命名 | 單一 Maltose 倉庫、`runtime/maltose`、設定相容及可重建環境 | 保留歷史與既有功能，私有資料及環境不進版本控制 |
| M2 啟動生命週期 | App 自動啟動主 Agent、就緒／失敗／重試／退出 | 窗口不被初始化阻塞，沒有重複 writer 或遺留的受管理程序 |
| M3 共用聊天與面板 | 原輸入欄接真實 Agent，工具共用原生狀態及 ⌥⌘V 操作核心 | 全屏／非全屏摘要符合可見範圍，面板操作逐項可模擬、可讀回 |
| M4 資料與最終路徑 | 正式資料遷移收據、`Maltose` 根目錄、可回復的啟動設定 | 不覆寫既有資料，Finder 啟動不依賴舊開發目錄或互動 shell |
| M5 Codex 委派 | 有範圍的任務、持久 thread／worktree、問題／批准與成果回收 | 真實 Codex 可修改隔離專案、執行測試，重啟可恢復同一任務 |
| M6 直接互動與交回 | 黏著的 `@codex` 收件人、實際暫停、同步紀錄、主 Agent 意圖確認 | 同一聊天完成多輪交接；主 Agent 理解追加需求，確認前不恢復舊動作 |
| M7 驗收與發行 | 完整測試、故障矩陣、封裝檢查、新版 App 與驗證報告 | 真實完整流程及桌面驗收成立；跳過／未驗證項目明列 |

各階段沿用下方既有勾選與執行紀錄，不因本表重新搬移資料、匯入歷史或重做 UI。完成某一階段前，同步更新主計畫、相關 feature plan 及驗證報告；測試紀錄須對應當前版本。

產品驗收腳本：

1. 從 Finder 開啟 Maltose，原面板正常顯示，主 Agent 自動就緒並能真實回答。
2. 請 Maltose 在隔離 fixture 專案修正一項程式問題；它提供目標、限制及驗收條件並委派 Codex。
3. 使用者輸入 `@codex` 追加需求，接續同一個任務；再送一則不含前綴的訊息，確認仍給 Codex。切換觀看面板不改變收件人。
4. Codex 執行期間，Maltose 不派發自主動作，但互動與狀態持續保存；問題、批准與停止各自具有正確狀態。
5. Codex 完成修改與測試，Maltose 依實際紀錄說明成果及追加需求，主動詢問接下來的意圖。此時仍不恢復舊排程。
6. 使用者給出新意圖，核對成果與待執行動作後交回；重啟、斷線或重複事件不重做已發生的寫入，也不重複詢問。
7. 正常退出後，App 所擁有的 Agent、watcher、Codex 與背景工作完成收尾，其他獨立程序不受影響。

完整目標以 M0–M7 及上述流程共同判定。僅有面板示範、固定確認問句、模型單次回覆、封裝成功或核心測試通過，都只能記為部分證據。

## 計畫摘要與續做優先順序

保留工作樹內既有實作，依下列順序推進；歷史紀錄中的測試結果只證明當時版本，不能套用到其後尚未驗證的修改。

| 順序 | 工作 | 本階段交付 |
| --- | --- | --- |
| 1 | 核對現有程式與未提交修改，先驗證最近的持久化、輸入送達與暫停恢復變更 | 可重現的當前基準、聚焦測試與剩餘問題清單 |
| 2 | 完成單一聊天中的主 Agent／Codex 協調 | 委派、直接接手、多輪問題與批准、停止、交回、重啟恢復 |
| 3 | 接通 Codex 的共用面板能力，補齊語音交接的身分與來源驗證 | 兩個 Agent 使用同一套面板狀態與工具；語音不因重放而升級權限 |
| 4 | 驗證真實的完整任務流程 | 隔離專案的實際開發、測試、成果回收，以及主 Agent 理解追加需求後確認意圖 |
| 5 | 完成 Maltose 命名、根目錄重新定位與新版封裝 | 可從 Finder 啟動並自動啟動主 Agent 的 Maltose.app |
| 6 | 完成回歸、退出與故障恢復驗收，整理交付 | 當前版本的測試證據、資料復原方式與明列的未驗證項目 |

實作時優先查核的具體問題：

- 主 Agent 的文字輸入 RPC 收到回覆，不等於訊息已被 Agent 接納。區分排隊、接納、不確定與延後狀態，測試交接競態，避免遺失或重送。
- 完成後的確認訊息須保存成功才算送達；串流序號在崩潰／重啟後不能重用，持久化也不能讓每個小片段都拖慢聊天。
- 未被協調層確認接手的委派仍存在時，不得恢復主 Agent 的自主執行。
- 語音交回必須保留可驗證的當次說話者與來源；資料庫中保存的身分標記不能直接當作重啟後的新驗證。
- Codex 面板工具須經現有面板核心及檔案服務，另驗證安裝版本的支援能力、取消、逾時與退出收尾。
- 模型選擇使用 Codex 實際回報的清單，保存於 Maltose 自己的設定；目前任務固定其模型，不為相容問題擅改全域 Codex 設定。
- 固定的「下一步要做什麼」問句只能證明通知流程；完整驗收仍需證明主 Agent 理解使用者與 Codex 互動期間新增的要求。
- 確認問句的模型整理只讀取有來源的協作紀錄；暫停期間不得藉整理成果重新啟用自主工具。產生、保存與實際顯示為不同狀態，過期問句不得在新指令之後插入。
- 密碼或其他秘密答案必須經專用輸入流程，不能先寫入一般聊天／同步紀錄才遮蔽；另測試使用者直接在原輸入欄回答秘密問題的情況。
- 故障回報須包含原因、已完成變更與未解事項。正常交回、停止、App 退出及程序崩潰的背景工作清理分別驗證，不能用單一成功案例代替完整矩陣。

每階段結束均更新下方勾選與驗證報告。已完成的來源匯入、正式資料遷移及環境部署，先核對收據再沿用；不得為了從頭跑計畫而覆寫。

## 執行目標

將現有 Maltose 原生工作區與 `/Users/Marvin/Workspace/MyAgent` 整合成同一個名為 **Maltose** 的產品與程式碼倉庫。保留現有面板 UI、Agent、語音、記憶與文件能力；開啟 `Maltose.app` 自動啟動主 Agent，沿用現有輸入欄與聊天面板完成真實互動。

Maltose 作為主 Agent，可將開發工作委派給 Codex。使用者也能在同一個對話框用 `@codex` 接手同一項開發任務；期間 Maltose 暫停自主執行並同步互動，直到 Codex 完成後，由 Maltose 主動確認下一步意圖。

第一個可用里程碑：開啟 App → 主 Agent 就緒 → 輸入文字 → 收到真實串流回答 → Agent 能讀取並操作現有面板 → 正常退出。

完整完成條件另包含：委派 Codex → 使用者直接互動 → Codex 完成 → Maltose 同步成果並確認意圖，以及斷線、重啟與資料遷移驗證。

## 設為執行目標時的範圍

- 執行範圍為 M0–M7。第一個可用里程碑是中途驗收點，不代表整個目標完成。
- 開始或續做前，先對照當下程式、未提交修改、測試證據及下方執行紀錄；已完成的工作沿用，不重新搬移或重做 UI。
- 每階段交付可檢查的變更、測試結果與復原方式。所有必要驗收成立後才宣告完成；需要帳號、硬體或使用者操作的未驗證項目必須明列，不能以模擬結果代替。

## 下一次執行的起點

本計畫保留已記錄的進度；設為目標後先核對證據，再依以下順序完成剩餘整合：

1. **核對現況**：以實際 HEAD、未提交檔案及驗證報告建立續做清單。`1195340` 是原 UI 基準，目前已含後續匯入與改名提交；不能回退到原基準重新開始。
2. **驗證協調層接線**：沿用已接到 composer、輸入路由、主 runtime、Codex adapter 與 task store 的 `AgentSessionCoordinator`，核對剩餘能力與實際服務驗收；不重新建立聊天 UI。隔離程序驗證後，才啟用正式 App。
3. **完成互動閉環**：接上主 Agent 委派、`@codex` 多輪互動、批准／問題、停止／交回及完成後意圖確認。收件人、任務與待送訊息持久化；重啟先核對送達與執行狀態，不能盲目重送。
4. **驗證真實開發**：在隔離 fixture 專案驗證實際 Codex 認證、修改、測試、成果回收與同一任務恢復；另跑既有面板、語音、身分與資料回歸。
5. **完成命名與發行**：安全更名最終專案目錄，更新工作環境及路徑，重新封裝並驗證 Finder 啟動、退出與故障恢復。全部必要驗收通過後交付。

交付順序以依賴關係為準；M0–M7 是完整驗收清單，不要求重做已有證據支持的工作。目前來源中尚未完成接線或驗收的協調程式，不得因檔案存在就標示完成。

## 已確認的產品決策

1. 麥芽糖就是 Maltose；產品名稱移除「UI」「MyAgent」「Workspace Preview」等舊品牌用語。技術文件中仍可用 UI 描述介面層。
2. 同一產品、同一倉庫，原生 App、Python 主 Agent 與 Codex 使用各自的程序及依賴環境。
3. 延用目前聊天面板與底部輸入欄。Codex 不需要另一個聊天面板；任務詳情視圖可按需開啟。
4. `@codex` 開始一段直接互動；期間後續訊息預設送給同一個 Codex 任務，不要求每句重新標記。
5. 開啟或選取面板只是觀看，不會自行切換指令收件人。
6. Maltose 暫停的是自主推進工作；事件同步、持久化、狀態觀察與使用者控制仍正常運作。
7. 使用者與 Codex 的互動同步給 Maltose，保留真實發言者、訊息來源與任務關係。
8. Codex 完成後，Maltose 整理新要求與成果，主動確認下一步；確認前不恢復舊的排隊動作。
9. Codex 詢問問題、等待批准、失敗、中斷與任務完成是不同狀態，不能以一則回覆或單一回合結束推定整項任務完成。
10. 保留 `@maltose`／「交回 Maltose」及停止入口；交回對話不等於宣稱 Codex 已停止。

## 目前基準與既有資產

- 目前實體工作目錄：`/Users/Marvin/Workspace/Maltose`；`Maltose_UI` 暫留相容別名，供現有聊天與歷史連結續用。正式開發設定及重建環境使用新路徑；Codex 專案附件仍待桌面重新定位。
- 原 UI 基準提交：`1195340`。本次整理計畫時 HEAD 為 `28dded8`，包含歷史匯入與套件改名；另有大量未提交整合工作。執行前以 Git 實況為準，必須保留這些修改，不能回退到基準而遺失。
- 最新已驗證的面板工作：35 種程序內指令、snapshot v2、⌥⌘V JSON 模擬；49 項 Swift 測試通過，包含原生全螢幕與跨螢幕。這是先前證據，執行前仍需檢查當下狀態。
- `WorkspaceWindowManager` 管理面板與窗口；`WorkspaceLayoutState` 管理排列；各內容 model 維持既有狀態。沿用 [共用面板合約](../docs/architecture/workspace-agent-interface.md)。
- MyAgent 倉庫 HEAD：`9632baf`，存在多項已修改與未追蹤檔案，包含執行隔離、KWS 與舊整合工作。執行前重新盤點，不假設都是可丟棄內容。
- MyAgent 目錄約 3.8 GB；主套件約 2 MB，`.venv` 與 `.venvs` 合計約 2.7 GB，另有正式資料、模型、原始文件、錄音及私有設定。容量僅為盤點時參考。
- 現有 `start` 啟動文件 watcher、Agent、Web UI 並開啟瀏覽器，不適合作為原生 App 的直接啟動入口。
- 既有 MyAgent `ui/bridge.py`、事件與工具註冊入口可參考，但其舊 Host／MUP 對接不代表現在的 App 已連通，不能直接啟用當作完成。
- 來源倉庫規則見 `/Users/Marvin/Workspace/MyAgent/AGENTS.md`；遷移其程式時保留相關規則，先閱讀 `dev/README.md`、`dev/major_plan.md` 與對應 feature plan。

## 架構與責任

```text
Maltose.app
  ├─ 既有原生窗口、面板、聊天與輸入欄
  ├─ RuntimeSupervisor：主 Agent 程序、就緒、退出與故障恢復
  ├─ SessionCoordinator：訊息路由、控制交接、任務紀錄
  ├─ 主 Agent Adapter ↔ Maltose Python Runtime
  └─ Codex Adapter ↔ Codex app-server（按需啟動）
```

以上名稱為責任名稱；實作前先確認現有可重用元件，不要求為每一項新增一套服務。

建議倉庫結構：

```text
Maltose/
  apps/macos/MaltoseApp/    # 既有 AppKit／SwiftUI
  runtime/
    pyproject.toml
    uv.lock
    maltose/               # 由 myagent 遷入的主 Agent 套件
    tests/
  integrations/codex/      # Codex adapter；Swift 部分可留 App target
  docs/
  plans/
  scripts/
```

原生 App 保有面板狀態，Python Runtime 保有既有 Agent／語音／記憶邏輯。協調層保有產品任務、訊息路由與控制狀態；Codex 保有自己的 thread 與執行上下文，產品紀錄 thread 對應及顯示用事件，不維護第二份互相競爭的 Codex 對話真相。

共用本機橋接沿用已實作的私有 stdio／NDJSON；日後若需要獨立程序重新附著，再評估受限 Unix socket。合約含版本、request/session/task ID、來源、事件序號與明確錯誤；原生面板修改仍回到 MainActor。避免為整合重新啟用整套已退役的 Host。

Codex 的對話生命週期以 app-server 接入；面板工具可透過 MCP adapter 提供，兩者共用既有面板操作核心。執行時查核已安裝版本與 [官方 app-server 文件](https://learn.chatgpt.com/docs/app-server)、[官方 MCP 文件](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)，測試實際支援的合約；實驗功能必須明確標示並有相容性處理。

2026-11-01 文件核對：官方將 app-server 定位為支援認證、對話歷史、批准與串流的整合介面；[遷移說明](https://learn.chatgpt.com/docs/mcp-server) 仍標示其為 experimental、不支援 production workloads，因此本輪先作為本機試用整合，發行前重新核對支援狀態。禁止使用已移除的 `codex mcp-server`。若使用 app-server 的 `dynamicTools` 暴露面板能力，須先驗證安裝版本的 experimental capability；不支援時明確顯示能力不可用或改用外部 MCP adapter，不能悄悄建立另一份面板狀態。

## 資料、改名與回復原則

- 原始碼、Git 歷史、未提交修改與私有資料分別保全。先建立可回復的來源快照、差異與檔案清單，再進行搬移；私有快照不進入版本控制。
- UI 倉庫作為整合主線。來源歷史以子目錄匯入方式保留，來源 dirty／untracked 程式另外還原到對應位置；不把來源 `.git` 當普通子目錄複製成嵌套倉庫。
- 不將 `.env`、憑證、原始文件、記憶／聲紋／任務資料庫、模型、錄音或 Python 環境加入 Git 或 App 發行包。
- Python 套件與命令改名為 Maltose，更新 import、entry point、測試、設定及腳本；新設定優先，舊 `myagent.toml`／`MYAGENT_*` 等透過明確相容層過渡。禁止整個目錄無差別取代字串。
- 資料庫內的型別／模組引用、Agent 身分、配對、憑證及外部服務識別需逐項檢查；需要遷移時提供版本化、可重試的轉換，不以品牌改名直接覆寫。
- 既有 `.venv` 不視為可任意搬動的成品。記錄並重建可重現的主環境與 KWS 獨立環境，保留 ML／voice 依賴與現有模型；不藉改名升級依賴或更換語音方案。
- 執行資料目標為 `~/Library/Application Support/Maltose/`，Memory 與 Knowledge 索引維持分離。原始文件仍是 source of truth，模型與使用者文件可保留原位置並使用明確設定引用。
- 遷移正式資料前停止相關寫入者，建立備份並驗證數量／校驗資訊；不讓新舊 Agent 同時寫同一份資料。不要把私有內容或憑證輸出至測試報告。
- 原專案在驗證完成前保留可回復副本；完成後退役舊啟動入口與開發路徑依賴，不立即刪除備份。
- 最終根目錄更名要安排在工作環境可安全重新定位時進行；完成後確認專案附件、工具工作目錄、測試、封裝與啟動路徑。不能留下只能靠舊絕對路徑運作的成品。

## 執行階段

### M0：基準、備份與遷移清單

- [x] 重讀兩邊適用的規則，重新記錄 HEAD、dirty／untracked 狀態與現行測試入口。
- [x] 保全兩份倉庫歷史、目前修改及需要保留的非追蹤資料，建立安全的來源 → 目的地清單。
- [x] 盤點 config、entry points、絕對路徑、環境版本、模型與資料路徑；不讀出或記錄憑證內容。
- [x] 執行現行 Swift 與 Python 基準測試；若有失敗，在隔離環境區分既存問題與遷移問題，不沿用舊報告推定結果。
- [x] 建立遷移 ADR，記錄歷史匯入、資料位置、程序邊界及回復方式。

驗收：目前功能與未提交修改均可回復，遷移清單能清楚區分程式、依賴與個人資料。

### M1：單一倉庫與 Maltose 命名

- [x] 匯入 Agent 原始碼、測試及必要開發文件，保留來源歷史與未提交工作。
- [x] 保留來源倉庫適用的開發規則，整理為 runtime 子目錄規則，更新遷入後的文件連結與 feature plan。
- [x] 完成套件、CLI、App 顯示名稱、封裝名稱與設定命名；建立舊設定讀取相容與衝突處理測試。
- [x] 重建鎖定版本的主／KWS 執行環境，驗證環境及資源路徑，避免依賴原開發目錄。
- [x] 更新發行腳本，產生 `Maltose.app`；明確區分開發環境與 App 所用的受管理 runtime，Finder 啟動不依賴互動 shell 的 PATH／cwd。
- [x] 執行原生面板及 Agent 相關回歸，確認模型設定、說話者政策、執行隔離與資料格式沒有因改名改變。

驗收：新結構可建置與測試，主 Agent 可從新入口啟動，產品名稱為 Maltose，舊設定仍有明確遷移路徑。

### M2：App 管理主 Agent 啟動與退出

- [x] 新增原生 App 使用的無 Web UI 啟動入口，重用既有 Agent 初始化，不透過舊 `start` 順帶啟動瀏覽器。
- [x] App 先顯示窗口，再非同步啟動 runtime；顯示 starting、ready、failed、stopping、stopped 等實際狀態。
- [x] 建立就緒握手、合約版本檢查、啟動逾時、單實例保護、日誌及手動重試；無限自動重啟迴圈不算恢復策略。
- [x] 主 Agent、文件 watcher 與必要 worker 的擁有者及退出順序清楚；只停止本 App 所管理的程序。
- [ ] 驗證退出／崩潰／重啟不遺留重複 Agent、writer 或音訊 worker；Agent 故障時 UI 仍可操作。
- [x] 保留現有音訊設定與權限行為，不以啟動測試擅改正式語音或模型設定。

驗收：開啟 App 自動就緒；啟動失敗可看見原因並重試；正常退出沒有殘留的受管理程序。

### M3：真實聊天、runtime 事件與面板工具

- [x] 將底部輸入送入既有 Agent 的文字輸入／身分邊界，替換聊天示意資料為真實 session 與串流訊息，保留原 UI 互動與版面。
- [x] runtime 事件驅動形象、工具進度與完成／失敗狀態；不生成假的內部推理或百分比。
- [x] 為現有面板指令建立可呼叫的具名工具與 JSON Schema，測試參數及能力與既有合約一致。
- [x] 以 IPC 呼叫現有面板核心，提供新鮮的 `get_user_view`；UI 與 Agent 操作持續共用同一份面板狀態。
- [x] 將目前視圖與指定面板內容的讀取需求分清楚；需要更多內容時，不為了讀取而暗中切換使用者畫面。
- [ ] 測試 request／event 去重、亂序、斷線、版本不合、取消、重連後讀回真實狀態，避免重送造成重複面板或訊息。

驗收：使用者在同一對話框取得真實回答；主 Agent 能讀取畫面並建立／操作面板，UI 編輯也能被 Agent 讀回。

### M4：正式資料遷移與單一啟動驗收

- [x] 在隔離副本先驗證 config、Memory、Knowledge、speaker、task 狀態與路徑遷移；原始文件不被索引資料替代。
- [x] 停止正式資料寫入後，依 M0 清單備份並完成必要遷移，記錄可重試的完成狀態。
- [x] 驗證新 App 能使用既有資料與模型，不建立空白資料庫假裝遷移成功；保留資料來源與回復位置。
- [ ] 完成根目錄／專案名稱統一，重查舊絕對路徑與啟動捷徑，退役舊的日常啟動入口。
- [ ] 重新封裝並驗證簽章、Finder 啟動、冷啟動／再次開啟、失敗恢復、正常退出。

驗收：日常只需開啟 `Maltose.app`，能使用原本的 Agent 資料；不再依賴使用者另開 MyAgent。

### M5：Codex 任務接入與 Maltose 委派

- [x] 建立並驗證 app-server 傳輸、產品任務紀錄與隔離 worktree／baseline 核心；以實際 CLI 驗證中斷後重啟恢復。此項不代表下列 App／主 Agent 接線已完成。
- [x] 協調層接入原 composer／journal，加入 controller-only workspace／觀察服務、主 Agent 委派工具及人員控制來源紀錄；完成隔離程序與恢復測試。正式服務及下列完整能力仍需驗收。
- [ ] 實作 Codex adapter，按需管理 app-server、初始化、thread 建立／恢復、回合與串流事件、批准／問題、停止及故障。
- [x] 認證使用 Codex 支援的流程；不抓取其他 App 的私有憑證，不把金鑰寫入倉庫。已核對官方 account/read／login/start、0.155.1 的既有登入真實模型及隔離未登入案例；瀏覽器人員登入與正式 UI 另按 M7 驗收。
- [x] 建立 task ID、Maltose conversation ID、Codex thread ID、工作目錄／worktree、控制狀態與版本的持久對應。
- [x] Maltose 以有範圍的工作要求委派：目標、專案狀態、限制、驗收條件、相關資料與預期成果。已用既有真實 Main 模型與 Codex 在隔離專案驗證。
- [x] 獨立開發任務使用隔離工作目錄／worktree；保留既有未提交變更，同一任務交接時持續使用同一工作現場。
- [ ] 回收修改摘要、diff、測試證據、錯誤及未解事項；Codex 回合完成與產品任務完成分開判定。
- [x] 必要面板工具透過共用 adapter 暴露，不另建 Codex 私有面板狀態。已驗證 0.155.1 experimental dynamicTools，真實模型建立／編輯原生面板；中斷／重啟完整矩陣仍按 M7 驗收。

驗收：Maltose 可委派一項實際開發工作、顯示過程並讀回成果；中斷或程序重啟能恢復同一任務。

### M6：單一聊天中的 @codex 交接

- [x] 實作並驗證共用 autonomy gate、實際活動 drain、舊工作 held、owner／lease／epoch、native 控制 RPC 與收件人前綴解析。此為下列產品接線的前置核心，不代表 composer 或 Codex 協作已完成。
- [x] 協調層接上既有 App，完成 durable routed input、固定完成問句的保存確認、開始／停止競態及整個程序／store 重啟恢復測試。尚未部署與正式服務驗收，不能以此宣稱 M6 全部完成。
- [x] 輸入 `@codex` 時建立真正的收件人標記；引用、程式碼與一般文字中的字串不誤觸路由。
- [ ] 輸入欄持續顯示當前收件人／任務及 Maltose 暫停狀態；面板切換不改變收件人。
- [ ] 有目前 Codex 任務時沿用該 thread 與工作目錄；沒有時建立；多任務時使用明確選取，不隨機選擇。
- [ ] 交接先停止主 Agent 派發新動作，處理已在執行的操作並確認結果，再進入直接互動；等待期間顯示「正在交接」。
- [x] 直接互動期間後續訊息預設給 Codex，Maltose 不自動追加指令或插話；保留觀察、同步及持久化。唯讀成果確認不提供自主工具。
- [ ] 所有互動保留 author、origin、conversation/task/thread/turn ID；給 Maltose 的同步內容不能冒充使用者原話或更高優先指令。
- [ ] Codex 詢問與等待批准維持直接互動；完成／失敗／中斷分別處理，不把中斷宣稱為回復檔案修改。
- [x] 完成事件先落實狀態及成果，再喚醒 Maltose，針對最新要求主動詢問下一步；重連／重複事件不重複詢問。真實模型理解追加要求、持久快取／UI 去重、保存失敗恢復及過期確認競態均有測試；完整故障矩陣仍按 M7。
- [ ] 使用者確認意圖後重新檢查舊計畫與待執行動作，才允許 Maltose 恢復自主執行。
- [ ] 提供 `@maltose`／「交回 Maltose」及停止控制，保留仍在執行的 Codex 狀態，禁止互相衝突的並行寫入。

驗收：使用者可以自然地與 Codex 多輪互動，Maltose 看得到過程但保持暫停；完成後主動確認並理解新的工作方向。

### M7：完整回歸、封裝與交付

- [ ] 執行各階段聚焦測試及相關完整 Swift／Python 套件；實際執行原生全螢幕與跨螢幕測試。build 11 的 Swift 141／Python 393 無失敗／skip 且有兩個實體顯示器；後續 build 14 已完成相應核心回歸（143 Swift／408 Python），新版桌面與真人驗收仍未完成。
- [x] 在隔離 fixture 專案跑真實 Codex 開發流程，不修改正式使用者專案來充當測試。
- [ ] 驗證 app-server 不可用／未認證、Agent 啟動失敗、socket 斷線、App 重啟、重複事件、任務等待輸入與取消等情況。
- [ ] 驗證既有聲紋／語音／Memory／KDB／檔案與命令隔離；涉及真實麥克風及模型服務的驗收單獨記錄。
- [ ] 更新 README、設定／搬移說明、啟動與復原方式、架構及驗證報告，將舊 Host 與 MyAgent 文件明確定位為歷史或相容資料。現行架構與 roadmap 入口已核對更新；最終發行版本及剩餘驗收結果仍需同步。
- [ ] 檢查發行包與 Git 變更沒有包含私有資料、憑證、環境或模型快取；執行 `git diff --check`。
- [ ] 產生新版 `Maltose.app` 並完成實際啟動驗收，記錄版本、測試數、跳過原因及仍需人工完成的項目。

## 交接狀態與單一執行者規則

建議產品控制狀態：

```text
maltose_active → handing_off → codex_direct
codex_direct → codex_waiting_for_user → codex_direct
codex_direct → reporting_to_maltose → awaiting_user_intent
awaiting_user_intent → maltose_active 或 codex_direct
```

失敗、中斷與斷線另記錄 task／runtime 狀態，不混同於「完成」。事件可以來自兩個 Agent，但同一工作範圍的自主寫入指揮者由協調層唯一決定。交接中收到的新訊息必須可追蹤，不得遺失、重送或錯送。

「暫停 Maltose」不能凍結協調層或 IPC，否則無法接收 Codex 完成、停止與恢復事件；也不能在主 Agent 的舊回合仍執行工具時只改 UI 標籤。

具體交接規則：

1. 收到有效 `@codex` 後，先持久化交接請求與訊息 ID，關閉 Maltose 新的自主工具／排程派發，再等待已派發的操作結束或明確取消；不能阻塞承載面板回覆的 IPC reader。
2. 確認執行權釋出後才將訊息交給同一個 Codex 任務。交接中的追加訊息保存在佇列；失敗時顯示原因並保留草稿，禁止兩邊各執行一次。
3. 鍵盤與語音經同一個收件人路由。直接互動期間的語音不能繞過協調層進入 Maltose 自主回合；原有身分與授權判斷仍然有效。
4. 將產品任務狀態與 Codex 回合狀態分開儲存。問題、批准與單一 `turn/completed` 均不足以自行判定整項產品任務已完成；先依任務驗收與明確成果判定。
5. 結果同步採保留來源的紀錄與必要摘要。Maltose 主動確認時要涵蓋使用者直接交給 Codex 的新要求；確認事件須可去重，重啟後不能反覆詢問或自動恢復過期動作。
6. Codex 尚在執行時選擇 `@maltose`，可切換對話收件人，但同一專案的衝突寫入仍須等待停止確認或執行權交接；停止不代表撤銷已完成的修改。

## 必跑驗收場景

| 場景 | 通過條件 |
| --- | --- |
| App 冷啟動 | 窗口先出現，Agent 狀態可見，就緒後可以真實聊天；無額外瀏覽器或重複 Agent |
| 既有 UI | 面板移動／全屏／側欄／編輯／現行 36 種共用工具及 ⌥⌘V 測試保留，內容與物件不因整合重建 |
| 舊設定與資料 | 模型、記憶、聲紋及原始文件仍可使用，來源可追溯，遷移重跑不重複或覆寫 |
| 自主委派 | Maltose 委派 fixture 開發任務，Codex 完成後回傳可檢查的修改與測試 |
| 直接接手 | 使用者 `@codex` 補充需求，沿用原 thread／worktree，Maltose 停止自主動作 |
| 多輪互動 | Codex 詢問後使用者可直接回答，訊息不被送回 Maltose 執行 |
| 回報確認 | Codex 完成後 Maltose 正確提及期間的新要求，主動確認；確認前不恢復舊動作 |
| 邊界狀態 | 問題／批准／失敗／中斷不被當成完成，停止不承諾撤回已發生的外部效果 |
| 重啟與斷線 | 恢復原任務與收件人狀態，先核對真實執行情況，不盲目重送寫入或重複詢問 |
| 正常退出 | 資料完成保存，受管理的 Agent／watcher／worker 有序結束，未影響其他獨立程序 |

## 測試與執行紀律

- 先基準、再聚焦、再相關完整套件；測試只使用隔離資料與 fixture。現有問題要以可重現證據區分，不藉移除測試、放寬身分或安全政策取得通過。
- 優先以 fake runtime／fake app-server 驗證事件與路由，再跑實際程序及整合；正式模型／語音與真實 Codex 驗收獨立記錄。
- 沒有可用帳號、服務、桌面或硬體時，完成不依賴它的工作並明確列出未驗證項目；模擬通過不等於真人／正式服務通過。
- 建立階段性且可檢查的變更，保留 unrelated 修改；不在遷移中丟棄、重設或提交私有檔案。
- 先完成必要的實作、測試與可回復步驟，不為例行命名或低風險實作選擇反覆要求確認。遇到真正缺少的憑證、權限或可能覆寫不明使用者資料時，再指出具體阻礙。
- 各階段更新本計畫與對應 feature plan／ADR，記錄結果。正式目標只有在完成條件成立時才算完成。

## 非本輪目標

- 重做面板 UI、替換既有 Agent 框架、改換語音／模型方案。
- 公開網路上的 Agent 平台、多使用者帳號系統、通用插件商店。
- 預設新增第二個 Codex 聊天面板、任意 DOM／媒體操作或磁碟刪除工具。
- 將 Codex 全部內部對話持續塞入 Maltose 模型情境；保留完整同步紀錄，依事件提供必要增量與摘要。
- 在未完成遷移驗證時刪除來源專案或備份。

## 執行目標提示詞

> 按照 `/Users/Marvin/Workspace/Maltose/plans/maltose-unification-and-codex.md` 完成 M0–M7 的全部必要工作。先核對當下程式、Git 修改、已完成勾選及驗證報告，保留並沿用已有成果，從未完成項目續做；已完成的匯入、資料遷移與環境部署不得重複覆寫。將產品與最終專案目錄統一為 Maltose，開啟 App 自動啟動主 Agent；沿用現有 UI、對話框、語音、身分、Memory、KDB 及共用面板狀態，完成 Codex 委派與 @codex 多輪直接互動。交接時確實暫停 Maltose 自主執行，同步互動並保留來源，Codex 完成後由 Maltose 主動確認下一步，確認前不恢復舊動作。保全歷史、未提交修改及私有資料，執行測試、故障恢復與真實服務驗收，封裝 Maltose.app，更新計畫及報告。完成條件是整個「啟動 → 委派 → 直接接手 → 完成回報 → 確認意圖」流程及 M7 驗收成立；中途里程碑不能當作整個目標完成。模擬、真實服務與尚未驗證項目分開報告。

## 執行紀錄：2026-11-01

- M0 已完成。保全 Git bundle、工作樹與差異；匯入 236 個來源路徑並校驗；來源工作樹狀態不變。資料備份 4822 路徑中，兩個既有 KWS monitor 日誌仍在附加，其餘相符；正式停寫與資料切換仍屬 M4。私有 manifest 留在忽略的 `.cache/unification/baseline-20261101/`。
- M1 的匯入、改名與環境重建已完成；受管理 runtime 封裝仍待與 M2 驗證。匯入提交 `c07b15a` 保留雙親歷史，套件為 `runtime/maltose`；主 Python 3.12.10 與 KWS Python 3.10.19 依原鎖重建。設定路徑與新舊名稱相容測試通過。根目錄更名仍按 M4 執行。
- 修改前桌面 Swift 49 項通過。Python 285 項有 2 failures／1 error／5 skipped；三項失敗在原提交 HEAD 的隔離副本重現。修正測試缺少已驗證身分的前提並增加拒絕檢查，正式身分政策不變。
- 新主環境 Python 289 項，0 failures／errors、5 Docker integration skipped；改名後 Swift 桌面 49 項全數通過。KWS 真實模型通過 READY／health／靜音 PCM／reset，未使用麥克風。
- M2／M3 已實作 native stdio 入口、supervisor、kernel lease、資源／watcher 退出管理、既有聊天串流／journal、36 種面板工具及人員批准回傳。App 受管理環境與正式設定尚未部署，不能宣稱日常開啟已能使用原資料與正式模型。
- 本階段完整 Python 314 項，0 failures／errors、5 Docker integration skip；Swift 原生桌面 68 項全數通過、無 skip。實際子程序包含 Echo、腳本模型經既有 TaskBrain 呼叫原生面板、重複請求去重、父程序死亡與真實空白 KDB watcher 清理。模型回答 fixture 不代表正式模型或真人語音驗收。
- 已產生包含 Python 原始碼資源的 Maltose.app，strict ad-hoc 簽章通過；正式環境部署與 Finder 冷啟動仍待 M4。細節及限制見 [原生 runtime 整合報告](../docs/verification/native-runtime-integration-report.md)。
- 已補上 M4 所需的私有 `.env` 資料載入與權限檢查，來源的兩個服務設定解析通過且沒有輸出值。下一步部署受管理主／KWS 環境，並完成停寫後的正式設定與資料遷移；M5–M7、Codex 協調及整體完成驗收仍未完成。

- 發行包以獨立 cwd 成功匯入包內 runtime；133 個檔案通過私有憑證／資料庫／環境／模型目錄檢查，麥克風用途說明存在。Docker client 可執行，但本機 daemon 未連通，5 項容器整合仍未驗收。

## 執行紀錄：M4 正式切換

- 主 Python 3.12.10 與 KWS Python 3.10.19 的 App 專用環境已依原 lock/hash 在 Application Support 重建。主環境無 editable checkout，KWS 保留獨立環境。
- 隔離演練與正式切換均核對 4 個 SQLite／43 筆記錄、4 張 LanceDB 表／221 筆記錄及 4 份原文；4 筆文件與 3 筆 queue 路徑已更新，其餘資料保留。正式收據 ID 為 `6c1f4dd2503c4506884185043dbcc006`，私有備份不進 Git／發行包。
- 舊 KWS 診斷排程已保全、停用並驗證退出；舊 App 發行包移入忽略的保全區，原 MyAgent 專案仍可回復。以明確禁止舊專案讀取的 sandbox 驗證新 runtime 可冷啟動。
- Finder 已能啟動正式資料版本；已觀察到真實語音、既有模型串流回答及共享面板操作。實際測試找到 KWS stdout／訊框問題，已隔離原生診斷、序列化交易並補上整體逾時，修正後多輪可回待機。
- 本階段 Swift 69 項桌面測試全通過，Python 330 項無失敗、5 Docker integration skip。根目錄更名與其後重新定位、M5–M7 及整體最終驗收仍未完成。詳見 [正式遷移報告](../docs/verification/maltose-data-migration-report.md)。

## 執行紀錄：M5 核心

- 已完成私有 stdio CodexConnection、CodexAdapter 與 CodexTaskStore；保存 task／conversation／thread／worktree、控制狀態、訊息來源及送達狀態，區分回合結束與產品任務完成。
- 使用本機 Codex 0.155.1 schema 及實際程序核對初始化、建立／中斷回合、退出、重啟與同 thread 恢復。測試使用隔離 localhost fixture provider，不代表真實模型完成開發或正式帳號驗收。
- 已完成精確授權 Git 根目錄的隔離 worktree／工作內容 baseline 核心；原 index／HEAD／工作檔不被修改，結果相對接手當下內容產生，保留 binary／hash／有上限 diff。Git ignored 私有資料不匯入，來源競態保留 incomplete attempt。
- Codex Swift 聚焦 21 項及 workspace Python 聚焦 9 項全數通過；完整 Swift 90 項無失敗、13 GUI skip；完整 Python 340 項無失敗、5 Docker integration skip。`git diff --check` 通過。既有排程測試改以確切的背景 task terminal 等待，正式排程行為不變。
- 核心尚未接到正式 App 的 composer／語音路由與主 Agent 委派，Maltose 的執行權暫停、人員批准／問題 UI、面板能力接入、真實模型開發與 M6–M7 仍未完成；根目錄仍為 Maltose_UI。新增來源尚未部署到正在使用的 App，不把本輪當成完整目標達成。詳細範圍見 [Codex 核心報告](../docs/verification/codex-integration-report.md)。

## 執行紀錄：M6 執行權核心

- 主 runtime 的工具、模型／對話、排程／TaskManager、通知及語音輸出使用同一個 autonomy gate。暫停先關閉派發，再等待真實活動結束；IPC reader 不阻塞等待工具，面板回覆可正常完成。
- 新 native pause／resume／snapshot 及 RuntimeSupervisor async result 介面驗證 owner／lease、epoch、version 與 in-flight；恢復先將舊工作 held。一般啟動保留原排程，交接中的重啟才先保留舊工作待重新檢查。
- 中斷保全已完成工具結果及部分串流。輸入路由事件保留來源與 speaker scope，舊輸入 deferred；喚醒詞不送 Codex，也不在 paused 時清掉主 Agent context。已修正 verification scope 改變時沿用短期私有歷史的問題。
- Native kernel lease 延伸至 interpreter shutdown，實際子程序證明舊 worker 收尾時仍不能取得另一個 writer。控制 API 不暴露為模型工具。
- 聚焦 Python 13 項／Swift 5 項全數通過；完整 Python 353 項無失敗、5 Docker skip；完整 Swift 95 項無失敗、13 GUI skip；`git diff --check` 通過。詳細範圍見 [交接控制報告](../docs/verification/autonomy-handoff-report.md)。
- 尚待 SessionCoordinator 把持久收件人／輸入、主 Agent 委派、workspace、Codex、人員批准與完成後意圖確認接到原 composer；跨程序輸入 outbox 與整體恢復未驗收。正式 App 尚未啟用 input routing，也未重新封裝；全目標及 M6–M7 仍持續進行。

## 執行紀錄：M5／M6 協調層接線

- `AgentSessionCoordinator` 已接原 composer／journal／native runtime。持久收件人、待送／待確認輸入、主 Agent 委派工具、開發專案／task／thread／worktree、問題與批准 UI、完成後固定確認問句使用同一協調流程；原面板 UI 沿用。
- 回合完成與產品完成仍分開；停止意圖持久化，開始回合尚未回覆時不丟失停止，也不自動送出追加需求。完成問題僅在成功保存聊天後確認交付，重放維持同一訊息 ID。
- 主 Agent 的批准入口也納入 gate；Codex 互動紀錄保留來源，秘密回答遮蔽。同步包含未完成回覆，提供有來源且標示截斷的摘要，不改變聲紋／Memory 身分。
- 聚焦 collaboration Python 8 項通過；最終完整 Python 361 項無失敗、5 Docker skip；完整 Swift 桌面與本機 Codex 113 項全通過、無 skip。最初的並行回歸出現時序失敗，聚焦及後續完整重跑通過，保留在報告中，不當作已根治。`git diff --check` 通過。
- 正式 Codex 認證／模型開發、主模型交回後的理解、Codex 面板 MCP、完整人員互動與真人語音矩陣、根目錄更名及最終封裝尚未完成。本輪來源未重新部署，不把既有發行包算成新流程的驗收。詳見 [協調層驗證](../docs/verification/session-coordination-report.md)。

## 執行紀錄：語音交回與 Codex 共用面板

- 已驗證真實 Codex 帳號／模型完成隔離 calculator 修改、三項 unittest、來源不變及交回。另由真實模型實際呼叫兩個動態工具，建立原生筆記面板並寫入指定文字，專案無修改；使用 gpt-6-astra，沒有自動批准人員請求。
- 模型清單、Maltose 自己的選擇及任務固定模型已接上；明確不可用的選擇不自動替換，也不擅改全域 Codex 設定。
- 36 種面板工具經 experimental app-server、現有 native bridge／FileService／MainActor 核心執行；call ID 持久去重、衝突與過期 turn 拒絕、不確定結果不重送，停止／交回等待收尾。私有讀取使用當次任務擁有者或原生人員的 task／runtime／lease 授權，不升級 Memory 身分。
- 語音交回保留 runtime 保管的單次驗證證據；重啟、內容不符、120 秒過期、scope 改變及重送均拒絕。排隊後身分改變則 deferred、不呼叫模型；鍵盤輸入仍 unknown。喚醒詞更新 scope 而不成為開發指令。
- 修正主 Agent 入列／接納混淆、交接競態的來源回覆、完成問句 journal 同步、跨重啟序號預留與未確認委派的恢復拒絕。已加入對應真實程序與 store 測試。
- 完整 Python 366 項無失敗、5 Docker skip。完整 Swift 桌面／真實 Codex 124 項、無 skip，但全螢幕同一案例有 7 個失敗斷言，其餘通過；最終協調／adapter／互動聚焦 35 項全通過、無 skip。`git diff --check` 通過。
- 全螢幕診斷為實際 App 未取得前景啟用／key window；目前等待啟用後續做，不放寬原生 Space 斷言。系統啟動入口實驗仍重現，已撤回無效實驗。此驗收未完成。
- 正式主模型理解與主動確認、真人語音／多任務／故障及程序清理完整矩陣、根目錄更名、新版封裝與最終發行仍待完成；來源未部署。詳見 [語音與共用面板報告](../docs/verification/voice-handoff-and-shared-panels-report.md)。

## 執行紀錄：真實 Main 成果理解與背景清理

- 真實 Main 與 Codex 已完成隔離專案的自然語言委派、calculator 修正、三項測試、人員直接追加 docstring、Main 理解並確認新意圖的閉環。本機文字保留 unknown 身分，沒有提升 Memory 權限。
- Main 成果確認使用獨立唯讀模型情境、結構化輸出、持久快取及穩定 ID。新要求與工具回報分開保留，生成與原生聊天保存分開標示，失敗／過期確認不恢復自主動作。
- 秘密問題使用安全視窗，一般輸入欄在落盤前拒絕；公開問題沿用同一回合。其他說話者不能藉 @maltose 交回語音任務；Codex 失敗原因同步，不生成完成確認。
- Codex 實際背景終端於交回／App 退出前透過 scoped list／clean／重查收尾。Docker 另修正 timeout 後 daemon 容器清理，TERM-ignoring 父子 heartbeat 停止，獨立容器不受影響；不代表突然崩潰的完整矩陣已完成。
- 最新完整 Python 378 項，0 failures／errors／skip，包含五項實際 Docker 整合。最新完整 Swift 137 項、0 failures、15 GUI skip；真實雙模型流程及背景清理再次通過。完整回歸發現送達 metadata 造成同 ID 快取衝突，已修正並驗證重放；另加入明確任務選取與失敗後重試，保留失敗及修正紀錄。
- 試用包曾建立 0.7.0／build 8，141 個 bundle／125 個 runtime 檔案，當時來源 hash、簽章、獨立 cwd 匯入及兩項服務憑證掃描通過。後續修正仍須重新封裝；新版未以正式資料啟動，不當作 Finder 驗收。
- 最新修正已重新封裝為 0.7.0／build 9：141 個 bundle／125 個 runtime 檔案，來源 hash、strict 簽章、獨立 cwd 匯入及兩項憑證值掃描通過，沒有啟動正式 Agent／麥克風。保留 build 8 私有備份，原生／runtime 來源與執行檔 hash 見 [驗證結果](../docs/verification/main-review-build9-results.json)。
- Mac 目前鎖定，原生工具已確認無法自動解鎖，等待人員解鎖再驗收全螢幕／真人語音。這不證明先前間歇桌面失敗的唯一原因。多任務／故障矩陣、根目錄重新定位與最終交付仍未完成，詳見 [成果理解與清理報告](../docs/verification/main-review-and-cleanup-report.md)。

## 執行紀錄：實體根目錄重新定位

- 實體主倉庫已搬至 `/Users/Marvin/Workspace/Maltose`，413 個來源檔案、Git HEAD／工作樹狀態在搬移時保持一致；未提交內容及忽略資料均保留。舊路徑暫留相容別名，未重跑正式資料匯入。
- 正式 `taskbrain.codex_cwd` 已改用新根目錄，其餘設定語意維持一致，原設定與收據保存在私有 migrations 目錄。原開發 venv 保全後依鎖檔離線重建，Python 3.12.10／117 個套件版本不變；App 專用環境不變。
- 搬移工具九項隔離驗證及搬移前／後完整 Python 387 項均通過，無 skip。搬移後使用全新編譯快取的 Swift 137 項無失敗，20 skip（15 桌面、五項本輪未開啟真實模型服務）；不重複宣稱未執行的測試。
- Codex 桌面專案名稱、附件及目前聊天的執行環境仍需重新定位，舊路徑別名暫不移除；最終 Finder／語音／全螢幕與故障矩陣仍未完成。詳見 [重新定位報告](../docs/verification/project-relocation-report.md)。

- 搬移後重新封裝 0.7.0／build 10，舊路徑別名暫時移除期間，來源比對、strict 簽章、獨立 cwd 匯入及兩項憑證掃描通過，之後還原別名；沒有啟動正式 Agent／麥克風。詳見 [build 10 結果](../docs/verification/relocated-build10-results.json)。

## 執行紀錄：Codex server 崩潰收尾

- 實際 Codex 0.155.1 的 server 群組 SIGKILL 會留下另一群組、忽略 SIGHUP 的背景程序。實驗以建立時間核對身分完成善後，保留失敗證據；未把後來的清理當成原測試成功。
- 新增獨立 guardian、OS 後代／建立時間追蹤及私有 EOF 收據；相同 server 崩潰、執行中工具的宿主崩潰及不重送的同 thread 恢復均通過。原生只向 kernel 核對過的自有群組送訊號；清理失敗保持暫停並保存 issue，啟動前失敗可修復後重試。
- 截斷／17 MiB 超限資料後仍排空可信收據，其他舊事件停止處理；parser 只掃新片段，16 MiB 限制保留。Python 六項聚焦及完整 393 項通過、無 skip。最終 Swift 141 項無失敗、15 GUI skip，真實 Main／Codex 流程亦通過。
- 所有 lock 套件版本及 App main／KWS 環境版本保持不變，只補上既有 psutil 的明確 extra。build 10 早於本修補，須更新 trial package；原生 App 全體崩潰與桌面／語音完整驗收仍未完成。詳見 [生命週期報告](../docs/verification/codex-lifetime-report.md)。

- 修補版已封裝為 0.7.0／build 11，142 個 bundle／126 個 runtime 檔案來源相符；舊別名不存在時仍通過簽章、受管理 Python 的獨立匯入與兩項憑證值掃描，之後還原。完整 Swift 141 項、0 失敗、15 GUI skip；Python 393 項、0 失敗／skip。詳見 [build 11 結果](../docs/verification/lifetime-build11-results.json)。

## Build 11 解鎖後的桌面驗收進度

2026-11-01：當前來源完整 Swift 回歸 141 項、0 failures、0 skip，包含原生全螢幕、兩個顯示器可用時的跨窗口移動及真實 Main／Codex 面板流程。正式 build 11 已從 Finder 啟動、原主 Agent 自動就緒，原聊天輸入收到真實模型回覆；既有音訊只有一條 active stream。啟動前 3,407 檔備份校驗全部相符。真人語音、人員專案附件重新定位及正式退出／重啟／全體崩潰仍待驗收，已提出具體人員測試。早先鎖定與 GUI skip 是歷史狀態，不能再作為目前桌面狀態。詳見 [當前桌面驗收](../docs/verification/build11-desktop-acceptance.md)。

## 主 runtime 忙碌斷線修補

桌面重新鎖定後改查隔離程序，重現原 native EOF 無法結束阻塞模型呼叫的缺口。新增 App-owned 主 runtime 獨立 guardian、私有 EOF 控制管線、PID／建立時間及跨群組後代核對；和 Codex 共用程序追蹤。新增四項真實子程序故障測試及原有程序／IPC 聚焦共 21 項通過；完整回歸與 build 12 封裝進行中。正式 build 11 仍開啟等待人員測試，未以新版來源覆蓋其 bundle；Mac 目前再度鎖定，已請人員解鎖。詳見 [忙碌斷線驗證](../docs/verification/main-runtime-lifetime-report.md)。

主 runtime 修補完成本輪回歸：Python 397 項無失敗／skip；Swift 141 項無失敗、15 GUI skip。build 12 在獨立 cache 位置通過 144／128 檔來源比對、簽章、受管理 interpreter 匯入與憑證掃描；正式 build 11 未被覆蓋。另以真實 Docker 的 TERM-resistant 容器重現 root 群組崩潰後 daemon 仍寫入的缺口，probe 回傳 1，已精準清理 fixture；此項必須修正，不以既有 timeout finally 通過取代。下一步完成啟動前資源登記、守護清理與不確定／重啟處理，再進行 GUI 與正式新版驗收。詳見 [build 12 結果](../docs/verification/main-lifetime-build12-results.json)。

## 原生 Docker 崩潰清理修補（build 13）

已修復前輪 TERM-resistant 容器在 root 群組崩潰後繼續寫入的缺口。原生 guardian 接管 stopped-container 建立、PID／准入 barrier 與完整 ID 的持久化；主 runtime 只啟動已登記容器，kernel lease 延伸至 daemon 清理。未確認時關閉 gate 並失敗，重啟先清理且不重播。七項真實故障／同目錄恢復矩陣通過，含 API 失聯後的啟動阻擋與旁觀容器保全。聚焦 44 項、完整 Python 408 項無失敗／skip；Swift 141 項無失敗、15 GUI skip。獨立 build 13 的 145／129 檔來源、簽章、受管理匯入與憑證掃描通過；dist 的 build 11 未被覆蓋。正式 GUI、真人及全 App 故障驗收仍待人員解鎖，目標未完成。詳見 [容器生命週期驗證](../docs/verification/native-docker-lifetime-report.md)。

## Codex 認證失敗及不可用流程（build 14）

已以真正 0.155.1 app-server、空白 home／file-only 認證完成未登入驗證：先確認 account=null 才送要求；Maltose 維持 paused，原輸入保留，重試不重複訊息或建立 task。執行檔缺失後亦可用明確新 @maltose 意圖交回，舊 Codex 要求 deferred、原檔不變。修正未登入訊息指向舊選單的文字，改為現有 Codex 選單。完整 Swift 143 項無失敗、15 GUI skip；文字修正後兩項聚焦通過。獨立 build 14 的 145／129 檔來源、簽章、受管理匯入與憑證掃描通過；Python 與 build 13 相同，沿用 408 項及七項 Docker 故障證據。正式 App 仍未切換，GUI／真人／專案附件驗收持續待解鎖；整體目標仍 in_progress。詳見 [認證故障報告](../docs/verification/codex-auth-failure-report.md)。

## 文件入口與歷史方案整理（2026-11-01）

已將架構入口更新為既有原生面板、受管理主 Agent、協調層與 Codex 的實際責任；roadmap 改指現行產品整合，舊 Host／MUP feature、協定及使用方式明確標為歷史／相容資料。Python 架構保留匯入基準並說明現行命名，開發入口區分 App 的正式資料與 CLI 相容日誌。不更動執行程式、資料或套件；10 份文件的 79 個本機連結及 git diff --check 通過，沒有重跑應用測試，不將既有測試結果算為重新執行。M7 最終文件交付仍須等待新版正式驗收結果。

## 執行狀態：等待桌面與人員驗收（2026-11-01 15:21）

前輪完成現行／歷史架構文件整理，79 個本機連結及差異檢查通過。本輪再次以桌面工具確認 Mac 鎖定且無法自動解鎖；本機 Codex 專案仍為「麥芽糖UI」，路徑仍為 Maltose_UI。此條件已跨多輪持續存在，現在沒有已知可替代剩餘正式驗收的獨立工作；整體目標受阻，沒有宣告完成。

核對正式 dist 仍為 0.7.0／build 11，該 App 程序仍在執行；獨立 trial 為 build 14，未覆蓋執行中的 bundle，也未宣稱正式驗收。既有 143 項 Swift、408 項 Python 的證據及版本限制維持，這輪沒有重跑測試。

續做所需條件：

1. 人員解鎖 Mac，讓新版正式 App 的 Finder 冷啟動、退出／重啟、完整協作 UI 及 App 故障矩陣可以實際驗收。
2. 人員完成真人喚醒、收音及語音回覆的測試，並配合身分／中斷／裝置案例。模型或靜音 PCM 成功不能代替聽感驗收。
3. 人員將 Codex 本機專案名稱設為 Maltose、路徑設為 `/Users/Marvin/Workspace/Maltose`，重新定位目前聊天的執行環境。工具沒有專案路徑修改能力，電腦操作也禁止控制 Codex 本身；不繞過限制修改私有設定。舊路徑別名暫留，等重新定位確認後再退役。

條件具備後恢復完整 M0–M7 目標，先核對現況與執行中的正式版本，保全新產生資料及 native-executions 收據，再完成新版切換與所有未勾選驗收；不得重做遷移或把舊版桌面證據算到新版。

## 新增需求：聊天追蹤與閱讀保護（2026-11-01）

使用者要求在進一步產品驗收前先加入：所有聊天模式於送出／收到訊息時自動捲到底部，除非過去 30 秒內手動捲離底部。實作沿用原聊天與 scroll view，同時追蹤串流內容增長；以最後一次實際手動捲動重新計時，回到底部立即恢復，逾時後下一次訊息更新恢復。每個對話保留自己的閱讀狀態，模式切換不清除；純排版／程式捲動不建立手動意圖。原先桌面鎖定條件已解除，舊受阻紀錄保留為歷史，不代表目前狀態；本機專案重新定位與其他真人驗收仍需確認。

目前新功能聚焦 10 項通過，包含實際 NSHostingView 的 grid／focused／sidebar 版面、串流增長、手動保護、模式切換及恢復；完整 Swift 回歸與新封裝尚在進行，不能提前宣告完成。

### 聊天修補交付與剩餘驗證

0.7.0／build 15 已部署並從 Finder 啟動，主 Agent 就緒且真實文字回答會追蹤至底部。新功能聚焦 10 項通過；完整 Swift 148 項有 2 skip 及 1 項全螢幕案例的 4 個失敗斷言，兩項 skip 已另行補驗通過，全螢幕單獨重現仍失敗。不能宣稱完整回歸通過。實際 wheel 因 CUA 多螢幕位置錯誤未送出，手動規則的原生通知／clip 測試與真人手勢驗收分開記錄。停寫備份 4,444 檔校驗相符，舊版及正式資料仍可回復；後續補齊主計畫驗收。詳見 [聊天捲動報告](../docs/verification/chat-autoscroll-report.md)。
