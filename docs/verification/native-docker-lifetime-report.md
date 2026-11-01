# 原生 Docker 執行生命週期與故障恢復

日期：2026-11-01。狀態：原生 runtime 修補及隔離驗證通過；正式 GUI／真人語音仍待驗收。

## 問題與行為

build 12 的隔離實測證明：root 群組崩潰後，即使所有已追蹤的 OS 程序都停止，忽略 TERM／HUP 的 daemon 容器仍能寫入。當時 probe 回傳 1，測試 finally 精準清理了該容器。舊結果保留在 [build 12 結果](main-lifetime-build12-results.json)。

原生 App 管理的 Docker backend 現在先將工作交給獨立 guardian 建立尚未執行的容器。guardian 保存 execution ID、scope、creator PID／建立時間、建立狀態及完整容器 ID；核對 daemon 的唯一名稱與 execution 標籤後，才允許主 runtime 使用 `docker start --attach` 執行。紀錄不包含 argv、服務憑證或模型對話。

creator 另有一個私有准入位元：PID 及准入狀態持久化後才可呼叫 Docker。父程序若在登記完成前死亡，creator 收到 EOF 就退出；這補上 fork 與紀錄之間的窗口。未准入的工作可以確認未送出；已送出卻沒有結果的建立保持 uncertain，不能盲目重播。

正常結束或故障清理均以唯一名稱／標籤查得完整 ID；已有 ID 的紀錄還會拒絕身分被替換的容器。移除後再次查詢確認。共用程序 tracker 保留 guardian 自己的清理 helper，並可在正常收尾時只停止 root 的其他後代。原生 kernel lease 透過同一個 descriptor 保留到 daemon 清理完成，避免舊容器仍可寫入時接納另一個 writer。

清理未確認會先關閉既有 autonomy gate，再使主 runtime 失敗。下一次啟動先恢復未完成清理，完成前不初始化 Agent；恢復只處理舊容器，不重送 create／start。一般開發 CLI 保留原有執行路徑，本報告的完整守護範圍是原生入口所管理的 backend。

## 真實故障矩陣

工具：`runtime/dev/tools/verify_native_docker_crash.py`。最終日誌：`/tmp/maltose-docker-owner-admission-matrix.log`；建立中 lease 另以 `/tmp/maltose-docker-owner-lease-proof.log` 強化確認。每項均使用真正 `maltose.desktop`、Echo 模型及本機 Docker；所有容器關閉網路、使用已存在的 `python:3.12-slim`，沒有啟動麥克風或修改正式 App。

| 情境 | 觀察與驗收 |
| --- | --- |
| root 整個群組 SIGKILL | 已追蹤程序停止、容器不存在、heartbeat 停止 |
| 宿主 SIGKILL，stdin 寫入端仍開啟 | 依宿主 PID／建立時間獨立偵測並清理 |
| 原生輸入 EOF，模型仍在執行 | 清理受管理程序與容器，沒有接受未確認的工具完成 |
| guardian SIGKILL | 既有 gate 關閉、已知資源緊急清理、runtime 失敗 |
| 建立中 root 崩潰 | 先確認 root 已實際死亡，kernel lease 仍被 guardian 持有；建立完成後移除，工作沒有開始 |
| 已建立、尚未啟動時崩潰 | 已保存 ID 的容器被移除，heartbeat 從未出現 |
| 清理 API 失聯 | runtime 以 70 失敗；容器仍在執行時再次啟動被阻擋；恢復 API 後先移除原容器再就緒 |

七項全部通過。每項另有獨立的旁觀容器，清理及同目錄重啟後仍維持 running；重啟沒有傳送模型指令，也沒有重播原容器。API 失聯由私有 CLI shim 注入，保留真正 daemon 與容器運行，沒有停掉 Docker engine。失聯期間的容器仍在寫入這項事實保存在 beforeRecovery，沒有拿恢復後成功掩蓋它。

所有 fixture 在 finally 使用各自的唯一 execution 名稱／標籤與完整 ID 善後，沒有 prune、全面刪容器或停止其他工作。機器可讀結果見 [Docker 生命週期結果](native-docker-lifetime-results.json)。

## 其他驗證

- 聚焦程序／資源／IPC／Docker 44 項通過，14.629 秒；涵蓋未知建立結果、daemon 不可用、跨 scope 與 symlink 拒絕、PID／ID 核對、禁止重播、准入前 EOF、清理失敗封閉 gate 及時限耗盡不得啟動工作。
- 完整 Python：408 項、0 failures／errors／skip，34.348 秒，包含五項實際 Docker integration。
- 完整 Swift：141 項、0 failures、15 GUI skip，134.849 秒，包含真實 Main／Codex 模型。Mac 仍鎖定，GUI 項目需另補驗。
- 新增啟動觀察 fixture 曾漏帶 `--native-stdio`，修正替身後保持原斷言並通過。故障工具新增最後核對時曾有縮排錯誤，語法檢查已發現並修正；該錯誤沒有啟動容器。上述失敗不作為成功證據。

完整回歸日誌為 `/tmp/maltose-docker-owner-final-full-python.log` 與 `/tmp/maltose-docker-owner-full-swift.log`。既有完整外部 lock package 記錄與本輪前完全相同；沒有重建正式環境、升級語音／模型或改認證。

## 發行與後續

修補版為 0.7.0／build 13，獨立封裝至 `.cache/unification/releases/Maltose-0.7.0-13.app`，145 個 bundle／129 個 runtime 檔案與來源相符；strict 簽章、受管理 Python 獨立 cwd 匯入及兩項既有憑證值檢查通過。static verifier 沒有啟動 Agent 或麥克風。`dist/Maltose.app` 仍為 build 11，未覆蓋正在使用的 bundle；build 11 的回復副本保持不變。

正式升版前先退出 Maltose，再處理受管理環境收據及 App 切換；執行中封裝時使用 `MALTOSE_PACKAGE_OUTPUT` 指定另一個輸出。`native-executions` 是私有恢復紀錄，回復備份需一併保留，不能為繞過啟動失敗而刪除 pending 紀錄；恢復 Docker 連線後使用既有重試入口。

下一步仍為正式 build 13 的 Finder 冷啟動、退出／重啟、全 App 故障、原生 UI 的完整 Codex 互動，以及真人語音／身分／中斷／裝置矩陣。宿主 fixture 的通過不替代這些驗收；本機專案及聊天附件也仍需人員重新定位。整個 M0–M7 目標保持 in_progress。
