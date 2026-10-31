# ADR 003：WKWebView 離線封裝

實際 macOS 測試發現 file:// 載入 Vite ES module 時內容空白。改以 IIFE classic script 封裝 React、Zod 與 ECharts，全部資產內嵌於 app resource bundle，無 CDN。重新執行 WKWebView 測試確認圖表可顯示與 bridge 可回傳結構化選取。

原生不透過 evaluateJavaScript 下發文件；Renderer 透過固定 allowlist 的 WKScriptMessageHandlerWithReply 取得 Host snapshot，與提交語意事件。來源必須是主 frame、指定 WebView、bundle 內的 file URL。所有外部/新視窗導航拒絕，CSP connect-src none。

驗證程式可以使用固定的 JavaScript UI 自動化讀取測試 DOM；這不是代理生成的可執行 UI，也不是 awareness 實作的一部分。
