import XCTest
@testable import MaltoseApp

@MainActor final class CodexTaskStoreTests: XCTestCase {
    private func location() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-task-store-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent("tasks.json")
    }
    private func task() -> CodexTaskRecord {
        .init(conversationID: "fixture-conversation", repositoryPath: "/tmp/repository", worktreePath: "/tmp/worktree",
              delegation: .init(objective: "Add fixture behavior", constraints: ["Preserve current edits"], acceptanceCriteria: ["Fixture check passes"]))
    }

    func testPanelMutationClaimsSurviveRestartAndCannotBeRemovedReboundOrDuplicated() throws {
        let url=try location();defer {try? FileManager.default.removeItem(at:url.deletingLastPathComponent())}
        let store=CodexTaskStore(url:url);try store.open()
        let conversation=try store.ensureConversation()
        _ = try store.enqueue(.init(id:"human-update",text:"更新筆記",author:.user,origin:.native,speakerID:nil,speakerStatus:nil,runtimeSessionID:nil,recipient:.maltose,delivery:.accepted),conversationID:conversation.id)
        let source=NativePanelSource(runtimeSessionID:"original-runtime",executor:.maltose,inputID:"human-update",scopeID:"original-invocation")
        let claim=NativePanelMutationClaim(inputID:"human-update",targetID:"notes",category:"content",source:source)
        try store.updateConversation(conversation.id) {$0.panelMutationClaims=[claim]}
        store.close()
        let restored=CodexTaskStore(url:url);try restored.open();defer {restored.close()}
        XCTAssertEqual(restored.conversations.first?.panelMutationClaims,[claim])
        XCTAssertThrowsError(try restored.updateConversation(conversation.id) {$0.panelMutationClaims=[]})
        var rebound=claim;rebound.source.runtimeSessionID="new-runtime"
        XCTAssertThrowsError(try restored.updateConversation(conversation.id) {$0.panelMutationClaims=[rebound]})
        XCTAssertThrowsError(try restored.updateConversation(conversation.id) {$0.panelMutationClaims=[claim,claim]})
        XCTAssertEqual(restored.conversations.first?.panelMutationClaims,[claim])
    }

    func testAtomicPrivateSnapshotRestoresThreadWorktreeAndMessageProvenance() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CodexTaskStore(url: url); try store.open()
        let original = task(); try store.create(original)
        try store.update(original.id) { task in task.threadID = "fixture-thread"; task.activeTurnID = "fixture-turn"; task.status = .running; task.control = .codexDirect }
        let message = CodexTaskMessage(id: "source-message", author: .user, origin: .voice, content: "新增要求",
                                       threadID: "fixture-thread", turnID: "fixture-turn")
        XCTAssertTrue(try store.append(message, to: original.id))
        let revision = store.revision
        XCTAssertFalse(try store.append(message, to: original.id))
        XCTAssertEqual(store.revision, revision)
        let snapshot = store.tasks
        store.close()
        let restored = CodexTaskStore(url: url); try restored.open(); defer { restored.close() }
        XCTAssertEqual(restored.tasks, snapshot)
        XCTAssertEqual(restored.revision, revision)
        XCTAssertEqual(restored.task(original.id)?.control, .codexDirect)
        let permissions = try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(permissions?.intValue, 0o600)
    }

    func testSingleWriterLeaseAndRevisionConflictPreventLostUpdates() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let first = CodexTaskStore(url: url), second = CodexTaskStore(url: url)
        try first.open()
        XCTAssertThrowsError(try second.open())
        let original = task(), revision = first.revision
        try first.create(original)
        XCTAssertThrowsError(try first.update(original.id, expectedRevision: revision) { $0.status = .failed })
        XCTAssertEqual(first.task(original.id)?.status, .prepared)
        first.close(); try second.open(); defer { second.close() }
        XCTAssertEqual(second.task(original.id)?.id, original.id)
    }

    func testInvalidMutationCannotReplaceThreadOrFabricateCompletion() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CodexTaskStore(url: url); try store.open(); defer { store.close() }
        let original = task(); try store.create(original)
        try store.update(original.id) { $0.threadID = "first-thread"; $0.activeTurnID = "first-turn" }
        let snapshot = try Data(contentsOf: url), revision = store.revision
        XCTAssertThrowsError(try store.update(original.id) { $0.threadID = "replacement" })
        XCTAssertThrowsError(try store.update(original.id) { $0.status = .completed })
        XCTAssertEqual(store.revision, revision)
        XCTAssertEqual(try Data(contentsOf: url), snapshot)
        try store.update(original.id) { $0.activeTurnID = nil; $0.status = .completed; $0.outcomeSummary = "Fixture evidence accepted" }
    }

    func testConflictingMessageAndForeignThreadCannotOverwriteHistory() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CodexTaskStore(url: url); try store.open(); defer { store.close() }
        let original = task(); try store.create(original)
        try store.update(original.id) { $0.threadID = "thread" }
        let message = CodexTaskMessage(id: "source", author: .codex, origin: .codex, content: "Result", threadID: "thread", turnID: "turn")
        try store.append(message, to: original.id)
        XCTAssertThrowsError(try store.append(.init(id: "source", author: .user, origin: .native, content: "Result", threadID: "thread", turnID: "turn"), to: original.id))
        XCTAssertThrowsError(try store.append(.init(id: "new", author: .codex, origin: .codex, content: "Other", threadID: "foreign", turnID: nil), to: original.id))
        XCTAssertEqual(store.task(original.id)?.messages, [message])
    }

    func testCorruptionUnsupportedVersionAndSymlinkAreExplicitErrorsWithoutReset() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        for contents in ["{partial", #"{"schemaVersion":99,"revision":0,"tasks":[]}"#] {
            try Data(contents.utf8).write(to: url)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
            let store = CodexTaskStore(url: url)
            XCTAssertThrowsError(try store.open())
            XCTAssertEqual(try String(contentsOf: url, encoding: .utf8), contents)
        }
        let target = url.appendingPathExtension("private")
        try FileManager.default.moveItem(at: url, to: target)
        try FileManager.default.createSymbolicLink(at: url, withDestinationURL: target)
        XCTAssertThrowsError(try CodexTaskStore(url: url).open())
    }

    func testVersionOneTaskSnapshotUpgradesWithoutLosingTaskAndSavesConversationRecoveryState() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let old = CodexTaskStore(url: url); try old.open()
        let task = task(); try old.create(task); old.close()
        var document = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        document["schemaVersion"] = 1; document.removeValue(forKey: "conversations"); document.removeValue(forKey: "activeConversationID")
        try JSONSerialization.data(withJSONObject: document).write(to: url)
        let upgraded = CodexTaskStore(url: url); try upgraded.open()
        let conversation = try upgraded.ensureConversation(task.conversationID)
        try upgraded.updateConversation(conversation.id) { $0.recipient = .codex; $0.phase = .codexDirect; $0.activeTaskID = task.id; $0.stopRequested = true }
        XCTAssertEqual(upgraded.task(task.id), task)
        upgraded.close()
        let restored = CodexTaskStore(url: url); try restored.open(); defer { restored.close() }
        XCTAssertEqual(restored.activeConversation?.activeTaskID, task.id)
        XCTAssertEqual(restored.activeConversation?.stopRequested, true)
        XCTAssertEqual(restored.activeConversation?.recipient, .codex)
        let saved = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        XCTAssertEqual(saved["schemaVersion"] as? Int, 3)
        XCTAssertNotNil(upgraded.migrationBackupURL)
    }

    func testInputReviewRetainsUncertainDeliveryAndRejectsChangedRuntimeProvenance() throws {
        let url = try location(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CodexTaskStore(url: url); try store.open()
        let conversation = try store.ensureConversation()
        let input = AgentInputRecord(id: "voice-id", text: "Fixture input", author: .user, origin: .voice,
            speakerID: "owner", speakerStatus: "identified", runtimeSessionID: "original-runtime", recipient: .codex, delivery: .uncertain)
        XCTAssertTrue(try store.enqueue(input, conversationID: conversation.id))
        XCTAssertFalse(try store.enqueue(input, conversationID: conversation.id))
        let conflict = AgentInputRecord(id: input.id, text: input.text, author: input.author, origin: input.origin,
            speakerID: input.speakerID, speakerStatus: input.speakerStatus, runtimeSessionID: "different-runtime", recipient: .codex)
        XCTAssertThrowsError(try store.enqueue(conflict, conversationID: conversation.id))
        try store.updateConversation(conversation.id) { $0.inputs[0].reviewDisposition = .movedToDraft }
        store.close(); try store.open(); defer { store.close() }
        XCTAssertEqual(store.activeConversation?.inputs.first?.delivery, .uncertain)
        XCTAssertEqual(store.activeConversation?.inputs.first?.runtimeSessionID, "original-runtime")
        XCTAssertEqual(store.activeConversation?.inputs.first?.reviewDisposition, .movedToDraft)
    }
}
