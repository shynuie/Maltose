import XCTest
@testable import MaltoseCore
func bridge(_ kind:String = "selection_changed", surface:String = "market", sequence:Int = 1, revision:Int = 1, node:String = "chart") -> JSON {
    var m: JSON = .object(["surface_id":.s(surface),"document_revision":.n(revision),"sequence":.n(sequence),"kind":.s(kind),"node_id":.s(node)])
    if kind == "selection_changed" {m["selection"] = .object(["node_id":.s(node),"kind":.s("chart.time_range"),"value":.object(["start":.s("2026-10-01"),"end":.s("2026-10-15")])])}
    if kind == "viewport_changed" {m["viewport"] = .object(["node_id":.s(node),"x_domain":.array([.s("2026-10-01"),.s("2026-10-15")])])}
    return m
}
func preparedHost() async throws -> HostState {
    let h=try await makeHost()
    _ = await h.handle(try command("surface.create",createPayload()),principal:"agent.a",sessionID:sessionA)
    await h.openBridge(surfaceID:"market",epoch:"epoch")
    await h.nativeFocus(surfaceID:"market")
    return h
}
final class AwarenessTests:XCTestCase,@unchecked Sendable {
    func testSelectionViewportAndReferenceEvidence() async throws {
        let h=try await preparedHost()
        let subscribed=await h.handle(try command("ui.context.subscribe"),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(subscribed["ok"],.bool(true))
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        try await h.acceptBridge(bridge("viewport_changed",sequence:2),boundSurface:"market",epoch:"epoch")
        let snapshot=try await h.contextSnapshot(principal:"agent.a")
        try SchemaValidator(name:"context").validate(snapshot)
        let model=try await h.typedContext(principal:"agent.a")
        XCTAssertEqual(model.focusedNodeID,"chart")
        XCTAssertEqual(model.surfaces[0].selection?.kind,.chartTimeRange)
        XCTAssertEqual(snapshot["focused_node_id"],.s("chart"))
        XCTAssertEqual(snapshot["surfaces"].array![0]["selection"]["value"]["start"],.s("2026-10-01"))
        XCTAssertEqual(snapshot["surfaces"].array![0]["document_revision"],.n(1))
        let resolved=try await h.resolveReference(principal:"agent.a",query:.object(["phrase":.s("this chart")]))
        XCTAssertEqual(resolved["candidates"].array![0]["node_id"],.s("chart"))
        XCTAssertTrue(resolved["candidates"].array![0]["evidence"].array!.contains(.s("native_focus")))
        let events=await h.drainEvents(principal:"agent.a",sessionID:sessionA)
        XCTAssertTrue(events.contains {$0["name"] == .s("context.viewport_changed")})
        for event in events {try SchemaValidator(name:"event").validate(event)}
        do {try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch");XCTFail("duplicate accepted")} catch let e as MUPError {XCTAssertEqual(e.code,"duplicate_event")}
    }
    func testSummaryRedactionRevocationAndNoPrivateFocusLeak() async throws {
        let h=try await preparedHost()
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        let privateSnapshot=try await h.contextSnapshot(principal:"agent.b")
        XCTAssertEqual(privateSnapshot["surfaces"],.array([]));XCTAssertEqual(privateSnapshot["focused_surface_id"],.null)
        let resolved=try await h.resolveReference(principal:"agent.b",query:.object(["phrase":.s("this chart")]))
        XCTAssertEqual(resolved["candidates"],.array([]))
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[.summary])
        let summary=try await h.contextSnapshot(principal:"agent.b")
        let s=summary["surfaces"].array![0]
        XCTAssertNil(s.object?["selection"]);XCTAssertNil(s.object?["viewport"]);XCTAssertNil(s.object?["visible_nodes"])
        XCTAssertEqual(summary["focused_node_id"],.null)
        _ = await h.handle(try command("ui.context.subscribe",session:sessionB),principal:"agent.b",sessionID:sessionB)
        try await h.acceptBridge(bridge(sequence:2),boundSurface:"market",epoch:"epoch")
        let events=await h.drainEvents(principal:"agent.b",sessionID:sessionB)
        XCTAssertTrue(events.isEmpty)
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[])
        let after=try await h.contextSnapshot(principal:"agent.b");XCTAssertEqual(after["surfaces"],.array([]))
        try await h.acceptBridge(bridge(sequence:3),boundSurface:"market",epoch:"epoch")
        let drained=await h.drainEvents(principal:"agent.b",sessionID:sessionB)
        XCTAssertFalse(drained.contains {$0["surface_id"] == .s("market")})
    }
    func testAmbiguityAndStaleReferences() async throws {
        let h=try await preparedHost()
        _ = await h.handle(try command("surface.create",createPayload("second")),principal:"agent.a",sessionID:sessionA)
        await h.openBridge(surfaceID:"second",epoch:"other")
        await h.nativeFocus(surfaceID:nil)
        let result=try await h.resolveReference(principal:"agent.a",query:.object(["phrase":.s("the chart")]))
        XCTAssertEqual(result["ambiguous"],.bool(true))
        let stale=try await h.resolveReference(principal:"agent.a",query:.object(["phrase":.s("this chart"),"max_age_ms":.n(0)]))
        XCTAssertEqual(stale["candidates"],.array([]));XCTAssertEqual(stale["requires_clarification"],.bool(true))
    }
    func testCrossAgentFocusEventRedaction() async throws {
        let h=try await preparedHost()
        _ = await h.handle(try command("ui.context.subscribe"),principal:"agent.a",sessionID:sessionA)
        _ = await h.handle(try command("surface.create",createPayload("private-b"),session:sessionB),principal:"agent.b",sessionID:sessionB)
        await h.nativeFocus(surfaceID:"private-b")
        let events=await h.drainEvents(principal:"agent.a",sessionID:sessionA)
        for event in events {
            XCTAssertNotEqual(event["surface_id"],.s("private-b"))
            XCTAssertNotEqual(event["changes"]["focused_surface_id"],.s("private-b"))
        }
    }
    func testBridgeCannotForgeSurfaceOrActions() async throws {
        let h=try await preparedHost()
        do {try await h.acceptBridge(bridge(surface:"private"),boundSurface:"market",epoch:"epoch");XCTFail()} catch {}
        do {try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"old");XCTFail()} catch {}
        var invalid=bridge("action");invalid["action_id"] = .s("shell.exec")
        do {try await h.acceptBridge(invalid,boundSurface:"market",epoch:"epoch");XCTFail()} catch {}
    }
    func testLiveRendererKeepsStableSelectionFreshWithoutInventingInteraction() async throws {
        let h=try await preparedHost()
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        let before=try await h.contextSnapshot(principal:"agent.a")
        try await Task.sleep(for:.milliseconds(40))
        let stale=try await h.contextSnapshot(principal:"agent.a",filters:.object(["max_age_ms":.n(10)]));XCTAssertEqual(stale["fresh"],.bool(false))
        do {_ = try await h.rendererSnapshot(surfaceID:"market",epoch:"old");XCTFail("Old renderer refreshed context")} catch {}
        _ = try await h.rendererSnapshot(surfaceID:"market",epoch:"epoch")
        let after=try await h.contextSnapshot(principal:"agent.a",filters:.object(["max_age_ms":.n(30)]))
        XCTAssertEqual(after["fresh"],.bool(true));XCTAssertEqual(after["context_revision"],before["context_revision"])
        XCTAssertEqual(after["surfaces"].array![0]["selection"],before["surfaces"].array![0]["selection"])
        XCTAssertEqual(after["surfaces"].array![0]["interaction"],before["surfaces"].array![0]["interaction"])
    }

}
