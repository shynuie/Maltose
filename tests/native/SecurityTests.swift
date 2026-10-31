import XCTest
@testable import MaltoseCore
final class SecurityTests:XCTestCase,@unchecked Sendable {
    func testEventBackpressureRequiresSnapshotAndDoesNotLeak() async throws {
        let h=try await preparedHost()
        _ = await h.handle(try command("ui.context.subscribe"),principal:"agent.a",sessionID:sessionA)
        _ = await h.handle(try command("ui.context.subscribe",session:sessionB),principal:"agent.b",sessionID:sessionB)
        for i in 1...140 {try await h.acceptBridge(bridge(sequence:i),boundSurface:"market",epoch:"epoch")}
        let own=await h.drainEvents(principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(own.count,1);XCTAssertEqual(own[0]["name"],.s("context.stale"));XCTAssertEqual(own[0]["changes"]["resync_required"],.bool(true))
        let other=await h.drainEvents(principal:"agent.b",sessionID:sessionB);XCTAssertTrue(other.isEmpty)
    }
    func testPrivateChangesDoNotIncrementOtherPrincipalRevision() async throws {
        let h=try await preparedHost()
        let before=try await h.contextSnapshot(principal:"agent.b")
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        let after=try await h.contextSnapshot(principal:"agent.b")
        XCTAssertEqual(before["context_revision"],after["context_revision"])
    }
    func testRevokedReadCannotBeReplayedFromRequestCache() async throws {
        let h=try await preparedHost()
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[.document])
        let request=try command("surface.get",.object(["surface_id":.s("market")]),session:sessionB)
        let before=await h.handle(request,principal:"agent.b",sessionID:sessionB);XCTAssertEqual(before["ok"],.bool(true))
        try await h.setGrant(surfaceID:"market",grantee:"agent.b",scopes:[])
        let after=await h.handle(request,principal:"agent.b",sessionID:sessionB);XCTAssertEqual(after["error"]["code"],.s("forbidden"))
    }
    func testSensitiveNodesNeverEnterAwareness() async throws {
        let h=try await preparedHost()
        try await h.acceptBridge(bridge(),boundSurface:"market",epoch:"epoch")
        let patch:JSON = .object(["surface_id":.s("market"),"expected_revision":.n(1),"operations":.array([.object(["op":.s("set_props"),"node_id":.s("chart"),"props":.object(["sensitive":.bool(true),"text":.s("do-not-expose")])])])])
        _ = await h.handle(try command("ui.patch",patch),principal:"agent.a",sessionID:sessionA)
        do {try await h.acceptBridge(bridge(revision:2),boundSurface:"market",epoch:"epoch");XCTFail("Sensitive selection accepted")} catch {}
        let snapshot=try await h.contextSnapshot(principal:"agent.a")
        XCTAssertEqual(snapshot["surfaces"].array![0]["visible_nodes"],.array([]))
        XCTAssertEqual(snapshot["surfaces"].array![0]["selection"],.null)
        XCTAssertFalse(String(data:try snapshot.data(),encoding:.utf8)!.contains("do-not-expose"))
    }
    func testIdempotencyAcrossSessionsAndPayloadMismatch() async throws {
        let h=try await makeHost();let key=UUID().uuidString
        let a=await h.handle(try command("surface.create",createPayload(),key:key),principal:"agent.a",sessionID:sessionA)
        let session=UUID().uuidString;try await h.connect(principal:"agent.a",sessionID:session)
        let repeated=await h.handle(try command("surface.create",createPayload(),session:session,key:key),principal:"agent.a",sessionID:session)
        XCTAssertEqual(a["result"],repeated["result"])
        let wrong=await h.handle(try command("surface.create",createPayload("other"),session:session,key:key),principal:"agent.a",sessionID:session)
        XCTAssertEqual(wrong["error"]["code"],.s("duplicate_request"))
    }
}
extension SecurityTests {
    func testCredentialRotationAndRevocation() async throws {
        let registry=AgentRegistry(store:MemoryCredentials())
        let first=try await registry.register("agent.test")
        let second=try await registry.register("agent.test")
        XCTAssertNotEqual(first,second)
        do {_ = try await registry.authenticate(first);XCTFail("Rotated token accepted")} catch {}
        let principal=try await registry.authenticate(second);XCTAssertEqual(principal,"agent.test")
        try await registry.revoke("agent.test")
        do {_ = try await registry.authenticate(second);XCTFail("Revoked token accepted")} catch {}
    }
}
