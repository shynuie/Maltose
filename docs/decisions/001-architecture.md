# ADR 001：原生 Host 與受限離線 Renderer

決定：macOS 14+、Swift 6 / SwiftPM；Host actor 串行管理持久與暫態狀態。AppKit 管理視窗與焦點，SwiftUI 管理工作區。React + Zod + ECharts 只解讀封閉式 UI 文件。

SQLite WAL 保存文件、配置、使用者偏好、授權與不含內容的稽核。選取、焦點與 viewport 暫態資料不還原為活躍狀態。每個 surface 有文件版本；每個認證 principal 有 context 版本，避免從全域版本推知其他代理活動。

協定來源為 JSON Schema draft 2020-12；Swift 使用同一 schema 的受限關鍵字驗證器，TS/Python 使用標準驗證器並跑共同 fixtures。禁止將 v0.2 視為 v0.3。

安全邊界：僅 127.0.0.1 WebSocket，先認證才路由；憑證存 Keychain、不可由 agent 自行指定 principal。跨代理 grant 只能經本機可信任使用者介面修改。每次查詢與事件送出重新檢查 ACL。summary 不含 node、selection、data。

參考：Apple Network.framework NWProtocolWebSocket / NWListener / requiredLocalEndpoint，https://developer.apple.com/documentation/network/nwprotocolwebsocket ，https://developer.apple.com/documentation/network/nwparameters/requiredlocalendpoint ；https://json-schema.org/draft/2020-12 。

Keychain 實測修正：macOS 密碼項目不能同時使用 kSecMatchLimitAll 與 kSecReturnData。改為先只列屬性，再依精確 service/account 逐筆讀取。Registry 僅快取 SHA-256 digests，Host 內的輪替/撤銷立即更新；不是每 50ms 向 Keychain 讀取所有密碼。依據：https://developer.apple.com/documentation/security/secitemcopymatching(_:_:)
