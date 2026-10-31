# Typed Canvas 驗證紀錄

日期：2026-10-29

## 結果

MyAgent `ui_canvas` 區塊已轉成 MUP v0.3 typed canvas，經 Maltose 原生 Host 顯示成互動畫布。房屋場景的 house、roof、door、sun、tree 與 caption 都轉成固定型別節點；`node` 預設矩形，`text` 轉成 text primitive。顏色與尺寸經界限檢查，未知型別略過，文字以一般字串保留。

WebKit UI 測試以原生視窗載入畫布並點選 `sun`；Host 的 context snapshot 回報 `selection.node_id = sun`、`selection.kind = node`。畫布元素也進入 Host 的文件節點索引，可供既有 UI Awareness 與 reference resolution 使用。各 Agent 的 surface ownership 未變更。

## 實際執行的檢查

- `npm test`：4 個測試檔、25 個測試通過。
- `npm run build`：renderer 與 TypeScript SDK build 通過。
- MyAgent `python -m unittest discover -s tests -p test_maltose_ui_integration.py -v`：11 個測試通過，含使用完整房屋 payload 的轉換測試。
- `./scripts/swift-test.sh`：41 個測試通過；5 個 GUI-only 案例在預設執行中 skip。
- `MALTOSE_GUI_TESTS=1 ./scripts/swift-test.sh --filter WKRendererTests/testTypedCanvasRendersAndReportsSelectedElement`：1 個 WebKit 渲染與選取回報測試通過。
- `./scripts/package.sh`：簽章 toolkit 與 `dist/Maltose UI Host.app` 成功建立；`codesign --verify --strict` 通過。Toolkit wheel SHA-256：`4c62cdb4eb48d5dadb91e5c4f45b05659c6ffed66197f3f18c2c552ae57743c6`。
- schema 生成後 `npm test` 再跑一次：25 個測試通過。

受限執行環境第一次跑 Swift suite 時，loopback bind 受作業系統權限限制；以允許本機 socket 的測試環境重跑後全數通過。真人麥克風與正式模型未在本輪啟動，尚未完成手動語音驗收。

## 使用方式

關閉舊版 Maltose UI Host 後開啟 `dist/Maltose UI Host.app`，再重新啟動 MyAgent（`./start --maltose`）。MyAgent 更新後會經簽章 toolkit 安裝／載入 typed canvas bridge；當 Agent 送出 `ui_canvas` 區塊，房屋圖形會出現在 Maltose 工作區。點選圖形會把選取節點提供給 Agent 的授權 UI context。

架構選擇詳見 [ADR 004](../decisions/004-typed-safe-canvas.md)，工作範圍與驗證清單見 [typed canvas plan](../../plans/typed-canvas.md)。
