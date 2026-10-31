# ADR 004：MUP 安全型別畫布

狀態：採用（2026-10-29）

## 背景

MyAgent 的 `ui_canvas` 可以帶入任意場景元素，但 Maltose 原有文件節點只有 stack、文字、按鈕、表格與折線圖。舊橋接將未知區塊降成文字，造成房屋場景無法互動顯示。

## 決策

在 MUP v0.3 文件中加入 `canvas` 與固定 primitive 節點：`canvas.rect`、`canvas.ellipse`、`canvas.triangle`、`canvas.text`。座標/尺寸限制在 4096、元素限制 256、文字限制 2048 字元、顏色限制 `#RRGGBB`。canvas 只能含 primitive，primitive 只能是 canvas 的直接子項。

MyAgent bridge 僅將已知 `ui_canvas` 的 `node`、`text` 型別轉為這些節點，拒絕未知元素，校正尺寸/色彩並保留文字為普通資料。Host 用同一份結構化節點索引提供 UI Awareness；點選元素回報節點 ID 與 `kind: node`。

原生 renderer 使用 React 固定生成 SVG 節點，不接收 HTML/SVG markup、JavaScript 或執行檔。`node` 暫時以矩形表示；`shape` 或 `primitive` 欄位可選擇其他固定圖形。

## 後果

任意自由形式繪圖與代理生成程式碼不在支援範圍，避免 UI payload 形成程式碼執行面。現有 MyAgent 場景可以直接安全顯示；點選與 focus/selection 經既有 ownership、MUP 與隱私隔離機制處理。

## 驗證

見 [typed canvas 計畫與驗證](../../plans/typed-canvas.md)。
