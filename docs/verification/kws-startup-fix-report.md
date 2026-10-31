# MyAgent KWS 啟動修復驗證

日期：2026-10-29。來源：[修復計畫](../../plans/myagent-kws-startup-fix.md)。

## 根因與修正

使用者執行 `./start --maltose` 時，`wake.toml` 的 Alibaba KWS Python 指向已不存在的 `/private/tmp/myagent-kws310/bin/python`。CLI 在建立 EventHub／MaltoseBridge 之前就停止，因此後面的 Web UI 未就緒訊息只是結果。

已以 uv 與原有 Python 3.10.19 重建持久環境 `/Users/Marvin/Workspace/MyAgent/.venvs/kws310`，設定改為相對路徑 `.venvs/kws310/bin/python`，新增 `.venvs/` 忽略規則。保留原模型 `alibaba-kws-maiyatang-real-tts1000-raw-clean35-speed-cp998`、normalization、threshold、主 Python 3.12 `.venv`、pyproject.toml／uv.lock。

依既有 KWS 開發記錄使用 ModelScope 1.40.1、PyTorch 2.14.0、py-sound-connect 0.2.1，補齊實際 pipeline 必需的 datasets／soundfile／PyYAML 依賴。獨立環境共 66 個鎖定套件，附 SHA-256 與 `dev/tools/setup_kws_runtime.py` 重建工具。來源為 [PyPI ModelScope](https://pypi.org/project/modelscope/1.40.1/)、[PyPI PyTorch](https://pypi.org/project/torch/2.14.0/) 與 ModelScope 官方套件索引；沒有把這些依賴加入 MyAgent 主專案。

補上以下行為：

- config 中相對 Python 路徑以 config 所在位置解讀，保留 venv/bin/python 的符號連結路徑；不能把它 resolve 成底層 Python 而失去 venv。
- interpreter 遺失／不可執行時，在建立 worker 前提供明確重建命令；CLI 回報喚醒詞服務錯誤，避免裸 FileNotFoundError。
- worker 初始化 ERROR 回傳原始原因，失敗會回收子程序與 pipes。
- 實際首次載入曾超過原有 20 秒上限，故初始化獨立允許 60 秒；後續 PCM／health 回應上限維持 20 秒。測試確認初始化寬限不會放寬請求逾時。
- `start` 發現 Agent 提早結束時，保留其 exit code 並指出啟動錯誤，避免誤導為 UI port 問題。

## 實際驗證

| 檢查 | 結果 | 證據 |
|---|---|---|
| 持久 KWS 環境重建工具，依鎖定版本／雜湊同步並匯入真正 pipeline | 通過，66 packages checked | [重建工具 log](kws-setup-reproducibility.log) |
| 真正既有模型載入 | READY，最終實測 3.75 秒 | [模型 smoke](kws-runtime-smoke.log) |
| 真正 worker health → 1 秒合成靜音 PCM → reset → health → shutdown | 通過；healthy=true、kws_state=0、buffered_bytes=0；靜音未誤觸發 | [模型 smoke](kws-runtime-smoke.log) |
| KWS startup／listening／voice loop／Maltose 相關回歸 | **38 通過**（包含 7 項新增 startup 測試） | [相關測試](kws-startup-tests.log) |
| 完整 MyAgent 回歸 | 281 執行：**273 通過、3 個原有失敗、5 skipped** | [完整回歸](kws-full-myagent-tests.log) |
| MyAgent git diff --check／start shell syntax | 通過 | 本次本機實際執行 |

三個既有失敗仍為 test_agent 的記憶工具、profile、tasks 與人類身分驗證假設落差，與上一輪未修改 HEAD 的基線一致，詳見 [接入報告](agent-integration-report.md)。沒有放寬身分政策，也沒有宣稱完整 suite 全綠。

## 過程中發現並修正

- 最初重建只安裝 ModelScope core，實際 pipeline 缺少 addict；按已安裝官方 metadata 加入 datasets 基礎依賴及 far-field 音訊依賴，再鎖定。
- 第一次相對路徑處理使用 resolve，會沿著 venv Python symlink 跑到底層 interpreter；已改 absolute 保留 symlink，加入回歸。
- 新環境第一次載入超過 20 秒；後續 pipeline 匯入與原模型實測成功，並將初始化等待與請求等待分開。

## 操作與未驗證範圍

目前已完成環境重建與設定修復，使用者可直接重試 `./start --maltose`。日後若隔離環境真的遺失，在 MyAgent 專案執行：

```sh
uv run --no-sync python dev/tools/setup_kws_runtime.py
```

此次實測使用真正本機模型與合成靜音，沒有開啟麥克風、播放語音或讀私人錄音。沒有替使用者啟動完整持續聆聽流程、正式模型服務或批准 Maltose 配對；這些仍由使用者實際重試驗收。沒有修改其他 command-execution 的既有開發內容。
