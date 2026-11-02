# 主 runtime 忙碌斷線與程序守護

日期：2026-11-01。狀態：build 12 歷史證據；其 Docker daemon 缺口已由後續 build 13 修補，正式 GUI 驗收仍在進行。

## 問題與修正

隔離重現確認：原生主 Agent 正執行受控的阻塞模型呼叫時，關閉擁有者 stdin，8 秒後仍未退出。原先 EOF 僅設定 cooperative shutdown；它不會中斷已在執行的模型或阻塞 executor。既有測試只驗證閒置 EOF，不能涵蓋這個情境。重現結果保存在私有 cache，沒有使用麥克風或修改正式 App。

`maltose.desktop` 現在於模型初始化前建立獨立程序群組的 guardian。守護同時核對主 runtime 與原生擁有者的 PID／建立時間，並接收一條不含使用者資料的私有控制管線；原生 IPC EOF 或輸出斷線會關閉此管線。一般 CLI 及純程序內 bridge 不安裝這項原生擁有者政策。

斷線先給正常的資料庫／音訊收尾兩秒，超時後對已核對的存活後代先 TERM、再 KILL；子程序移至其他群組或被重新掛接後仍維持已觀察到的所有權。guard 本身位於獨立群組。失去 guard 時主 runtime 停止，以非成功狀態回報；不能安靜地繼續不受保護的工作。主 Agent 與 Codex 共用 `runtime/processes.py` 的程序身分追蹤，沒有建立第二套相互衝突的所有權判定。

這只能管理 OS 已觀察到的後代，不宣稱隔離任意外部 daemon；Docker 仍使用既有的唯一 execution 標籤、完整容器 ID 核對與清理收據。實際原生 App 全體崩潰及真人語音矩陣仍另行驗收。

## 已通過的聚焦驗證

21 項程序／IPC／所有權測試通過，12.665 秒，日誌 `/tmp/maltose-main-lifetime-final-focused.log`。新增四項真正子程序故障測試：

1. 忙碌模型期間 stdin EOF：清理忽略 TERM／HUP 且位於其他群組的 worker，kernel lease 釋放；同一資料位置可重啟，沒有重播被中斷的工作，其他獨立程序仍存活。
2. 宿主程序 SIGKILL：刻意保留上游 stdin 的寫入端，驗證守護靠宿主身分獨立偵測，而非只靠 EOF。
3. 主 runtime 整個群組 SIGKILL：外部群組的 worker 及守護均停止。
4. guardian 被殺：主 runtime 停止，受控案例回傳 70，不能回報正常完成。

首次接線曾漏將 callback 傳入 CLI 的 ExitStack 內層，造成聚焦失敗；已補上並重跑。完整回歸另外指出一個 monkeypatch 的舊 CLI 替身未接受新增 keyword，已更新替身並維持 executor 排空前不得釋放 lease 的原斷言；聚焦通過。這些失敗保留在對應日誌，不視為成功證據。

## 依賴與發行

新增 `desktop` extra，仍使用已存在的 psutil 7.2.2；離線解鎖解析 164 個套件，逐項比較所有 name/version 完全相同。相對本輪前鎖檔，只增加 Maltose 的 desktop extra 與對應 metadata；沒有升級模型、語音方案或其他依賴。setup scripts 一併匯出 desktop extra；正式環境仍由 kernel lease 保護，目前正式 App 活著時不執行環境重建。

build 11 已完成 Finder 啟動及真實文字回覆，是修補前的正式 App。修補版規劃為 build 12，先使用 `MALTOSE_PACKAGE_OUTPUT` 封裝到私有 release 位置，避免覆蓋仍在執行的 bundle 或混用延後載入的 Python 來源。完整回歸、靜態封裝稽核與後續正式 App 啟動各自記錄；不將舊版本的通過結果套用到新版。

## 最終回歸與封裝結果

當前來源完整 Python 397 項通過、0 failures／errors／skip，31.292 秒，包含五項實際 Docker 整合；Swift 141 項、0 failures、15 GUI skip，154.282 秒，包含真實 Main／Codex 模型交接。Mac 再度鎖定，這些 GUI 項目尚未補驗。日誌分別為 `/tmp/maltose-main-lifetime-final-full-python.log`、`/tmp/maltose-main-lifetime-full-swift.log`。

build 12 已獨立封裝至 `.cache/unification/releases/Maltose-0.7.0-12.app`，144 個 bundle／128 個 runtime 檔案來源相符；strict 簽章、受管理 Python 獨立 cwd 匯入（包含兩套 guard 與共用 tracker）、兩項既有服務憑證掃描均通過。static verifier 不啟動模型或麥克風。沒有覆蓋 `dist/Maltose.app`，正式 App 仍為 build 11；其 142 檔回復副本已比對及驗證簽章。

## 額外 Docker 崩潰實測：仍未通過

在私有 fixture 中使真實原生 runtime 的 Echo 模型執行 Docker backend，待容器持續寫 heartbeat 後 SIGKILL root 群組。合作式容器可隨 CLI TERM 停止，但這不足以涵蓋忽略訊號的工作。將容器改為忽略 TERM／HUP 後，觀察到 **OS 已追蹤程序全數停止，daemon 容器仍存在、heartbeat 仍更新**。probe 回傳 1；finally 使用該 fixture 的唯一名稱及 execution 標籤查得完整 ID，精準移除後重查，其他容器不受影響。

重現工具為 `runtime/dev/tools/verify_native_docker_crash.py`；日誌 `/tmp/maltose-native-docker-resistant-crash.log`，私有 fixture 保留結果。這項紅燈與上方 397 項綠燈共同構成當前證據，不能把程序測試通過當成整體退出安全。既有 Docker timeout 路徑有 finally 清理，Python root 被 SIGKILL 時卻無法執行 finally。

下一步需在 Docker 啟動前建立可回復的 execution 所有權登記，讓獨立守護於 root 消失後仍可依唯一標籤及完整容器 ID 清理／重查；同時涵蓋建立中崩潰、daemon 不可用及重啟後不盲目重播。未確認清理應保持可見且阻止衝突的執行，不能用廣泛 prune 或停掉 Docker engine 代替。修正後重跑此 resistant probe 及現有 timeout／unrelated-container 檢查，再完成適當回歸與新版封裝。

正式 Finder／真人語音／全 App 故障矩陣及專案附件重新定位仍未完成，目標保持進行中。機器可讀結果見 [build 12 驗證](main-lifetime-build12-results.json)。

後續進度：上方 build 12 紅燈已由 build 13 的持久資源登記／guardian create 與清理修正；七項真實故障及恢復矩陣通過。舊紅燈保留作歷史，不再當作目前仍未修復的缺口。最新範圍與剩餘驗收見 [Docker 生命週期報告](native-docker-lifetime-report.md)。
