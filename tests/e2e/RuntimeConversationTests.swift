import Foundation
import XCTest
@testable import MaltoseApp

@MainActor final class RuntimeConversationTests: XCTestCase {
    private func event(_ sequence: Int, type: String, payload: [String: Any] = [:], session: String = "session") throws -> Data {
        try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "sessionID": session, "sequence": sequence,
            "event": ["type": type, "payload": payload, "timestamp": "2026-11-01T00:00:00Z"]])
    }

    func testStreamFinalTextAndDedupSurviveJournalReopen() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-chat-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("conversation.jsonl")
        let model = ConversationHistoryModel()
        XCTAssertEqual(model.contentSourceLabel, "示意內容")
        try model.enableLiveStorage(at: file)
        XCTAssertEqual(model.contentSourceLabel, "對話紀錄")
        XCTAssertTrue(model.sessions.isEmpty, "Live sessions must not display demo data")
        let user = try event(1, type: "user_message", payload: ["content": "hello", "source": "native"])
        try model.applyRuntimeEvent(user)
        try model.applyRuntimeEvent(user)
        try model.applyRuntimeEvent(event(2, type: "assistant_start", payload: ["message_id": "reply"]))
        try model.applyRuntimeEvent(event(3, type: "assistant_delta", payload: ["message_id": "reply", "content": "partial"]))
        try model.applyRuntimeEvent(event(5, type: "assistant_end", payload: ["message_id": "reply", "content": "complete answer"]))
        try model.applyRuntimeEvent(event(4, type: "assistant_delta", payload: ["message_id": "reply", "content": "stale"]))
        XCTAssertEqual(model.currentSession?.messages.map(\.text), ["hello", "complete answer"])
        XCTAssertEqual(model.currentSession?.messages.first?.origin, "native")
        model.closeLiveStorage()
        let restored = ConversationHistoryModel()
        try restored.enableLiveStorage(at: file)
        XCTAssertEqual(restored.currentSession?.messages.map(\.text), ["hello", "complete answer"])
        XCTAssertEqual(restored.currentSession?.messages.first?.origin, "native")
        restored.closeLiveStorage()
    }

    func testInterruptedLastRecordIsPreservedBeforeRecovery() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-chat-recovery-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let file = directory.appendingPathComponent("conversation.jsonl")
        var data = try event(1, type: "user_message", payload: ["content": "saved"])
        data.append(10); data.append(Data("{\"partial\":".utf8))
        try data.write(to: file)
        let model = ConversationHistoryModel()
        try model.enableLiveStorage(at: file)
        XCTAssertEqual(model.currentSession?.messages.first?.text, "saved")
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: directory.path).contains { $0.contains("interrupted-") })
        try model.applyRuntimeEvent(event(2, type: "assistant_message", payload: ["content": "new answer"]))
        model.closeLiveStorage()
        let restored = ConversationHistoryModel()
        try restored.enableLiveStorage(at: file)
        XCTAssertEqual(restored.currentSession?.messages.map(\.text), ["saved", "new answer"])
        restored.closeLiveStorage()
    }

    func testCorruptCompleteRecordFailsWithoutReplacingDataWithSamples() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-chat-corrupt-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let file = directory.appendingPathComponent("conversation.jsonl")
        let original = Data("not JSON\n".utf8)
        try original.write(to: file)
        let model = ConversationHistoryModel()
        XCTAssertThrowsError(try model.enableLiveStorage(at: file))
        XCTAssertTrue(model.sessions.isEmpty)
        XCTAssertEqual(try Data(contentsOf: file), original)
    }

    func testRuntimePayloadCanContainStructuredArrays() throws {
        let model = ConversationHistoryModel(sessions: [])
        try model.applyRuntimeEvent(event(1, type: "ui_block", payload: ["items": [["label": "one"], ["label": "two"]]]))
        XCTAssertTrue(model.sessions.isEmpty)
    }

    func testComposerKeepsDraftUntilSubmissionIsAccepted() {
        let chrome = WorkspaceChromeModel()
        chrome.draft = "a real message"
        chrome.onSubmitText = { _ in false }
        chrome.submitDraft()
        XCTAssertEqual(chrome.draft, "a real message")
        var received: [String] = []
        chrome.onSubmitText = { received.append($0); return true }
        chrome.submitDraft()
        XCTAssertEqual(received, ["a real message"])
        XCTAssertEqual(chrome.draft, "")
    }
}
