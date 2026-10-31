# Typed Canvas / `ui_canvas` 支援計畫

## 目標

讓 MyAgent 的 `ui_canvas` 場景資料能以 Maltose 原生互動畫布顯示，沿用固定 schema、surface ownership 與 Agent UI Awareness；不接受 HTML、SVG 字串、JavaScript 或任意程式碼。

## 工作項目

- [x] MUP document schema 增加受限 canvas node 與 rect/ellipse/triangle/text 元素；限制數量、座標、尺寸、文字和 hex 色彩。
- [x] 原生 Host 驗證及可見節點索引納入畫布元素，維持選取/焦點事件的 node ID 與隔離。
- [x] React renderer 以固定 SVG primitives 繪製場景並支援元素點選，嚴格驗證輸入。
- [x] MyAgent bridge 把 `ui_canvas` 區塊轉成 canvas node，略過未知元素、安全降級不合法顏色，絕不執行 payload。
- [x] 新增 schema、轉換、renderer 回歸；重建簽章 toolkit 與 app。
- [x] 以完整房屋 payload 驗證 MyAgent bridge 轉換，並以原生 WebKit 測試確認 typed canvas 可見且點選回報節點；真人語音輸出尚未重跑。

## 已知 payload 欄位

場景有 `scene_id`、`title`、`elements`。現有 element 有 `type: node|text`、`id`、`x/y/width/height`、`label`、`color`。`node` 暫映射成受限矩形；來源若提供 `shape`/`primitive` 可選 `rect`、`ellipse`、`triangle`。`text` 以 SVG 文字繪製。缺省畫布大小為 640×480，必要時擴大至包住元素（上限 4096）。

## 安全邊界

SVG 只由 renderer 建立，不接收 SVG markup；element type 固定 enum，顏色只允許 `#RRGGBB`，所有文字經 React text node 輸出。Host 仍檢查全 surface node ID 唯一與文件大小。

## 驗證結果（2026-10-29）

- Renderer Vitest：25 通過；renderer 與 TypeScript SDK production build 通過。
- MyAgent Maltose unittest：11 通過，包含完整 house/roof/door/sun/tree/caption 場景轉換。
- Swift：41 通過；5 個 GUI-only 案例在一般 suite 中依環境跳過。另以 `MALTOSE_GUI_TESTS=1` 執行 WebKit canvas 渲染與點選回報，1 通過。
- 受限 shell 中第一次 Swift run 的 loopback tests 被系統拒絕 bind；在允許本機 socket 的測試環境重跑全套後通過。
- 真人麥克風/語音 Agent 沒有在本輪啟動；原生 WebKit、Host 與 selection 已透過整合測試驗證。
