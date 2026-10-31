# 憑證建立失敗修復計畫

## 問題
使用者在封裝 App 輸入有效識別碼 maltose.main，但只見通用「憑證註冊失敗」。

## 步驟
- [x] 比對目前程序與封裝版本，確認實際錯誤。
- [x] 在 App 顯示安全、可理解的失敗原因，保留非敏感 OSStatus。
- [x] 以封裝 App 的簽章身分實測隔離的暫存 Keychain service（不輸出 token、不改動使用者既有憑證）。
- [x] 修復根因，執行相關測試、重建與封裝。
- [x] 讓使用者的開啟視窗載入修正版，報告實測與剩餘限制。

## 實際結果
- 觀察到的執行中程序：2026-10-29 12:41:08 啟動；當時已修正的 release binary 於 12:44:47 才更新。舊程序不會自動載入後續磁碟更新。
- CUA 畫面確認有效識別碼 maltose.main；舊介面只顯示通用失敗訊息。
- 封裝更新至 0.3.1 / build 4；憑證訊息與 Host 連線狀態分開顯示，錯誤保留安全的 OSStatus，失敗會清除舊 token 顯示。
- CredentialControllerTests：2 tests，0 failures。
- release package / codesign strict / resource self-test：通過。
- 封裝 App --self-test-keychain：隔離 service 的 read/write/rotation/revocation 通過，測後清除，沒有輸出 token。
- 透過 CUA 關閉舊程序並重開新版，確認已連線 127.0.0.1:8765，恢復使用者輸入 maltose.main。
- 正式憑證最後的建立／輪替由使用者在 App 按鈕完成；沒有改動使用者既有憑證，不宣稱正式憑證已建立。
