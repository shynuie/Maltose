import XCTest
@testable import MaltoseCore
let sessionA = "00000000-0000-4000-8000-000000000001"
let sessionB = "00000000-0000-4000-8000-000000000002"
func command(_ name: String, _ payload: JSON = .object([:]), session: String = sessionA, request: String = UUID().uuidString, key: String? = nil) throws -> Data {
    var c: JSON = .object(["protocol":.s(MUP.version),"message_id":.s(UUID().uuidString),"session_id":.s(session),"request_id":.s(request),"type":.s("command"),"name":.s(name),"payload":payload])
    if let key { c["idempotency_key"] = .s(key) }
    return try c.data()
}
func sampleDocument() -> JSON { .object(["root":.object(["node_id":.s("chart"),"type":.s("chart.line"),"props":.object(["title":.s("Synthetic"),"points":.array([.array([.n(1),.n(10)]),.array([.n(2),.n(12)])])])])]) }
func createPayload(_ id: String = "market") -> JSON { .object(["surface_id":.s(id),"title":.s("Market"),"document":sampleDocument()]) }
func makeHost() async throws -> HostState { let h = try HostState(path: ":memory:"); try await h.connect(principal: "agent.a", sessionID: sessionA); try await h.connect(principal: "agent.b", sessionID: sessionB); return h }
final class HostTests: XCTestCase, @unchecked Sendable {
    func testOwnershipAndDuplicates() async throws {
        let h = try await makeHost()
        let req = try command("surface.create", createPayload())
        let first = await h.handle(req, principal: "agent.a", sessionID: sessionA)
        let second = await h.handle(req, principal: "agent.a", sessionID: sessionA)
        try SchemaValidator(name:"surface").validate(first["result"])
        XCTAssertEqual(first,second); XCTAssertEqual(first["ok"],.bool(true))
        let forbidden = await h.handle(try command("surface.get",.object(["surface_id":.s("market")]),session:sessionB),principal:"agent.b",sessionID:sessionB)
        XCTAssertEqual(forbidden["error"]["code"],.s("forbidden"))
        let bad = await h.handle(try command("surface.list",request:try JSON.decode(req)["request_id"].string!),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(bad["error"]["code"],.s("duplicate_request"))
    }
    func testDurabilityAndSessionBoundary() async throws {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".sqlite").path
        defer { for suffix in ["","-wal","-shm"] { try? FileManager.default.removeItem(atPath:path+suffix) } }
        let h = try HostState(path:path); try await h.connect(principal:"agent.a",sessionID:sessionA)
        let result = await h.handle(try command("surface.create", createPayload()),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(result["ok"],.bool(true))
        let restored = try HostState(path:path)
        let surfaces = await restored.surfacesForHost()
        XCTAssertEqual(surfaces.count,1)
        let forged = await h.handle(try command("surface.list",session:sessionB),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(forged["error"]["code"],.s("unauthenticated"))
    }
    func testValidationBeforeMutation() async throws {
        let h = try await makeHost()
        var p = createPayload(); p["owner_agent_id"] = .s("agent.b")
        let result = await h.handle(try command("surface.create",p),principal:"agent.a",sessionID:sessionA)
        XCTAssertEqual(result["ok"],.bool(false))
        let surfaces = await h.surfacesForHost(); XCTAssertTrue(surfaces.isEmpty)
    }
}
