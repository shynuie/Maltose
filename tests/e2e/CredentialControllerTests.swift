import XCTest
import MaltoseCore
@testable import MaltoseApp
private struct UnavailableCredentials:CredentialStore {
    func credentials() throws->[String:Data] {throw MUPError("keychain","Credential store unavailable (OSStatus -50)")}
    func save(principal:String,token:Data) throws {throw MUPError("keychain","Unavailable")}
    func remove(principal:String) throws {throw MUPError("keychain","Unavailable")}
}
@MainActor final class CredentialControllerTests:XCTestCase {
    func testFailureExplainsCauseWithoutOverwritingConnectionStatus() async {
        let controller=HostController(registry:AgentRegistry(store:UnavailableCredentials()))
        controller.status="已連線 · 127.0.0.1:8765"
        controller.oneTimeToken="previous-token"
        await controller.registerCredential("maltose.main")
        XCTAssertEqual(controller.oneTimeToken,"")
        XCTAssertTrue(controller.credentialStatus.contains("OSStatus -50"))
        XCTAssertTrue(controller.credentialStatus.contains("鑰匙圈"))
        XCTAssertEqual(controller.status,"已連線 · 127.0.0.1:8765")
    }
    func testInvalidNameExplainsRequiredFormat() async {
        let controller=HostController(registry:AgentRegistry(store:UnavailableCredentials()))
        await controller.registerCredential("/Users/Marvin/Workspace/MyAgent")
        XCTAssertTrue(controller.credentialStatus.contains("agent.myagent"))
        XCTAssertEqual(controller.oneTimeToken,"")
    }
}
