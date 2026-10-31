import SwiftUI
import WebKit
import MaltoseCore
@MainActor struct WebSurface: NSViewRepresentable {
    let surfaceID: String
    let host: HostState
    func makeCoordinator() -> Coordinator {Coordinator(surfaceID:surfaceID,host:host)}
    func makeNSView(context:Context) -> WKWebView {buildView(context.coordinator)}
    func buildView(_ coordinator:Coordinator) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        config.userContentController.addScriptMessageHandler(coordinator,contentWorld:.page,name:"maltose")
        let view = FocusWebView(frame:.zero,configuration:config)
        view.onFocus = { Task {await host.nativeFocus(surfaceID:surfaceID)} }
        view.onGeometry = { window,frame in
            let screenID="screen-\(window.screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? "unknown")"
            let placement:JSON = .object(["x":.number(frame.minX),"y":.number(frame.minY),"width":.number(max(240,frame.width)),"height":.number(max(180,frame.height)),"screen_id":.s(screenID)])
            Task {try? await host.updateWorkspaceLayout(surfaceID:surfaceID,placement:placement)}
        }
        view.navigationDelegate = coordinator
        view.setValue(false,forKey:"drawsBackground")
        coordinator.view = view
        Task {await host.openBridge(surfaceID:surfaceID,epoch:coordinator.epoch); coordinator.ready = true}
        let resources=Bundle.main.resourceURL.flatMap { Bundle(url:$0.appendingPathComponent("MaltoseUIHost_MaltoseApp.bundle")) } ?? Bundle.module
        if let url = resources.url(forResource:"index",withExtension:"html",subdirectory:"Resources/renderer") {
            coordinator.root = url.deletingLastPathComponent()
            view.loadFileURL(url,allowingReadAccessTo:url.deletingLastPathComponent())
        }
        return view
    }
    func updateNSView(_ view:WKWebView,context:Context) {}
    static func dismantleNSView(_ view: WKWebView, coordinator: Coordinator) {(view as? FocusWebView)?.stopObserving();view.stopLoading();view.configuration.userContentController.removeScriptMessageHandler(forName:"maltose",contentWorld:.page)}
    @MainActor final class Coordinator:NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate {
        let surfaceID:String, host:HostState, epoch=UUID().uuidString
        weak var view:WKWebView?
        var root:URL?
        var ready=false
        init(surfaceID:String,host:HostState){self.surfaceID=surfaceID;self.host=host}
        func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage,replyHandler:@escaping @MainActor @Sendable (Any?,String?)->Void) {
            guard message.frameInfo.isMainFrame,ready,message.webView === view,let url=message.frameInfo.request.url,url.isFileURL,let root,url.standardizedFileURL.path.hasPrefix(root.standardizedFileURL.path + "/") else {replyHandler(nil,"Untrusted bridge source");return}
            Task {
                do {
                    let bytes=try JSONSerialization.data(withJSONObject:message.body)
                    guard bytes.count<=65536 else {throw MUPError("message_too_large","Bridge message limit exceeded")}
                    let value=try JSON.decode(bytes)
                    if value == .object(["kind":.s("ready")]) {
                        let snapshot=try await host.rendererSnapshot(surfaceID:surfaceID,epoch:epoch)
                        replyHandler(try JSONSerialization.jsonObject(with:snapshot.data()),nil)
                    } else {
                        try await host.acceptBridge(value,boundSurface:surfaceID,epoch:epoch)
                        replyHandler(["ok":true],nil)
                    }
                } catch {replyHandler(nil,"Invalid semantic message")}
            }
        }
        func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping @MainActor @Sendable (WKNavigationActionPolicy)->Void) {
            guard let url=navigationAction.request.url,let root,url.isFileURL,url.standardizedFileURL.path == root.appendingPathComponent("index.html").standardizedFileURL.path,navigationAction.targetFrame?.isMainFrame == true else {decisionHandler(.cancel);return}
            decisionHandler(.allow)
        }
    }
}
@MainActor final class FocusWebView:WKWebView {
    var onFocus:(()->Void)?
    var onGeometry:((NSWindow,NSRect)->Void)?
    var geometryTask:Task<Void,Never>?
    var observations:[NSObjectProtocol]=[]
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        for observation in observations {NotificationCenter.default.removeObserver(observation)}
        observations=[]
        if let window {
            for name in [NSWindow.didMoveNotification,NSWindow.didResizeNotification,NSWindow.didChangeScreenNotification] {
                observations.append(NotificationCenter.default.addObserver(forName:name,object:window,queue:.main) { [weak self] _ in Task {@MainActor in self?.scheduleGeometry()} })
            }
        }
        scheduleGeometry()
    }
    override func setFrameSize(_ newSize:NSSize) {super.setFrameSize(newSize);scheduleGeometry()}
    func scheduleGeometry() {
        geometryTask?.cancel()
        geometryTask=Task { [weak self] in
            do {try await Task.sleep(for:.milliseconds(150))} catch {return}
            guard let self,let window=self.window,self.bounds.width>0,self.bounds.height>0 else {return}
            self.onGeometry?(window,window.convertToScreen(self.convert(self.bounds,to:nil)))
        }
    }
    func stopObserving() {geometryTask?.cancel();for observation in observations {NotificationCenter.default.removeObserver(observation)};observations=[]}
    override func becomeFirstResponder()->Bool {let result=super.becomeFirstResponder();if result {onFocus?()};return result}
}
