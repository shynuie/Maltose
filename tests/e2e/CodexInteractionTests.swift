import XCTest
@testable import MaltoseApp

@MainActor final class CodexInteractionTests: XCTestCase {
    private func request(_ id: CodexRPCID = .integer(1), connection: UUID = UUID()) -> CodexServerRequest {
        .init(id: id, method: "item/commandExecution/requestApproval", params: .object(["threadId": .string("thread"), "turnId": .string("turn")]), connectionID: connection)
    }

    func testOnlyCurrentHumanControlCanAnswerAndRepeatedCallbackCannotApproveTwice() {
        let coordinator = CodexInteractionCoordinator()
        var answers: [(CodexServerRequest, CodexInteractionCoordinator.Answer)] = []
        var callback: ((CodexInteractionCoordinator.Answer) -> Void)?
        var presentations = 0
        coordinator.present = { _, completion in presentations += 1; callback = completion; return {} }
        coordinator.send = { request, answer in answers.append((request, answer)); return true }
        let original = request()
        coordinator.receive(original); coordinator.receive(original)
        XCTAssertEqual(presentations, 1); XCTAssertTrue(answers.isEmpty)
        callback?(.success(.object(["decision": .string("accept")])))
        callback?(.success(.object(["decision": .string("accept")])))
        XCTAssertEqual(answers.count, 1)
        XCTAssertEqual(answers.first?.0.connectionID, original.connectionID)
    }

    func testResolvedOrRestartedRequestCancelsUIAndRejectsLateApprovalForReusedID() {
        let coordinator = CodexInteractionCoordinator()
        var callbacks: [(CodexInteractionCoordinator.Answer) -> Void] = [], sent: [UUID] = [], cancelled = 0
        coordinator.present = { _, completion in callbacks.append(completion); return { cancelled += 1 } }
        coordinator.send = { request, _ in sent.append(request.connectionID); return true }
        let old = request()
        coordinator.receive(old); coordinator.resolved(old.id)
        let fresh = request()
        coordinator.receive(fresh)
        callbacks[0](.success(.object(["decision": .string("accept")])));
        XCTAssertTrue(sent.isEmpty)
        callbacks[1](.success(.object(["decision": .string("decline")])))
        XCTAssertEqual(sent, [fresh.connectionID]); XCTAssertEqual(cancelled, 1)
        coordinator.receive(request(.integer(2))); coordinator.reset()
        callbacks[2](.success(.object(["decision": .string("accept")])))
        XCTAssertEqual(sent.count, 1); XCTAssertEqual(cancelled, 2)
    }

    func testStringAndIntegerRequestsRemainDistinctAndFailedSendIsVisible() {
        let coordinator = CodexInteractionCoordinator()
        var callbacks: [(CodexInteractionCoordinator.Answer) -> Void] = [], ids: [CodexRPCID] = [], issues: [String] = []
        let connection = UUID()
        coordinator.present = { request, completion in ids.append(request.id); callbacks.append(completion); return {} }
        coordinator.send = { _, _ in false }; coordinator.onIssue = { issues.append($0) }
        coordinator.receive(request(.integer(1), connection: connection)); coordinator.receive(request(.string("1"), connection: connection))
        XCTAssertEqual(ids, [.integer(1)])
        callbacks[0](.failure(.init(code: -32000, message: "cancel")))
        XCTAssertEqual(ids, [.integer(1), .string("1")]); XCTAssertEqual(issues.count, 1)
    }

    func testLoginOnlyOpensOfficialHTTPSAccountPages() {
        XCTAssertNotNil(AgentSessionCoordinator.loginURL("https://auth.openai.com/oauth/authorize?fixture=1"))
        XCTAssertNotNil(AgentSessionCoordinator.loginURL("https://chatgpt.com/oauth/authorize"))
        for url in ["http://auth.openai.com/", "https://auth.openai.com.example.invalid/", "https://example.invalid/", "file:///tmp/auth", "https://user@auth.openai.com/", "https://auth.openai.com:1234/"] {
            XCTAssertNil(AgentSessionCoordinator.loginURL(url), url)
        }
    }
}
