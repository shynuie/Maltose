# ADR 005：單一 Maltose 產品與分開的執行程序

日期：2026-11-01。狀態：accepted；執行中。主計畫：[產品整合與 Codex](../../plans/maltose-unification-and-codex.md)。

Maltose 原生面板及原 MyAgent 主 Agent 合併成同一個倉庫與產品。原生 App 保有窗口與面板的既有模型；Python 保有 Agent、語音、身分、Memory、KDB 及工具邊界。App 管理子程序與生命週期，協調層管理訊息路由、任務和 @codex 交接；不由模型自行決定實際控制權。

來源歷史以不 squash 的雙親匯入提交 `c07b15a` 保存，兩個父提交為 `1195340` 與 `9632baf`；原始各分支保存在 `legacy-myagent/*` refs。原始碼的未提交修改另依私有 manifest 校驗後還原。來源工作樹未改動。完整備份與私有資料清單位於被忽略、權限受限的 `.cache/unification/baseline-20261101/`，不能加入 Git 或發行包。

套件與公開 CLI 為 `maltose`，舊持久身分、surface ID 等不因品牌改名任意替換。設定優先序為 CLI 明確路徑、新環境變數、舊環境變數、新設定檔、舊設定檔；設定內相對路徑跟隨設定檔位置。新舊設定檔不做隱式合併。新環境按原 lock 重建，主 Python 3.12 與 KWS Python 3.10 分離。

2026-11-01 資料已切換至 Application Support，逐筆結果見 [正式遷移報告](../verification/maltose-data-migration-report.md)。Memory 與 KDB 狀態分開、文件仍是 source of truth。正式資料遷移須停止相關 writer、備份與驗證，保留可重試的遷移紀錄；不能讓新舊 Agent 同時寫同一份資料。M0 備份校驗發現兩個既有 KWS monitor 日誌在持續附加，其餘 4820 個保全路徑與來源相符；這不構成正式資料切換或停機備份的證據。

原生 App 與受管理 runtime 的雙向傳輸優先採用標準輸入／輸出、NDJSON 訊息。這是計畫允許的本機 IPC 替代：無 listener、無公開 port，子程序連線的擁有者明確，也便於退出時偵測 EOF。未來需要獨立程序重新附著時，再增加受限 Unix socket，沿用相同版本化 request／event 合約。

M2／M3 實作補充：native runtime 在載入模型前取得設定目錄的 kernel lease，初始化期間已建立的資源使用 ExitStack 清理。KDB watcher 重用既有 CLI，由私有管線 EOF 跟隨父程序生命週期；背景服務失敗保持可見。面板模型與 MainActor 核心不變，檔案由 Python FileService 核對後只傳內容／快照，原生 transport 不直接開啟模型提供的路徑。保存的文件身分與內容 fingerprint 分開，避免舊快照的確認清掉新編輯。

批准窗口只接收審核管理器的專用 `native_approval` 事件，模型一般 UI 卡片不能冒充。批准回傳僅由原生人員確認控制發出，使用當次 runtime session 綁定既有管理器；管線持有者或輸入來源本身不等同已驗證的使用者身分。UI journal 保存事件及輸入來源，尚不宣稱還原 TaskBrain 模型歷史。去重快取只保障當次連線；跨程序恢復依後續協調層的持久狀態核對，不盲目重送。

Codex app-server 按需啟動，使用其支援的認證和 thread 生命週期。面板工具採已安裝 0.155.1 驗證的 experimental dynamicTools／item/tool/call 合約，經既有私有 stdio、controller lease、Python schema／FileService 及原生 MainActor 核心執行；不另建面板狀態或公開 listener。新 thread 明確註冊工具，舊 thread 不假裝具有新能力；不支援時回報能力錯誤，外部 MCP adapter 僅為後續相容方案。@codex 接手同一個 task／thread／worktree，Maltose 暫停自主執行但保持觀察與資料同步；Codex 結束後先確認使用者意圖，再恢復自主工作。

動態工具先保存有來源的 request，再執行，結果也先保存再回覆。call ID 與 task／turn 綁定；重複呼叫重用既有結果，缺少結果的已開始操作回報 outcome_unknown，不能自動重送。停止及交回須排空面板呼叫，runtime 的 async controller 工作亦阻止恢復。原生人員控制可授權目前任務讀取面板內容，授權僅存在當次 runtime／paused lease，不改變說話者、Memory 或 FileService 權限。

語音交回以 runtime 保管的當次輸入證據接納；App 不送回可自行宣稱的 verified TurnContext。證據綁定內容、runtime、說話者驗證世代及期限，只能使用一次；排隊後再次驗證，舊 scope 即使切回相同人也不復活。喚醒詞仍只更新身分 scope，不成為 Codex 指令。鍵盤輸入持續採 unknown 身分。

M5 核心已實作，App／主 Agent 接線仍待完成。Codex 自身保持對話與 runtime 真相；原生 task store 只保存產品映射、來源、送達／控制狀態及顯示成果。私有 stdio 傳輸不自動批准或重送寫入。回合完成先進 awaitingReview，不能直接完成產品任務或恢復 Maltose。隔離 Git 工作目錄保全當下工作內容，私有 baseline 與使用者原有未提交修改分開比對；不為建立基準而提交使用者檔案。詳細範圍與實測限制見 [Codex 核心報告](../verification/codex-integration-report.md)。

M6 執行權核心採單一 cooperative gate，將已准入的對話／模型／工具／worker／音訊活動計入 drain，不能以 UI 狀態或 task terminal 代替真實活動結束。Pause 不在 IPC reader 等待 drain；恢復需目前 owner／lease 及新意圖，並先將舊排隊工作 held。一般啟動不改掉日常排程，只有交接中的恢復才先保留舊工作。模型不能呼叫 resume。Native process lease 保留至 interpreter shutdown，避免背景工作還在收尾就釋出同一設定的寫入權。實測與尚未接線部分見 [交接控制報告](../verification/autonomy-handoff-report.md)。

後續協調層已接入原 composer／journal。產品 conversation 與 runtime session 分開；持久輸入先保存再確認接收，重放不重新套用舊收件人切換。委派工具只提交有來源的要求並關閉新動作准入，不在目前工具內等待 App。Workspace／觀察等 controller 服務只接受 paused owner／lease，較慢工作離開 IPC reader，恢復前須完成這些工作。停止意圖與完成問題各有持久交付狀態，RPC 接受不等於工具已停止或 UI 已保存問題。資料同步標示來源及截斷，秘密回答不進產品紀錄；舊主 Agent 批准也不得繞過 gate 觸發寫入。來源及尚未部署／正式驗收的範圍見 [協調層報告](../verification/session-coordination-report.md)。

回復方式：原專案及私有備份在完成驗收前保留；歷史 bundle、原生工作樹 archive、binary patch、來源完整副本及匯入 manifest 都有保存。任一資料遷移失敗時停止新 writer，按紀錄復原，不能以建立空資料庫掩蓋失敗。

主 Agent 的成果理解是 controller-only 的唯讀模型操作，屬暫停期間的觀察／確認功能；沒有工具、Memory、原 session 或舊計畫，不能恢復自主執行。依穩定訊息 ID／來源 fingerprint 保存結果，UI 保存成功與生成分開記錄；過期問題不顯示，交回 context 保留原生確認過的送達狀態。程序在模型回覆前中止時可重算此唯讀操作，寫入工具仍禁止盲目重放。

本機文字可以授權主 Agent 將已選取專案的具體開發要求委派 Codex，與使用者直接 @codex 的控制範圍一致；這不建立已驗證聲紋或個人 Memory 權限。未辨識語音及 Web 輸入不得使用此例外。其他說話者不能以 @maltose 交回目前語音任務。秘密回答只由原生安全視窗送出，一般輸入欄在新增 outbox／聊天前拒絕秘密問題答案；完整語音秘密輸入矩陣仍待驗收。

正常交回及 App 退出先透過已驗證的 Codex 背景終端 API 清理自己連線附著的任務，再讀回空清單保存收據；API 回覆成功本身不證明程序已停止。Docker 則依唯一名稱／execution 標籤核對 daemon 的完整容器 ID，移除後重查；不能只依賴 client process group 退出。未確認清理保持失敗可見，不執行全面容器清理。突然崩潰及失聯仍需獨立驗收，見 [成果理解與清理報告](../verification/main-review-and-cleanup-report.md)。

Finder 啟動的服務憑證從設定目錄 owner-only `.env` 以資料方式解析，只接受既有四種服務變數，明確外部環境優先；禁止以 shell source 重新執行私有設定。正式副本已隨 M4 停寫遷移建立，loader 不自行讀取原開發專案。

實際 KWS SDK 會直接寫入 fd 1，因此主 runtime 與 KWS worker 都先複製協定 descriptor，再將原生 stdout 診斷導向 stderr。KWS 請求／回應交易序列化、使用無緩衝管線，逾時涵蓋整個 frame；正常退出先排空收尾事件。原生模式只宣告實際連通的面板工具，不把舊 Web presentation store 當成原生面板的另一份狀態。

開發根目錄採相同 volume 的排他 rename，收據保存 Git／來源摘要及目錄 device／inode；以 runtime／task store kernel lease 保護。只更新明確的 operational path，不改寫個人記憶或 Codex 自有歷史。舊路徑暫時別名僅供現有聊天與歷史連結，產品與重建環境使用新實體根目錄；桌面專案及聊天附件完成重新定位後再退役別名。開發環境依原 lock 離線重建，原 venv 留在私有備份，App 環境不隨目錄更名搬動。詳見 [重新定位報告](../verification/project-relocation-report.md)。

實際 server 群組崩潰證明單靠 group kill 會遺留忽略掛斷訊號的工具背景程序。Codex runner 現在先建立獨立群組的 guardian，以 OS 後代／建立時間建立所有權，保留 stdout EOF lease 至收尾確認。原生傳輸核對當次 root／token；失敗保持暫停並透過現有 issue 入口保存。未 exec CLI 的啟動中止可重試，已就緒的 scope 不接受此捷徑。協定失敗後只排空有來源的收尾訊框，其他舊事件停止派發。具體證據與範圍見 [生命週期報告](../verification/codex-lifetime-report.md)。

主 runtime 的 EOF cooperative shutdown 在模型阻塞時不足以保證退出。原生入口因此新增獨立 guardian，觀察原生擁有者及 root 身分，私有控制管線只表達連線生命週期；給正常收尾時限後清理已追蹤後代。程序身分與後代追蹤抽為 Main／Codex 共用元件。一般 CLI 與 in-process bridge 不自動套用原生程序政策；此機制不取代 Docker daemon 的 execution 收據。詳見 [主 runtime 生命週期](../verification/main-runtime-lifetime-report.md)。

原生 Docker 建立與收尾改由既有 guardian 的私有 socketpair 管理。creator 在 PID 及准入狀態持久化後才可呼叫 daemon；完整容器 ID 經唯一名稱／標籤核對並落盤後，主 runtime 才能 start。正常 finish 及突然 owner loss 皆由 guard 清理，並保留同一 kernel lease 至收尾。恢復只移除已登記資源，不重播命令；未確認則關閉 gate 並阻止模型初始化。此為原生 backend 的 daemon 所有權，不擴大 FileService、網路或人員批准權限。詳見 [Docker 故障矩陣](../verification/native-docker-lifetime-report.md)。
