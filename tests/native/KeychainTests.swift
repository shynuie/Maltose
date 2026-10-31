import XCTest
@testable import MaltoseCore
final class KeychainTests:XCTestCase,@unchecked Sendable {
    func testIsolatedKeychainRegistrationRotationRevocation() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_KEYCHAIN_TESTS"] == "1" else {throw XCTSkip("Set MALTOSE_KEYCHAIN_TESTS=1 to test a temporary isolated Keychain service")}
        let store=KeychainCredentials(service:"local.maltose.test."+UUID().uuidString)
        let registry=AgentRegistry(store:store)
        defer {try? store.remove(principal:"agent.keychain-test")}
        let first=try await registry.register("agent.keychain-test")
        let authenticated=try await registry.authenticate(first);XCTAssertEqual(authenticated,"agent.keychain-test")
        let second=try await registry.register("agent.keychain-test")
        XCTAssertNotEqual(first,second)
        do {_ = try await registry.authenticate(first);XCTFail("Old credential accepted")} catch {}
        let current=try await registry.authenticate(second);XCTAssertEqual(current,"agent.keychain-test")
        try await registry.revoke("agent.keychain-test")
        XCTAssertTrue(try store.credentials().isEmpty)
    }
}
