import XCTest
@testable import MaltoseCore
final class LifecycleTests:XCTestCase,@unchecked Sendable {
    func testDetachAttachKeepsSelectionViewportAndStream() async throws {
        let h=try await preparedHost()
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        try await h.acceptBridge(bridge("viewport_changed",sequence:2),boundSurface:"market",epoch:"epoch")
        _ = await h.handle(try command("data.register",.object(["data_id":.s("prices")])),principal:"agent.a",sessionID:sessionA)
        let before=try await h.contextSnapshot(principal:"agent.a")
        for name in ["surface.detach","surface.attach"] {
            let reply=await h.handle(try command(name,.object(["surface_id":.s("market")])),principal:"agent.a",sessionID:sessionA)
            XCTAssertEqual(reply["ok"],.bool(true))
            await h.openBridge(surfaceID:"market",epoch:name)
            let after=try await h.contextSnapshot(principal:"agent.a")
            XCTAssertEqual(before["surfaces"].array![0]["selection"],after["surfaces"].array![0]["selection"])
            XCTAssertEqual(before["surfaces"].array![0]["viewport"],after["surfaces"].array![0]["viewport"])
            XCTAssertEqual(after["surfaces"].array![0]["document_revision"],.n(1))
        }
        let data=await h.handle(try command("data.publish",.object(["data_id":.s("prices"),"sequence":.n(1),"points":.array([.array([.n(1),.n(20)])])])),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(data["ok"],.bool(true))
    }
    func testRestartRestoresLayoutAndZoomButNoFocusOrSelection() async throws {
        let path=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString+".sqlite").path
        defer {for suffix in ["","-wal","-shm"] {try? FileManager.default.removeItem(atPath:path+suffix)}}
        let h=try HostState(path:path);try await h.connect(principal:"agent.a",sessionID:sessionA)
        _ = await h.handle(try command("surface.create",createPayload()),principal:"agent.a",sessionID:sessionA)
        await h.openBridge(surfaceID:"market",epoch:"epoch");await h.nativeFocus(surfaceID:"market")
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        try await h.acceptBridge(bridge("viewport_changed",sequence:2),boundSurface:"market",epoch:"epoch")
        try await h.updateLayout(surfaceID:"market",placement:.object(["x":.n(100),"y":.n(80),"width":.n(900),"height":.n(600),"screen_id":.s("screen-1")]))
        _ = await h.handle(try command("surface.detach",.object(["surface_id":.s("market")])),principal:"agent.a",sessionID:sessionA)
        let restored=try HostState(path:path)
        let snapshot=try await restored.contextSnapshot(principal:"agent.a")
        XCTAssertEqual(snapshot["focused_surface_id"],.null)
        XCTAssertEqual(snapshot["surfaces"].array![0]["selection"],.null)
        XCTAssertEqual(snapshot["surfaces"].array![0]["stale"],.bool(true))
        let surfaces=await restored.surfacesForHost();XCTAssertEqual(surfaces[0].kind,"window");XCTAssertEqual(surfaces[0].placement["width"],.n(900))
        let renderer=try await restored.rendererSnapshot(surfaceID:"market")
        XCTAssertNotEqual(renderer["viewport"],.null)
    }
    func testReconnectGapsAndRevocationTerminateSubscriptions() async throws {
        let h=try await preparedHost()
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[.summary,.selection])
        let reply=await h.handle(try command("ui.context.subscribe",session:sessionB),principal:"agent.b",sessionID:sessionB)
        XCTAssertEqual(reply["ok"],.bool(true))
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[])
        let events=await h.drainEvents(principal:"agent.b",sessionID:sessionB)
        XCTAssertEqual(events.count,1);XCTAssertEqual(events[0]["name"],.s("context.permission_changed"));XCTAssertEqual(events[0]["surface_id"],.null)
        let sid=reply["result"]["subscription_id"]
        let unsub=await h.handle(try command("ui.context.unsubscribe",.object(["subscription_id":sid]),session:sessionB),principal:"agent.b",sessionID:sessionB)
        XCTAssertEqual(unsub["error"]["code"],.s("forbidden"))
        let fresh=await h.handle(try command("ui.context.get",.object(["since_context_revision":.n(0)])),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(fresh["result"]["resync_required"],.bool(true))
    }
}
