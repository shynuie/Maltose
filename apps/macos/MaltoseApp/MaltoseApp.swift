import SwiftUI
import MaltoseCore
@main struct MaltoseApp: App {
    @StateObject var controller = HostController()
    init() {
        if CommandLine.arguments.contains("--self-test-keychain") {
            let store=KeychainCredentials(service:"local.maltose.package-smoke."+UUID().uuidString)
            let account="agent.package-smoke"
            do {
                defer {try? store.remove(principal:account)}
                guard try store.credentials().isEmpty else {throw MUPError("keychain","Test service was not empty")}
                let first=Data(UUID().uuidString.utf8),second=Data(UUID().uuidString.utf8)
                try store.save(principal:account,token:first)
                guard try store.credentials()[account] == first else {throw MUPError("keychain","Test credential read mismatch")}
                try store.save(principal:account,token:second)
                guard try store.credentials()[account] == second else {throw MUPError("keychain","Test credential rotation mismatch")}
                try store.remove(principal:account)
                guard try store.credentials().isEmpty else {throw MUPError("keychain","Test credential was not removed")}
                print("Packaged Keychain read/write/rotation/revocation verified")
                exit(0)
            } catch let error as MUPError {print(error.message);exit(1)}
            catch {print("Packaged Keychain verification failed");exit(1)}
        }
        if CommandLine.arguments.contains("--self-test-resources") {
            do {
                guard let resources=Bundle.main.resourceURL,
                      let core=Bundle(url:resources.appendingPathComponent("MaltoseUIHost_MaltoseCore.bundle")),
                      core.url(forResource:"command.schema",withExtension:"json",subdirectory:"Schemas") != nil,
                      let renderer=Bundle(url:resources.appendingPathComponent("MaltoseUIHost_MaltoseApp.bundle")),
                      let html=renderer.url(forResource:"index",withExtension:"html",subdirectory:"Resources/renderer"),
                      try String(contentsOf:html,encoding:.utf8).contains("connect-src 'none'") else {throw MUPError("resources","Packaged offline resources missing")}
                _ = try SchemaValidator(name:"command")
                guard let toolkit=renderer.url(forResource:"toolkit",withExtension:nil,subdirectory:"Resources") else {throw MUPError("resources","Packaged toolkit missing")}
                _ = try ToolkitArtifact(directory:toolkit)
                print("Packaged schemas, offline renderer and toolkit verified")
                exit(0)
            } catch {print("Packaged resource verification failed");exit(1)}
        }
    }
    var body: some Scene {
        WindowGroup("Maltose · 工作區") {
            NavigationSplitView {
                VStack(alignment:.leading,spacing:16) {
                    Text("MALTOSE").font(.title2.bold())
                    Text(controller.status).font(.caption).foregroundStyle(.secondary)
                    List(controller.surfaces) { s in
                        VStack(alignment:.leading) { Text(s.title); Text(s.owner).font(.caption).foregroundStyle(.secondary) }
                    }
                    Divider()
                    Text("代理存取").font(.headline)
                    TextField("代理識別碼",text:$controller.principal)
                    HStack { Button("建立 / 輪替憑證",action:controller.register); Button("撤銷",action:controller.revoke) }
                    if !controller.credentialStatus.isEmpty {Text(controller.credentialStatus).font(.caption).textSelection(.enabled)}
                    if !controller.oneTimeToken.isEmpty {
                        Text("請將憑證交給此代理；憑證存於本機鑰匙圈。").font(.caption)
                        Text(controller.oneTimeToken).font(.caption.monospaced()).textSelection(.enabled)
                        Button("隱藏憑證") { controller.oneTimeToken = "" }
                    }
                
                    Divider()
                    DisclosureGroup("跨代理分享") {
                        Picker("工作表面",selection:$controller.sharingSurface) {
                            Text("選擇工作表面").tag("")
                            ForEach(controller.surfaces) {Text($0.title).tag($0.id)}
                        }
                        TextField("接收代理",text:$controller.sharingAgent)
                        Text("預設僅分享標題與狀態摘要。").font(.caption)
                        Toggle("文件與元件識別碼",isOn:$controller.shareDocument)
                        Toggle("選取內容",isOn:$controller.shareSelection)
                        Toggle("圖表檢視範圍",isOn:$controller.shareViewport)
                        HStack {Button("套用授權") {controller.share()};Button("撤銷分享") {controller.share(revoke:true)}}
                        Text(controller.grantStatus).font(.caption)
                    }
                }.padding().frame(minWidth:260)
            } detail: {
                ScrollView {
                    VStack(alignment:.leading,spacing:20) {
                        Text("你的代理工作區").font(.largeTitle.bold())
                        ForEach(controller.pairingRequests) {request in
                            VStack(alignment:.leading,spacing:8) {
                                Text("\(request.name) 請求連接").font(.headline)
                                Text("自報識別碼：\(request.requestedAgentID)")
                                Text("核對代碼：\(request.code)").font(.title3.monospaced())
                                Text("允許此代理建立自己的畫面、取得自身 UI 情境，並安裝已驗證的 Maltose 工具套件到獨立 uv 環境。請確認這是你剛啟動的代理。")
                                HStack {Button("允許並記住") {controller.approvePairing(request.id)};Button("拒絕") {controller.denyPairing(request.id)}}
                            }.padding().background(.quaternary,in:RoundedRectangle(cornerRadius:12))
                        }
                        if !controller.integrationStatus.isEmpty {Text(controller.integrationStatus).font(.caption)}
                        ForEach(controller.agentRuntimes) {runtime in
                            VStack(alignment:.leading,spacing:8) {
                                HStack {Text(runtime.id).font(.headline);Spacer();Text(runtime.connectionLabel).foregroundStyle(runtime.isLive ? .green : .secondary)}
                                Text("狀態：\(runtime.phaseLabel)")
                                if runtime.isLive && runtime.modelActive {Text("正在進行模型推論…")}
                                if runtime.isLive && runtime.speechActive {Text("正在播報…")}
                                if runtime.isLive,let tool=runtime.tool {Text("執行工具：\(tool)")}
                                if let progress=runtime.progress {Text(progress)}
                                ForEach(runtime.messages) {message in
                                    VStack(alignment:.leading) {Text(message.role == "user" ? "你" : "Agent").font(.caption).foregroundStyle(.secondary);Text(message.text).textSelection(.enabled)}
                                }
                                HStack {
                                    TextField("傳送指令給這個 Agent",text:Binding(get:{controller.agentInputs[runtime.id] ?? ""},set:{controller.agentInputs[runtime.id]=$0})).onSubmit {controller.sendInput(runtime.id)}
                                    Button("傳送") {controller.sendInput(runtime.id)}.disabled(!runtime.isLive)
                                }
                            }.padding().background(.quaternary,in:RoundedRectangle(cornerRadius:12))
                        }
                        Text("持續互動、結構化理解、本機執行。").foregroundStyle(.secondary)
                        if controller.surfaces.isEmpty { ContentUnavailableView("尚無工作表面",systemImage:"rectangle.stack",description:Text("啟動已接入的 Agent，允許連接後即可顯示內容。")) }
                        ForEach(controller.surfaces.filter {$0.kind == "workspace" && $0.visible}) { s in
                            VStack(alignment:.leading) { HStack { Text(s.title).font(.headline); Spacer(); Button("獨立視窗") {controller.change(s,detach:true)} }; if let host = controller.host { WebSurface(surfaceID:s.id,host:host).frame(height:420) } }.padding().background(.quaternary,in:RoundedRectangle(cornerRadius:12))
                        }
                    }.padding(28)
                }
            }.frame(minWidth:1000,minHeight:680).onReceive(NotificationCenter.default.publisher(for:NSApplication.didResignActiveNotification)) { _ in Task {await controller.host?.nativeFocus(surfaceID:nil,active:false)} }.onReceive(NotificationCenter.default.publisher(for:NSApplication.willTerminateNotification)) {_ in controller.stop()}.task {await controller.start()}
        }
    }
}
