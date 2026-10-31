import XCTest
@testable import MaltoseCore
final class PatchTests: XCTestCase, @unchecked Sendable {
    func testAtomicRevisionAndInvalidPatch() async throws {
        let h = try await makeHost()
        _ = await h.handle(try command("surface.create",createPayload()),principal:"agent.a",sessionID:sessionA)
        let title: JSON = .object(["op":.s("set_props"),"node_id":.s("chart"),"props":.object(["title":.s("Updated")])])
        var p: JSON = .object(["surface_id":.s("market"),"expected_revision":.n(1),"operations":.array([title])])
        let good = await h.handle(try command("ui.patch",p),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(good["result"]["revision"],.n(2))
        let stale = await h.handle(try command("ui.patch",p),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(stale["error"]["code"],.s("revision_conflict"))
        p["expected_revision"] = .n(2)
        p["operations"] = .array([title,.object(["op":.s("remove_node"),"node_id":.s("absent")])])
        let invalid = await h.handle(try command("ui.patch",p),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(invalid["ok"],.bool(false))
        let surfaces = await h.surfacesForHost(); XCTAssertEqual(surfaces[0].revision,2)
    }
    func testTypedTreeOperationsAndIdentity() throws {
        var doc = sampleDocument()
        doc["root"] = .object(["node_id":.s("root"),"type":.s("stack"),"props":.object([:]),"children":.array([doc["root"]])])
        let text: JSON = .object(["node_id":.s("label"),"type":.s("text"),"props":.object(["text":.s("Hi")])])
        let patched = try Document.patch(doc,operations:[.object(["op":.s("insert_node"),"parent_id":.s("root"),"index":.n(0),"node":text]),.object(["op":.s("move_node"),"node_id":.s("chart"),"parent_id":.s("root"),"index":.n(0)])])
        XCTAssertEqual(patched["root"]["children"].array?[0]["node_id"],.s("chart"))
        XCTAssertThrowsError(try Document.patch(patched,operations:[.object(["op":.s("move_node"),"node_id":.s("root"),"parent_id":.s("root"),"index":.n(0)])]))
    }
}
