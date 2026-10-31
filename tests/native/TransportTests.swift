import Foundation
import XCTest
@testable import MaltoseCore
final class MemoryCredentials:CredentialStore,@unchecked Sendable {
    private let lock=NSLock();private var values:[String:Data]=[:]
    func credentials() throws->[String:Data] {lock.lock();defer {lock.unlock()};return values}
    func save(principal:String,token:Data) throws {lock.lock();defer {lock.unlock()};values[principal]=token}
    func remove(principal:String) throws {lock.lock();defer {lock.unlock()};values.removeValue(forKey:principal)}
}
final class TransportTests:XCTestCase,@unchecked Sendable {
    func testRealLoopbackWebSocketAuthAndRevocation() async throws {
        let registry=AgentRegistry(store:MemoryCredentials())
        let token=try await registry.register("agent.a")
        let h=try HostState(path:":memory:")
        let server=try LoopbackServer(host:h,registry:registry)
        let port=try await server.start();defer {server.stop()}
        let session=URLSession(configuration:.ephemeral)
        let ws=session.webSocketTask(with:URL(string:"ws://127.0.0.1:\(port)")!);ws.resume()
        defer {ws.cancel(with:.normalClosure,reason:nil);session.invalidateAndCancel()}
        try await ws.send(.data(try command("host.authenticate",.object(["token":.s(token)]))))
        // SDKs send text; verify binary messages cannot cross the trust boundary.
        do {_ = try await ws.receive();XCTFail("Binary accepted")} catch {}
        let text=session.webSocketTask(with:URL(string:"ws://127.0.0.1:\(port)")!);text.resume()
        defer {text.cancel(with:.normalClosure,reason:nil)}
        let auth=try command("host.authenticate",.object(["token":.s(token)]))
        try await text.send(.string(String(data:auth,encoding:.utf8)!))
        let raw=try await text.receive()
        guard case .string(let string)=raw else {return XCTFail("Expected text response")}
        let reply=try JSON.decode(Data(string.utf8));XCTAssertEqual(reply["ok"],.bool(true))
        let sid=reply["result"]["session_id"].string!
        try await text.send(.string(String(data:command("surface.create",createPayload(),session:sid),encoding:.utf8)!))
        guard case .string(let created)=try await text.receive() else {return XCTFail()}
        XCTAssertEqual(try JSON.decode(Data(created.utf8))["result"]["owner_agent_id"],.s("agent.a"))
        try await registry.revoke("agent.a")
        try await Task.sleep(for:.milliseconds(100))
        do {_ = try await text.receive();XCTFail("Revoked connection remains open")} catch {}
    }
    func testBrowserOriginsRejected() async throws {
        let server=try LoopbackServer(host:HostState(path:":memory:"),registry:AgentRegistry(store:MemoryCredentials()))
        let port=try await server.start();defer {server.stop()}
        var request=URLRequest(url:URL(string:"ws://127.0.0.1:\(port)")!);request.setValue("https://untrusted.example",forHTTPHeaderField:"Origin")
        let session=URLSession(configuration:.ephemeral)
        defer {session.invalidateAndCancel()}
        let ws=session.webSocketTask(with:request);ws.resume()
        do {_ = try await ws.receive();XCTFail("Origin accepted")} catch {}
    }
}
extension TransportTests {
    func testPythonAndTypeScriptSDKAgainstNativeHost() async throws {
        let registry=AgentRegistry(store:MemoryCredentials())
        let a=try await registry.register("agent.a"),b=try await registry.register("agent.b")
        let h=try await preparedHost()
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[.summary])
        let server=try LoopbackServer(host:h,registry:registry)
        let port=try await server.start();defer {server.stop()}
        let root=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        for (binary,script) in [(root.appendingPathComponent(".venv/bin/python").path,"native_sdk.py"),("/usr/bin/env","native_sdk.mjs")] {
            guard FileManager.default.isExecutableFile(atPath:binary) else {throw XCTSkip("Install Python SDK tests and Node before interoperability tests")}
            let process=Process(),output=Pipe()
            process.executableURL=URL(fileURLWithPath:binary)
            process.arguments=(script.hasSuffix(".mjs") ? ["node"] : [])+[root.appendingPathComponent("tests/integration/"+script).path]
            var env=ProcessInfo.processInfo.environment
            env["MALTOSE_TEST_PORT"]=String(port);env["MALTOSE_TEST_A"]=a;env["MALTOSE_TEST_B"]=b
            process.environment=env;process.standardOutput=output;process.standardError=output
            try process.run()
            for _ in 0..<150 {if !process.isRunning {break};try await Task.sleep(for:.milliseconds(100))}
            if process.isRunning {process.terminate();XCTFail("SDK process timed out");return}
            let text=String(data:output.fileHandleForReading.readDataToEndOfFile(),encoding:.utf8) ?? ""
            XCTAssertEqual(process.terminationStatus,0,text)
        }
    }
}
