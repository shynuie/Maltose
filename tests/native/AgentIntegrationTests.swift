import XCTest
@testable import MaltoseCore
final class AgentIntegrationTests:XCTestCase,@unchecked Sendable {
    func testPairingProofDenialAndSingleClaim() async throws {
        let registry=AgentRegistry(store:MemoryCredentials())
        let pairing=PairingCoordinator(registry:registry)
        let claim=String(repeating:"x",count:40)
        let request=try await pairing.request(name:"Test",agentID:"agent.pair",claim:claim)
        let id=request["pairing_id"].string!
        do {_ = try await pairing.poll(id:id,claim:String(repeating:"z",count:40));XCTFail("Wrong claim accepted")} catch {}
        try await pairing.approve(id)
        let approved=try await pairing.poll(id:id,claim:claim)
        XCTAssertEqual(approved["status"],.s("approved"));XCTAssertNotNil(approved["token"].string)
        let again=try await pairing.poll(id:id,claim:claim);XCTAssertNil(again["token"].string)
        let pending=try await pairing.request(name:"Other",agentID:"agent.other",claim:String(repeating:"y",count:40))
        await pairing.deny(pending["pairing_id"].string!)
        let denied=try await pairing.poll(id:pending["pairing_id"].string!,claim:String(repeating:"y",count:40));XCTAssertEqual(denied["status"],.s("denied"))
    }
    func testRuntimeOverlapSequenceInputAndIsolation() async throws {
        let host=try await makeHost(),run=UUID().uuidString
        func publish(_ sequence:Int,_ event:String,_ data:JSON = .object([:])) async throws->JSON {
            await host.handle(try command("agent.runtime.publish",.object(["run_id":.s(run),"sequence":.n(sequence),"event":.s(event),"data":data])),principal:"agent.a",sessionID:sessionA)
        }
        _ = try await publish(0,"state_changed",.object(["state":.s("thinking")]))
        _ = try await publish(1,"model_started");_ = try await publish(2,"speech_started")
        let runtime=await host.runtimeViews();XCTAssertTrue(runtime[0].modelActive && runtime[0].speechActive)
        let duplicate=try await publish(2,"model_finished");XCTAssertEqual(duplicate["error"]["code"],.s("duplicate_event"))
        try await host.sendRuntimeInput(principal:"agent.a",text:"指令")
        let foreign=await host.handle(try command("agent.input.poll",session:sessionB),principal:"agent.b",sessionID:sessionB);XCTAssertEqual(foreign["result"],.array([]))
        let own=await host.handle(try command("agent.input.poll"),principal:"agent.a",sessionID:sessionA);XCTAssertEqual(own["result"].array?[0]["text"],.s("指令"))
        await host.disconnect(sessionID:sessionA)
        let offline=await host.runtimeViews();XCTAssertFalse(offline[0].connected)
    }
    func testDiscoveryDynamicPortAndStableHostIdentity() async throws {
        let dir=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer {try? FileManager.default.removeItem(at:dir)}
        let first=try DiscoveryPublisher(directory:dir.appendingPathComponent("discovery"))
        let second=try DiscoveryPublisher(directory:dir.appendingPathComponent("discovery"))
        XCTAssertEqual(first.hostID,second.hostID);XCTAssertNotEqual(first.instanceID,second.instanceID)
        try first.publish(port:49123)
        let files=try FileManager.default.contentsOfDirectory(at:dir.appendingPathComponent("discovery"),includingPropertiesForKeys:nil)
        XCTAssertEqual(files.count,1)
        let record=try JSON.decode(Data(contentsOf:files[0]));XCTAssertEqual(record["endpoint"],.s("ws://127.0.0.1:49123"))
        let permissions=try FileManager.default.attributesOfItem(atPath:files[0].path)[.posixPermissions] as? Int;XCTAssertEqual(permissions,0o600)
        first.remove();XCTAssertFalse(FileManager.default.fileExists(atPath:files[0].path))
    }
    func testActualSignedToolkitUvSidecarAndMyAgent() async throws {
        let root=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let python="/Users/Marvin/Workspace/MyAgent/.venv/bin/python"
        guard FileManager.default.isExecutableFile(atPath:python) else {throw XCTSkip("MyAgent environment not present")}
        let temp=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:temp,withIntermediateDirectories:true)
        defer {try? FileManager.default.removeItem(at:temp)}
        let toolkit=try ToolkitArtifact(directory:root.appendingPathComponent("apps/macos/MaltoseApp/Resources/toolkit"))
        let host=try HostState(path:":memory:",toolkit:toolkit),registry=AgentRegistry(store:MemoryCredentials())
        let pairing=PairingCoordinator(registry:registry),discovery=try DiscoveryPublisher(directory:temp.appendingPathComponent("discovery"))
        let server=try LoopbackServer(host:host,registry:registry,pairing:pairing,instanceID:discovery.instanceID,hostID:discovery.hostID)
        let port=try await server.start();defer {server.stop();discovery.remove()}
        try discovery.publish(port:port)
        let owner="agent.myagent-e2e",local=UUID().uuidString
        try await host.connect(principal:owner,sessionID:local)
        var payload=createPayload("e2e-chart")
        payload["document"] = .object(["root":.object(["node_id":.s("selected-chart"),"type":.s("chart.line"),"props":.object(["points":.array([])])])])
        _ = await host.handle(try command("surface.create",payload,session:local),principal:owner,sessionID:local)
        await host.openBridge(surfaceID:"e2e-chart",epoch:"e2e");await host.nativeFocus(surfaceID:"e2e-chart")
        var selection=bridge(surface:"e2e-chart",node:"selected-chart");selection["selection"]["node_id"] = .s("selected-chart")
        try await host.acceptBridge(selection,boundSurface:"e2e-chart",epoch:"e2e")
        let process=Process(),output=Pipe();process.executableURL=URL(fileURLWithPath:python);process.arguments=[root.appendingPathComponent("tests/integration/myagent_native.py").path]
        var env=ProcessInfo.processInfo.environment;env["PYTHONDONTWRITEBYTECODE"]="1";env["MALTOSE_DISCOVERY"]=temp.appendingPathComponent("discovery").path;env["MALTOSE_STATE"]=temp.appendingPathComponent("agent").path
        process.environment=env;process.standardOutput=output;process.standardError=output
        try process.run()
        var approved=false,sent=false,sawModel=false,sawSpeech=false
        for _ in 0..<350 {
            if !process.isRunning {break}
            if !approved,let request=await pairing.pending().first {try await pairing.approve(request.id);approved=true}
            // A live bound renderer refreshes observation freshness without fabricating new selections.
            _ = try await host.rendererSnapshot(surfaceID:"e2e-chart",epoch:"e2e")
            let observed=await host.runtimeViews()
            sawModel = sawModel || observed.contains {$0.modelActive}
            sawSpeech = sawSpeech || observed.contains {$0.speechActive}
            if !sent,!observed.isEmpty {try await host.sendRuntimeInput(principal:owner,text:"來自原生 UI 的指令");sent=true}
            try await Task.sleep(for:.milliseconds(100))
        }
        if process.isRunning {process.terminate();XCTFail("MyAgent sidecar test timed out");return}
        let diagnostic=String(data:output.fileHandleForReading.readDataToEndOfFile(),encoding:.utf8) ?? ""
        XCTAssertEqual(process.terminationStatus,0,diagnostic);XCTAssertTrue(approved && sent);XCTAssertTrue(sawModel,"No real model-start event observed");XCTAssertTrue(sawSpeech,"No actual playback/synthesis event observed")
        let runtimes=await host.runtimeViews();XCTAssertTrue(runtimes.contains {$0.id == owner && $0.messages.contains {$0.text.contains("已讀取選取區間")}})
        let surfaces=await host.surfacesForHost();XCTAssertEqual(surfaces[0].kind,"window")
    }
    func testRestartChangedPortReconnectAndRevocation() async throws {
        let root=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let temp=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:temp,withIntermediateDirectories:true)
        defer {try? FileManager.default.removeItem(at:temp)}
        let toolkit=try ToolkitArtifact(directory:root.appendingPathComponent("apps/macos/MaltoseApp/Resources/toolkit"))
        let host=try HostState(path:":memory:",toolkit:toolkit),registry=AgentRegistry(store:MemoryCredentials())
        let pairing=PairingCoordinator(registry:registry),discovery=try DiscoveryPublisher(directory:temp.appendingPathComponent("discovery"))
        let first=try LoopbackServer(host:host,registry:registry,pairing:pairing,instanceID:discovery.instanceID,hostID:discovery.hostID)
        let firstPort=try await first.start();defer {first.stop();discovery.remove()}
        try discovery.publish(port:firstPort)
        let process=Process(),output=Pipe();process.executableURL=root.appendingPathComponent(".venv/bin/python")
        process.arguments=[root.appendingPathComponent("tests/integration/bootstrap_reconnect.py").path]
        var env=ProcessInfo.processInfo.environment;env["PYTHONDONTWRITEBYTECODE"]="1";env["MALTOSE_DISCOVERY"]=temp.appendingPathComponent("discovery").path;env["MALTOSE_STATE"]=temp.appendingPathComponent("agent").path
        process.environment=env;process.standardOutput=output;process.standardError=output;try process.run()
        var replacement:LoopbackServer?,replacementDiscovery:DiscoveryPublisher?,approved=false,revoked=false
        defer {replacement?.stop();replacementDiscovery?.remove();if process.isRunning {process.terminate()}}
        for _ in 0..<350 {
            if !process.isRunning {break}
            if !approved,let request=await pairing.pending().first {try await pairing.approve(request.id);approved=true}
            if replacement == nil,FileManager.default.fileExists(atPath:temp.appendingPathComponent("agent/connected-1").path) {
                // Keep the old listener occupied until the new port is assigned, proving a changed port.
                let descriptor=try DiscoveryPublisher(directory:temp.appendingPathComponent("discovery"))
                let next=try LoopbackServer(host:host,registry:registry,pairing:pairing,instanceID:descriptor.instanceID,hostID:descriptor.hostID)
                let nextPort=try await next.start();XCTAssertNotEqual(firstPort,nextPort)
                first.stop();discovery.remove();try descriptor.publish(port:nextPort)
                replacement=next;replacementDiscovery=descriptor
            }
            if !revoked,FileManager.default.fileExists(atPath:temp.appendingPathComponent("agent/connected-2").path) {try await registry.revoke("agent.reconnect");revoked=true}
            try await Task.sleep(for:.milliseconds(100))
        }
        if process.isRunning {process.terminate();XCTFail("Reconnect/revocation timed out");return}
        let diagnostic=String(data:output.fileHandleForReading.readDataToEndOfFile(),encoding:.utf8) ?? ""
        XCTAssertEqual(process.terminationStatus,0,diagnostic);XCTAssertTrue(approved && revoked)
    }
    func testPairingCannotRotateExistingPrincipal() async throws {
        let registry=AgentRegistry(store:MemoryCredentials()),claim=String(repeating:"k",count:40)
        let token=try await registry.register("agent.existing"),pairing=PairingCoordinator(registry:registry)
        let request=try await pairing.request(name:"Impersonator",agentID:"agent.existing",claim:claim)
        do {try await pairing.approve(request["pairing_id"].string!);XCTFail("Existing credential rotated")} catch let e as MUPError {XCTAssertEqual(e.code,"principal_exists")}
        let principal=try await registry.authenticate(token);XCTAssertEqual(principal,"agent.existing")
        let response=try await pairing.poll(id:request["pairing_id"].string!,claim:claim);XCTAssertEqual(response["status"],.s("denied"));XCTAssertNil(response["token"].string)
    }

}
