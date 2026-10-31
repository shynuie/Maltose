import XCTest
import AppKit
import WebKit
import MaltoseCore
@testable import MaltoseApp
@MainActor final class WKRendererTests:XCTestCase {
    func testOfflineRendererAndNativeBridge() async throws {try await runRendererTest(withAgent:false)}
    func testTypedCanvasRendersAndReportsSelectedElement() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else {throw XCTSkip("Set MALTOSE_GUI_TESTS=1 in a macOS desktop session")}
        _ = NSApplication.shared
        let host=try HostState(path:":memory:"),owner="agent.canvas",sid=UUID().uuidString
        try await host.connect(principal:owner,sessionID:sid)
        let root:JSON = .object(["node_id":.s("scene"),"type":.s("canvas"),"props":.object(["width":.n(640),"height":.n(480),"title":.s("隨手畫的小房子"),"background_color":.s("#111827")]),"children":.array([
            .object(["node_id":.s("house"),"type":.s("canvas.rect"),"props":.object(["x":.n(180),"y":.n(150),"width":.n(220),"height":.n(170),"label":.s("小房子"),"color":.s("#F4B183")])]),
            .object(["node_id":.s("roof"),"type":.s("canvas.triangle"),"props":.object(["x":.n(160),"y":.n(70),"width":.n(260),"height":.n(100),"label":.s("屋頂"),"color":.s("#C0504D")])]),
            .object(["node_id":.s("sun"),"type":.s("canvas.ellipse"),"props":.object(["x":.n(520),"y":.n(70),"width":.n(90),"height":.n(90),"label":.s("太陽"),"color":.s("#FFD966")])])
        ])])
        let payload:JSON = .object(["surface_id":.s("canvas-demo"),"title":.s("隨手畫的小房子"),"document":.object(["root":root])])
        let request:JSON = .object(["protocol":.s(MUP.version),"message_id":.s(UUID().uuidString),"request_id":.s(UUID().uuidString),"session_id":.s(sid),"type":.s("command"),"name":.s("surface.create"),"payload":payload])
        let response=await host.handle(try request.data(),principal:owner,sessionID:sid)
        XCTAssertEqual(response["ok"],.bool(true))
        let surface=WebSurface(surfaceID:"canvas-demo",host:host)
        let coordinator=surface.makeCoordinator(),web=surface.buildView(coordinator)
        let window=NSWindow(contentRect:NSRect(x:120,y:120,width:820,height:620),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
        window.isReleasedWhenClosed=false;window.contentView=web;window.makeKeyAndOrderFront(nil)
        defer {window.orderOut(nil);web.stopLoading();web.configuration.userContentController.removeScriptMessageHandler(forName:"maltose",contentWorld:.page)}
        var rendered=false
        var pageDiagnostic=""
        for _ in 0..<80 {
            try await Task.sleep(for:.milliseconds(100))
            let count=(try? await web.evaluateJavaScript("document.querySelectorAll('section.canvas-scene svg').length")) as? Int ?? 0
            if count>0 {rendered=true;break}
            do {pageDiagnostic=(try await web.evaluateJavaScript("location.href+' | '+document.readyState+' | '+document.body.innerText")) as? String ?? "empty"}
            catch {pageDiagnostic="\(web.url?.absoluteString ?? "no-url") root=\(coordinator.root?.path ?? "no-root") error=\(error)"}
        }
        XCTAssertTrue(rendered,"Typed canvas SVG was not rendered: \(pageDiagnostic)")
        guard rendered else {return}
        _ = try await web.evaluateJavaScript("document.querySelector('[data-node-id=\"sun\"]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))")
        try await Task.sleep(for:.milliseconds(200))
        let snapshot=try await host.contextSnapshot(principal:owner)
        XCTAssertEqual(snapshot["surfaces"].array?.first?["selection"]["node_id"],.s("sun"))
        XCTAssertEqual(snapshot["surfaces"].array?.first?["selection"]["kind"],.s("node"))
    }
    func testRealChartBrushThroughSignedToolkitIntoMyAgent() async throws {
        guard FileManager.default.isExecutableFile(atPath:"/Users/Marvin/Workspace/MyAgent/.venv/bin/python") else {throw XCTSkip("MyAgent environment not present")}
        try await runRendererTest(withAgent:true)
    }
    private func runRendererTest(withAgent:Bool) async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else {throw XCTSkip("Set MALTOSE_GUI_TESTS=1 in a macOS desktop session")}
        _ = NSApplication.shared
        let root=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let toolkit=withAgent ? try ToolkitArtifact(directory:root.appendingPathComponent("apps/macos/MaltoseApp/Resources/toolkit")) : nil
        let host=try HostState(path:":memory:",toolkit:toolkit)
        let owner=withAgent ? "agent.myagent-e2e" : "agent.gui"
        let sid=UUID().uuidString
        try await host.connect(principal:owner,sessionID:sid)
        let document:JSON = .object(["root":.object(["node_id":.s("chart-gui"),"type":.s("chart.line"),"props":.object(["title":.s("Offline synthetic chart"),"points":.array([.array([.n(1),.n(10)]),.array([.n(2),.n(20)]),.array([.n(3),.n(15)])])])])])
        let request:JSON = .object(["protocol":.s(MUP.version),"message_id":.s(UUID().uuidString),"request_id":.s(UUID().uuidString),"session_id":.s(sid),"type":.s("command"),"name":.s("surface.create"),"payload":.object(["surface_id":.s("gui"),"title":.s("GUI Test"),"document":document])])
        let reply=await host.handle(try request.data(),principal:owner,sessionID:sid)
        XCTAssertEqual(reply["ok"],.bool(true))
        let surface=WebSurface(surfaceID:"gui",host:host), coordinator=surface.makeCoordinator()
        let web=surface.buildView(coordinator)
        let window=NSWindow(contentRect:NSRect(x:120,y:120,width:820,height:500),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
        window.isReleasedWhenClosed=false;window.contentView=web;window.makeKeyAndOrderFront(nil)
        defer {window.orderOut(nil);web.stopLoading();web.configuration.userContentController.removeScriptMessageHandler(forName:"maltose",contentWorld:.page)}
        var rendered=false, body=""
        for _ in 0..<80 {
            try await Task.sleep(for:.milliseconds(100))
            body=(try? await web.evaluateJavaScript("document.body.innerText")) as? String ?? ""
            let canvases=(try? await web.evaluateJavaScript("document.querySelectorAll('canvas').length")) as? Int ?? 0
            if canvases>0 && body.contains("Offline synthetic chart") {rendered=true;break}
        }
        XCTAssertTrue(rendered,"Offline render failed: \(body)")
        guard rendered else {return}
        await host.nativeFocus(surfaceID:"gui")
        _ = try await web.evaluateJavaScript("document.querySelector('[data-node-id]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))")
        try await Task.sleep(for:.milliseconds(150))
        let snapshot=try await host.contextSnapshot(principal:owner)
        XCTAssertEqual(snapshot["focused_node_id"],.s("chart-gui"))
        XCTAssertEqual(snapshot["surfaces"].array![0]["selection"],.null)
        // Exercise the actual ECharts wheel path: local zoom emits a debounced semantic viewport.
        _ = try await web.evaluateJavaScript("document.querySelector('canvas').dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:320,clientY:160,deltaY:-120}))")
        try await Task.sleep(for:.milliseconds(400))
        let zoomed=try await host.contextSnapshot(principal:owner)
        XCTAssertNotEqual(zoomed["surfaces"].array![0]["viewport"],.null,"Wheel zoom must reach the semantic bridge")
        // Select a real interval through the ECharts toolbox and canvas drag path.
        _ = try await web.evaluateJavaScript("""
        (()=>{const c=document.querySelector('canvas'),r=c.getBoundingClientRect();
        const send=(type,x,y)=>c.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,clientX:r.left+x,clientY:r.top+y,buttons:type==='mousemove'?1:0}));
        send('mousemove',r.width-45,13);send('mousedown',r.width-45,13);send('mouseup',r.width-45,13);send('click',r.width-45,13);
        send('mousedown',120,130);send('mousemove',240,130);send('mousemove',420,130);send('mouseup',420,130);
        })()
        """)
        try await Task.sleep(for:.milliseconds(250))
        let selected=try await host.contextSnapshot(principal:owner)
        XCTAssertEqual(selected["surfaces"].array![0]["selection"]["kind"],.s("chart.time_range"),"Canvas brush must emit a structured interval")
        if withAgent {try await exerciseMyAgent(host:host,root:root,owner:owner)}
        // Navigation policy must block remote content even for a user-generated navigation.
        _ = try? await web.evaluateJavaScript("location.href='https://example.com'")
        try await Task.sleep(for:.milliseconds(100))
        XCTAssertTrue(web.url?.isFileURL == true)
    }
    private func exerciseMyAgent(host:HostState,root:URL,owner:String) async throws {
        let temp=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:temp,withIntermediateDirectories:true)
        defer {try? FileManager.default.removeItem(at:temp)}
        let registry=AgentRegistry(store:GUIIntegrationCredentials())
        let pairing=PairingCoordinator(registry:registry)
        let descriptor=try DiscoveryPublisher(directory:temp.appendingPathComponent("discovery"))
        let server=try LoopbackServer(host:host,registry:registry,pairing:pairing,instanceID:descriptor.instanceID,hostID:descriptor.hostID)
        let port=try await server.start();try descriptor.publish(port:port)
        defer {server.stop();descriptor.remove()}
        let process=Process(),output=Pipe();process.executableURL=URL(fileURLWithPath:"/Users/Marvin/Workspace/MyAgent/.venv/bin/python")
        process.arguments=[root.appendingPathComponent("tests/integration/myagent_native.py").path]
        var env=ProcessInfo.processInfo.environment;env["PYTHONDONTWRITEBYTECODE"]="1";env["MALTOSE_DISCOVERY"]=temp.appendingPathComponent("discovery").path;env["MALTOSE_STATE"]=temp.appendingPathComponent("agent").path
        env["MALTOSE_EXPECT_NODE"]="chart-gui";env["MALTOSE_EXPECT_VALUE"]="";env["MALTOSE_SURFACE"]="gui"
        process.environment=env;process.standardOutput=output;process.standardError=output;try process.run()
        defer {if process.isRunning {process.terminate()}}
        var approved=false,sent=false
        for _ in 0..<300 {
            if !process.isRunning {break}
            if !approved,let request=await pairing.pending().first {try await pairing.approve(request.id);approved=true}
            if !sent,!(await host.runtimeViews()).isEmpty {try await host.sendRuntimeInput(principal:owner,text:"來自原生 UI 的指令");sent=true}
            try await Task.sleep(for:.milliseconds(100))
        }
        if process.isRunning {XCTFail("Real chart-to-MyAgent pipeline timed out");return}
        let diagnostic=String(data:output.fileHandleForReading.readDataToEndOfFile(),encoding:.utf8) ?? ""
        XCTAssertEqual(process.terminationStatus,0,diagnostic);XCTAssertTrue(approved && sent)
        let runtime=await host.runtimeViews();XCTAssertTrue(runtime.contains {$0.messages.contains {$0.text.contains("已讀取選取區間")}})
    }

}
extension WKRendererTests {
    func testNativeDetachAttachAndPersistGeometry() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else {throw XCTSkip("Set MALTOSE_GUI_TESTS=1 in a macOS desktop session")}
        _ = NSApplication.shared
        let host=try HostState(path:":memory:"),sid=UUID().uuidString
        try await host.connect(principal:"agent.gui",sessionID:sid)
        func request(_ name:String,_ payload:JSON) throws->Data {
            try JSON.object(["protocol":.s(MUP.version),"message_id":.s(UUID().uuidString),"request_id":.s(UUID().uuidString),"session_id":.s(sid),"type":.s("command"),"name":.s(name),"payload":payload]).data()
        }
        let doc:JSON = .object(["root":.object(["node_id":.s("stable"),"type":.s("text"),"props":.object(["text":.s("Persistent native surface")])])])
        _ = await host.handle(try request("surface.create",.object(["surface_id":.s("native"),"title":.s("Window lifecycle test"),"document":doc])),principal:"agent.gui",sessionID:sid)
        _ = await host.handle(try request("surface.detach",.object(["surface_id":.s("native")])),principal:"agent.gui",sessionID:sid)
        let controller=HostController();controller.host=host;controller.surfaces=await host.surfacesForHost();controller.synchronizeWindows()
        let window=try XCTUnwrap(controller.windows["native"])
        defer {window.orderOut(nil);controller.windows.removeAll();controller.delegates.removeAll()}
        XCTAssertTrue(window.isVisible)
        window.setFrame(NSRect(x:210,y:180,width:880,height:560),display:true)
        try await Task.sleep(for:.milliseconds(300))
        let detached=await host.surfacesForHost()
        XCTAssertEqual(detached[0].placement["width"],.n(880))
        XCTAssertEqual(detached[0].document["root"]["node_id"],.s("stable"))
        window.performClose(nil) // user-close reattaches, does not destroy the surface
        try await Task.sleep(for:.milliseconds(250))
        controller.surfaces=await host.surfacesForHost();controller.synchronizeWindows()
        XCTAssertEqual(controller.surfaces[0].kind,"workspace")
        XCTAssertNil(controller.windows["native"])
    }
}

private final class GUIIntegrationCredentials:CredentialStore,@unchecked Sendable {
    private let lock=NSLock();private var values:[String:Data]=[:]
    func credentials() throws->[String:Data] {lock.lock();defer {lock.unlock()};return values}
    func save(principal:String,token:Data) throws {lock.lock();defer {lock.unlock()};values[principal]=token}
    func remove(principal:String) throws {lock.lock();defer {lock.unlock()};values.removeValue(forKey:principal)}
}
