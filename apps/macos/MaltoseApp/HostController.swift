import SwiftUI
import AppKit
import MaltoseCore
@MainActor final class HostController: ObservableObject {
    @Published var surfaces:[Surface]=[]
    @Published var pairingRequests:[PairingRequest]=[]
    @Published var agentRuntimes:[AgentRuntimeView]=[]
    @Published var agentInputs:[String:String]=[:]
    @Published var integrationStatus=""
    var discovery:DiscoveryPublisher?
    var pairing:PairingCoordinator?
    @Published var status = "正在啟動…"
    @Published var principal = "agent.investment"
    @Published var oneTimeToken = ""
    @Published var credentialStatus = ""
    @Published var sharingSurface = ""
    @Published var sharingAgent = "agent.maltose"
    @Published var shareSelection = false
    @Published var shareDocument = false
    @Published var shareViewport = false
    @Published var grantStatus = ""
    let registry:AgentRegistry
    init(registry:AgentRegistry = AgentRegistry()) {self.registry=registry}
    var host: HostState?
    var server: LoopbackServer?
    var windows: [String:NSWindow] = [:]
    var delegates: [String:SurfaceWindowDelegate] = [:]
    func start() async {
        do {
            let dir = FileManager.default.urls(for: .applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("MaltoseUIHost")
            try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
            let resources=Bundle.main.resourceURL.flatMap {Bundle(url:$0.appendingPathComponent("MaltoseUIHost_MaltoseApp.bundle"))} ?? Bundle.module
            let toolkit=resources.url(forResource:"toolkit",withExtension:nil,subdirectory:"Resources").flatMap {try? ToolkitArtifact(directory:$0)}
            let host=try HostState(path:dir.appendingPathComponent("state.sqlite").path,toolkit:toolkit)
            self.host = host
            let discovery=try DiscoveryPublisher(),pairing=PairingCoordinator(registry:registry)
            self.discovery=discovery;self.pairing=pairing
            let server=try LoopbackServer(host:host,registry:registry,port:0,pairing:pairing,instanceID:discovery.instanceID,hostID:discovery.hostID)
            self.server = server
            let port=try await server.start()
            try discovery.publish(port:port)
            status="已連線 · 127.0.0.1:\(port)"
            while !Task.isCancelled {
                surfaces = await host.surfacesForHost()
                pairingRequests=await pairing.pending()
                agentRuntimes=await host.runtimeViews()
                synchronizeWindows()
                try await Task.sleep(for:.milliseconds(100))
            }
        } catch is CancellationError {stop();status="已停止"}
        catch {stop();status = "無法啟動：\(error.localizedDescription)"}
    }
    func stop(){discovery?.remove();server?.stop()}
    func approvePairing(_ id:String){Task {do {try await pairing?.approve(id);integrationStatus="已批准連接與工具套件使用。"} catch {integrationStatus=credentialFailure(error)}}}
    func denyPairing(_ id:String){Task {await pairing?.deny(id)}}
    func sendInput(_ principal:String){Task {do {try await host?.sendRuntimeInput(principal:principal,text:agentInputs[principal] ?? "");agentInputs[principal]=""} catch {integrationStatus="Agent 目前無法接收指令。"}}}
    func register() {let agent=principal;Task {await registerCredential(agent)}}
    func registerCredential(_ agent:String) async {
        oneTimeToken=""
        do {oneTimeToken=try await registry.register(agent);credentialStatus="憑證已建立，請複製後交給此代理。"}
        catch {credentialStatus=credentialFailure(error)}
    }
    func credentialFailure(_ error:any Error)->String {
        guard let failure=error as? MUPError else {return "憑證操作失敗，請稍後重試。"}
        switch failure.code {
        case "invalid_principal":return "代理識別碼請使用英文字母、數字、句點、底線或連字號，例如 agent.myagent。"
        case "quota":return "代理數量已達上限，請先撤銷不再使用的代理。"
        case "keychain":return "無法存取 macOS 鑰匙圈：\(failure.message)"
        default:return "憑證操作失敗：\(failure.message)"
        }
    }
    func revoke() {let agent=principal;Task {do {try await registry.revoke(agent);await host?.revokePrincipal(agent);oneTimeToken="";credentialStatus="已撤銷此代理的憑證。"} catch {credentialStatus=credentialFailure(error)}}}
    func change(_ surface: Surface, detach: Bool) {
        Task {
            guard let host else { return }
            let session = UUID().uuidString
            do {
                try await host.connect(principal:surface.owner,sessionID:session)
                let request: JSON = .object(["protocol":.s(MUP.version),"message_id":.s(UUID().uuidString),"session_id":.s(session),"request_id":.s(UUID().uuidString),"type":.s("command"),"name":.s(detach ? "surface.detach" : "surface.attach"),"payload":.object(["surface_id":.s(surface.id)])])
                _ = await host.handle(try request.data(),principal:surface.owner,sessionID:session)
                await host.disconnect(sessionID:session)
            } catch { status = "視窗操作失敗" }
        }
    }
    func share(revoke:Bool=false) {
        Task {
            guard let host else {return}
            var scopes:Set<Scope> = revoke ? [] : [.summary]
            if !revoke {if shareSelection {scopes.insert(.selection)};if shareDocument {scopes.insert(.document)};if shareViewport {scopes.insert(.viewport)}}
            do {try await host.setGrant(surfaceID:sharingSurface,grantee:sharingAgent,scopes:scopes);grantStatus = revoke ? "已撤銷分享與訂閱" : "已套用指定範圍"} catch {grantStatus = "無法更新授權"}
        }
    }
    func synchronizeWindows() {
        let desired = Set(surfaces.filter {$0.kind == "window" && $0.visible}.map(\.id))
        for id in windows.keys.filter({!desired.contains($0)}) { windows[id]?.orderOut(nil); windows.removeValue(forKey:id); delegates.removeValue(forKey:id) }
        for surface in surfaces where desired.contains(surface.id) && windows[surface.id] == nil {
            let window = NSWindow(contentRect:restoredFrame(surface),styleMask:[.titled,.closable,.resizable,.miniaturizable],backing:.buffered,defer:false)
            window.title = surface.title
            window.minSize = NSSize(width:240,height:180)
            window.isReleasedWhenClosed = false
            let delegate = SurfaceWindowDelegate(controller:self,surfaceID:surface.id)
            window.delegate = delegate; delegates[surface.id] = delegate
            window.contentView = NSHostingView(rootView:WebSurface(surfaceID:surface.id,host:host!))
            windows[surface.id] = window; window.makeKeyAndOrderFront(nil)
        }
    }
    func restoredFrame(_ surface:Surface)->NSRect {
        let p=surface.userOverrides["window_placement"].object != nil ? surface.userOverrides["window_placement"] : surface.placement
        let desired=NSRect(x:p["x"].number ?? 160,y:p["y"].number ?? 160,width:p["width"].number ?? 820,height:p["height"].number ?? 540)
        let screen=NSScreen.screens.first { screen in
            "screen-\(screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? "unknown")" == p["screen_id"].string
        } ?? NSScreen.main
        guard let frame=screen?.visibleFrame else {return desired}
        let width=min(desired.width,frame.width),height=min(desired.height,frame.height)
        return NSRect(x:max(frame.minX,min(desired.minX,frame.maxX-width)),y:max(frame.minY,min(desired.minY,frame.maxY-height)),width:width,height:height)
    }
}
@MainActor final class SurfaceWindowDelegate: NSObject, NSWindowDelegate {
    weak var controller: HostController?
    let surfaceID: String
    var layoutTask:Task<Void,Never>?
    init(controller:HostController,surfaceID:String) { self.controller = controller; self.surfaceID = surfaceID }
    func windowDidMove(_ notification:Notification) {scheduleLayout(notification)}
    func windowDidResize(_ notification:Notification) {scheduleLayout(notification)}
    func scheduleLayout(_ notification:Notification) {
        guard let window=notification.object as? NSWindow else {return}
        layoutTask?.cancel()
        let frame=window.frame,screen=window.screen
        let screenID="screen-\(screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? "unknown")"
        let placement:JSON = .object(["x":.number(frame.minX),"y":.number(frame.minY),"width":.number(max(240,frame.width)),"height":.number(max(180,frame.height)),"screen_id":.s(screenID)])
        layoutTask=Task {do {try await Task.sleep(for:.milliseconds(150));try await controller?.host?.updateLayout(surfaceID:surfaceID,placement:placement)} catch {}}
    }
    func windowDidBecomeKey(_ notification:Notification) { Task {await controller?.host?.nativeFocus(surfaceID:surfaceID)} }
    func windowDidResignKey(_ notification:Notification) { Task {await controller?.host?.nativeFocus(surfaceID:nil,active:false)} }
    func windowShouldClose(_ sender:NSWindow) -> Bool {
        if let surface = controller?.surfaces.first(where:{$0.id == surfaceID}) { controller?.change(surface,detach:false) }
        return false
    }
}
