import XCTest
@testable import MaltoseApp

@MainActor final class RuntimeApprovalTests: XCTestCase {
    private func event(id: String = "one", domain: String = "filesystem", status: String = "pending", actions: [String]? = nil, type: String = "native_approval") throws -> Data {
        let prefix = domain == "knowledge" ? "knowledge-proposal-" : domain + "-approval-"
        let key = domain == "knowledge" ? "proposal_id" : "approval_id"
        return try JSONSerialization.data(withJSONObject: ["event": ["type": type, "payload": [
            "block_type": "ui_confirmation", "block_id": prefix + id, "title": "Review", "content": "Exact operation", "status": status,
            "value": [key: id], "actions": (actions ?? [domain + ".approve", domain + ".reject"]).map { ["id": $0, "label": $0] }
        ]]])
    }

    func testHumanDecisionIsScopedQueuedAndNeverRepeatedForDuplicateEvents() throws {
        let coordinator = RuntimeApprovalCoordinator()
        var decisions: [(Bool, String?) -> Void] = []
        var shown: [String] = [], sent: [String] = []
        coordinator.present = { request, completion in shown.append(request.block_id); decisions.append(completion); return {} }
        coordinator.send = { action, value, completion in
            sent.append(action + ":" + (value["approval_id"] ?? "")); completion(true, nil); return true
        }
        try coordinator.receive(event())
        try coordinator.receive(event())
        try coordinator.receive(event(id: "two"))
        XCTAssertEqual(shown, ["filesystem-approval-one"])
        XCTAssertTrue(sent.isEmpty)
        decisions[0](false, nil)
        XCTAssertEqual(shown.count, 2)
        decisions[1](true, nil)
        XCTAssertEqual(sent, ["filesystem.reject:one", "filesystem.approve:two"])
        decisions[0](true, nil)
        XCTAssertEqual(sent.count, 2)
    }

    func testInvalidActionsAndLateCallbacksCannotApproveAfterDisconnect() throws {
        let coordinator = RuntimeApprovalCoordinator()
        var decision: ((Bool, String?) -> Void)?
        var cancelled = false
        coordinator.present = { _, callback in decision = callback; return { cancelled = true } }
        coordinator.send = { _, _, _ in XCTFail("Must not send an approval"); return false }
        try coordinator.receive(event(type: "ui_block"))
        try coordinator.receive(event(type: "ui_confirmation"))
        XCTAssertNil(decision, "Model presentation blocks must not impersonate authoritative approval requests")
        try coordinator.receive(event(actions: ["filesystem.approve", "execution.reject"]))
        XCTAssertNil(decision)
        try coordinator.receive(event())
        coordinator.reset()
        XCTAssertTrue(cancelled)
        decision?(true, nil)
    }

    func testKnowledgeRejectionIncludesReasonAndFailedAckIsVisible() throws {
        let coordinator = RuntimeApprovalCoordinator()
        var decision: ((Bool, String?) -> Void)?, issue: String?
        coordinator.present = { _, callback in decision = callback; return {} }
        coordinator.send = { action, value, completion in
            XCTAssertEqual(action, "knowledge.reject")
            XCTAssertEqual(value["reason"], "incorrect")
            completion(false, "expired"); return true
        }
        coordinator.onIssue = { issue = $0 }
        try coordinator.receive(event(domain: "knowledge"))
        decision?(false, "incorrect")
        XCTAssertEqual(issue, "expired")
        try coordinator.receive(event(domain: "knowledge", status: "truth_conflict", actions: []))
        XCTAssertEqual(issue, "Review：Exact operation")
    }
}
