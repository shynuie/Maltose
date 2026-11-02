import AppKit
import XCTest
@testable import MaltoseApp

@MainActor final class NativePanelOperationTests: XCTestCase {
    @MainActor private final class Harness {
        let manager: WorkspaceWindowManager
        let store: CodexTaskStore
        let journal: NativePanelOperationJournal
        let directory: URL
        let conversationID: String
        let productID: UUID
        var source: NativePanelSource
        init() throws {
            guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native panel models") }
            _ = NSApplication.shared
            guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
            directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-panel-operations-\(UUID())")
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            store = CodexTaskStore(url: directory.appendingPathComponent("tasks.json")); try store.open()
            let conversation = try store.ensureConversation(); conversationID = conversation.id
            let text = "更新 notes 筆記與 chart 圖表"
            _ = try store.enqueue(.init(id:"human", text:text, author:.user, origin:.native, speakerID:nil, speakerStatus:nil,
                                       runtimeSessionID:nil, recipient:.maltose, delivery:.accepted), conversationID: conversationID)
            let product = try store.beginProductTask(conversationID: conversationID, inputID:"human",
                plan:.init(sourceInputID:"human", criteria:[text], steps:[.init(id:"update",title:text)]))
            productID = product.id
            source = .init(runtimeSessionID:"runtime", executor:.maltose, inputID:"human", scopeID:"invocation",
                           product:.init(taskID:product.id, requirementsRevision:1, planVersion:1))
            manager = WorkspaceWindowManager(automaticallyFullscreen:false); manager.synchronize()
            journal = NativePanelOperationJournal(store:store, conversationID:conversationID)
            let policy = manager.agentInterface.panelPolicy
            policy.operationJournal = journal
            policy.validateSource = { source in .init(inputID:source.inputID, text:text, canReadExisting:true) }
            policy.assessIntent = { context, _ in
                let targets = context["targetIDs"]!.arrayValue!.compactMap(\.stringValue)
                return .init(decision:"allow", command:context["command"]!.stringValue!, targetIDs:targets,
                             evidence:text, reason:"受控的人員更新要求", actionEvidence:"更新", targetEvidence:targets[0])
            }
            let journal = self.journal, store = self.store, conversationID = self.conversationID
            policy.canRetryMutation = { previous, next in journal.canRetry(previous, as:next) }
            policy.claimMutation = { requested in
                try store.updateConversation(conversationID) { conversation in
                    var claims = conversation.panelMutationClaims ?? []
                    for claim in requested {
                    if claims.contains(where: { $0.inputID == claim.inputID && $0.targetID == claim.targetID && $0.category == claim.category && $0.source == claim.source && $0.operationVersion == claim.operationVersion }) { continue }
                        if let previous = claims.last(where: { $0.inputID == claim.inputID && $0.targetID == claim.targetID && $0.category == claim.category }) {
                            if previous == claim { continue }
                            guard claim.autonomous == true || journal.canRetry(previous, as:claim) else { throw CodexTaskStoreError.conflict }
                        }
                        claims.append(claim)
                    }
                    conversation.panelMutationClaims = claims
                }
            }
            policy.captureHumanInput("human", runtimeSessionID:"runtime")
        }
        func close() { manager.stop(); store.close(); try? FileManager.default.removeItem(at:directory) }
        func call(_ command: WorkspaceAgentCommand, source: NativePanelSource? = nil) async -> WorkspaceAgentResponse {
            await manager.agentInterface.handleAgent(.init(command:command, source:source ?? self.source))
        }
        func ack(_ receipts: [NativePanelOperationReceipt]) async -> WorkspaceAgentResponse {
            await manager.agentInterface.handleAgent(.init(command:.acknowledge_panel_operations(receipts:receipts)))
        }
        func continuation() -> NativePanelSource {
            var next = source; next.scopeID = "continuation"
            next.continuation = .init(taskID:productID,inputID:"human",requirementsRevision:1,planVersion:1,continuationID:"continue")
            return next
        }
    }

    func testActionBoundaryDistinguishesNewPanelsHumanEditsAndAdmittedExistingActions() async throws {
        let h = try Harness(); defer { h.close() }
        let policy = h.manager.agentInterface.panelPolicy
        policy.operationProtocolEnabled = { true }
        func boundary() -> [String: UserViewValue] {
            let conversation = h.store.conversations.first { $0.id == h.conversationID }!
            return policy.actionBoundary(inputID: "human", runtimeSessionID: "runtime",
                claims: conversation.panelMutationClaims ?? [], operations: conversation.panelOperations ?? [])
        }
        XCTAssertEqual(boundary()["noAcceptedExistingPanelActions"], .boolean(true))
        let created = await h.call(.create_panel(kind: .notes, screenID: nil))
        let id = try XCTUnwrap(created.result["panelID"]?.stringValue)
        let fill = await h.call(.notes_set_text(panelID: id, text: "新成果"))
        XCTAssertTrue(fill.ok)
        h.manager.panels["notes"]?.sampleContentModel?.note = "人員手動編輯"
        XCTAssertEqual(boundary()["noAcceptedExistingPanelActions"], .boolean(true), "This is a guard audit, not a false UI-state comparison")
        let update = await h.call(.notes_set_text(panelID: "chart", text: "不支援此面板"))
        XCTAssertFalse(update.ok)
        // The claim is admitted even when the operation has no effect. Never turn
        // a failed or uncertain action into evidence of no admitted actions.
        XCTAssertEqual(boundary()["noAcceptedExistingPanelActions"], .boolean(false))
        XCTAssertFalse(try XCTUnwrap(boundary()["acceptedActions"]?.arrayValue).isEmpty)
        let recorded = try XCTUnwrap(h.store.conversations.first?.panelOperations)
        let operationOnly = policy.actionBoundary(inputID: "human", runtimeSessionID: "runtime", claims: [], operations: recorded)
        XCTAssertEqual(operationOnly["noAcceptedExistingPanelActions"], .boolean(false))
        XCTAssertTrue(try XCTUnwrap(boundary()["originalPanels"]?.arrayValue).contains { $0["id"] == .string("chart") })
        XCTAssertFalse(try XCTUnwrap(boundary()["originalPanels"]?.arrayValue).contains { $0["id"] == .string(id) })
    }

    func testActionBoundaryCannotCertifyMissingSnapshotsRestartedRuntimeOrDisabledGuard() throws {
        let h = try Harness(); defer { h.close() }
        let policy = h.manager.agentInterface.panelPolicy
        policy.operationProtocolEnabled = { true }
        for (input, runtime) in [("missing", "runtime"), ("human", "new-runtime")] {
            let detail = policy.actionBoundary(inputID: input, runtimeSessionID: runtime, claims: [], operations: [])
            XCTAssertEqual(detail["complete"], .boolean(false))
            XCTAssertEqual(detail["noAcceptedExistingPanelActions"], .boolean(false))
        }
        policy.operationProtocolEnabled = { false }
        XCTAssertEqual(policy.actionBoundary(inputID: "human", runtimeSessionID: "runtime", claims: [], operations: [])["complete"], .boolean(false))
        policy.operationProtocolEnabled = { true }; policy.claimMutation = nil
        XCTAssertEqual(policy.actionBoundary(inputID: "human", runtimeSessionID: "runtime", claims: [], operations: [])["complete"], .boolean(false))
    }

    func testUnnegotiatedOperationProtocolDoesNotIssueReceiptsOrBlockLegacyUpdates() async throws {
        let h=try Harness();defer {h.close()}
        h.manager.agentInterface.panelPolicy.operationProtocolEnabled={false}
        XCTAssertFalse(WorkspaceAgentToolDefinitions.all.contains {$0.command == "acknowledge_panel_operations"})
        let first=await h.call(.notes_set_text(panelID:"notes",text:"舊協定第一次更新"))
        let second=await h.call(.notes_set_text(panelID:"notes",text:"舊協定第二次更新"))
        XCTAssertTrue(first.ok);XCTAssertTrue(second.ok)
        XCTAssertNil(first.operationReceipts);XCTAssertNil(second.operationReceipts)
        XCTAssertTrue(h.journal.operations.isEmpty)
        XCTAssertTrue(h.store.conversations.first?.panelMutationClaims?.allSatisfy {$0.operationVersion == nil} == true)
        let read=await h.call(.read_panel(panelID:"notes"))
        XCTAssertNil(read.result["operationHistory"])
        XCTAssertEqual(h.manager.panels["notes"]?.sampleContentModel?.note,"舊協定第二次更新")
    }

    func testLostAcknowledgementReadsBackTheCompletedOperationBeforeAllowingAnotherWrite() async throws {
        let h = try Harness(); defer { h.close() }
        let first = await h.call(.notes_set_text(panelID:"notes",text:"已完成的修改"))
        XCTAssertTrue(first.ok); XCTAssertEqual(h.journal.operations.count,1)
        XCTAssertEqual(h.journal.operations[0].phase,.completed); XCTAssertFalse(h.journal.operations[0].acknowledged)
        let blocked = await h.call(.notes_set_text(panelID:"notes",text:"不能在未知回執後重做"))
        XCTAssertEqual(blocked.error?.code,"outcome_unknown")
        XCTAssertEqual(blocked.error?.operationID,h.journal.operations[0].id)
        XCTAssertEqual(h.manager.panels["notes"]?.sampleContentModel?.note,"已完成的修改")
        let wrong = await h.ack([.init(id:h.journal.operations[0].id,token:"wrong")])
        XCTAssertFalse(wrong.ok); XCTAssertFalse(h.journal.operations[0].acknowledged)
        let read = await h.call(.read_panel(panelID:"notes"))
        let history = try XCTUnwrap(read.result["operationHistory"]?.arrayValue?.first?.objectValue)
        XCTAssertEqual(history["phase"],.string("completed")); XCTAssertEqual(history["currentStateMatches"],.boolean(true))
        XCTAssertEqual(read.operationReceipts?.count,1)
        let ack = await h.ack(try XCTUnwrap(read.operationReceipts)); XCTAssertTrue(ack.ok)
        let next = await h.call(.notes_set_text(panelID:"notes",text:"同一執行的下一個明確修改"))
        XCTAssertTrue(next.ok); XCTAssertEqual(h.journal.operations.count,2)
        h.manager.panels["notes"]?.sampleContentModel?.note = "人員後續編輯"
        let afterEdit = await h.call(.read_panel(panelID:"notes"))
        XCTAssertTrue(afterEdit.result["operationHistory"]!.arrayValue!.allSatisfy { $0.objectValue?["currentStateMatches"] == .boolean(false) })
        let stale = await h.call(.notes_set_text(panelID:"notes",text:"不能覆寫人員編輯"))
        XCTAssertEqual(stale.error?.code,"outcome_unknown")
        XCTAssertEqual(h.manager.panels["notes"]?.sampleContentModel?.note,"人員後續編輯")
        let acknowledged = await h.ack(try XCTUnwrap(afterEdit.operationReceipts)); XCTAssertTrue(acknowledged.ok)
        let authorized = await h.call(.notes_set_text(panelID:"notes",text:"讀回後依常設權限更新"))
        XCTAssertTrue(authorized.ok)
        XCTAssertEqual(h.manager.panels["notes"]?.sampleContentModel?.note,"讀回後依常設權限更新")
    }

    func testOnlyAcknowledgedNoChangeFailureCanTransferToTheOriginalTaskContinuation() async throws {
        let h = try Harness(); defer { h.close() }
        let before = h.manager.panels["chart"]?.chartModel?.data
        let invalid = await h.call(.chart_load_csv(panelID:"chart",csv:"not-a-table",sourceName:"錯誤資料"))
        XCTAssertFalse(invalid.ok); XCTAssertEqual(invalid.error?.code,"invalid_csv")
        XCTAssertEqual(h.manager.panels["chart"]?.chartModel?.data.seriesNames,before?.seriesNames)
        XCTAssertEqual(h.manager.panels["chart"]?.chartModel?.data.rows.map(\.xLabel),before?.rows.map(\.xLabel))
        XCTAssertEqual(h.manager.panels["chart"]?.chartModel?.data.rows.map(\.values),before?.rows.map(\.values))
        XCTAssertEqual(h.journal.operations.first?.phase,.failedNoChange)
        let previous = try XCTUnwrap(h.store.conversations.first?.panelMutationClaims?.last)
        var next = previous; next.source = h.continuation()
        XCTAssertFalse(h.journal.canRetry(previous,as:next),"A failed reply must actually reach its caller")
        let ack = await h.ack(try XCTUnwrap(invalid.operationReceipts)); XCTAssertTrue(ack.ok)
        XCTAssertTrue(h.journal.canRetry(previous,as:next))
        try h.store.setProductHeld(h.productID,held:true)
        XCTAssertFalse(h.journal.canRetry(previous,as:next))
        try h.store.setProductHeld(h.productID,held:false)
        var unrelated = next; unrelated.source.continuation = nil
        XCTAssertFalse(h.journal.canRetry(previous,as:unrelated))
        unrelated = next; unrelated.source.runtimeSessionID = "restarted"
        XCTAssertFalse(h.journal.canRetry(previous,as:unrelated))
        unrelated = next; unrelated.source.product?.planVersion = 2
        XCTAssertFalse(h.journal.canRetry(previous,as:unrelated))
        var legacy = previous; legacy.operationVersion = nil
        XCTAssertFalse(h.journal.canRetry(legacy,as:next))
        let repaired = await h.call(.chart_load_csv(panelID:"chart",csv:"X,A\n1,2\n2,3",sourceName:"更正資料"),source:next.source)
        XCTAssertTrue(repaired.ok); XCTAssertEqual(h.journal.operations.map(\.phase),[.failedNoChange,.completed])
        XCTAssertEqual(h.store.conversations.first?.panelMutationClaims?.count,2)
        let repairedAck = await h.ack(try XCTUnwrap(repaired.operationReceipts)); XCTAssertTrue(repairedAck.ok)
        var third = next; third.source.scopeID = "another-continuation"
        XCTAssertFalse(h.journal.canRetry(next,as:third),"A completed operation cannot recycle its original grant")
    }

    func testPreparedAndUncertainOperationsSurviveRestartWithoutAuthorizingRetry() async throws {
        let h = try Harness(); defer { h.close() }
        let claim = NativePanelMutationClaim(inputID:"human",targetID:"notes",category:"content",source:h.source,operationVersion:1)
        try h.store.updateConversation(h.conversationID) { $0.panelMutationClaims = [claim] }
        let hash = NativePanelOperationJournal.stamp("before")
        var operation = NativePanelOperation(id:"uncertain-operation",inputID:"human",source:h.source,category:"content",targets:["notes"],
            commandDigest:hash,instanceID:"writer-instance",beforeStamp:hash,acknowledgementToken:"private-token")
        try h.journal.prepare(operation)
        var next = claim; next.source = h.continuation()
        XCTAssertFalse(h.journal.canRetry(claim,as:next))
        XCTAssertThrowsError(try h.journal.acknowledge([.init(id:operation.id,token:operation.acknowledgementToken)]))
        h.store.close(); try h.store.open()
        XCTAssertEqual(h.journal.operations.first?.phase,.prepared)
        operation.phase = .uncertain; operation.afterStamp = hash
        operation.responseData = try JSONEncoder().encode(WorkspaceAgentResponse(ok:false,error:.init(code:"operation_failed",message:"結果未知")))
        try h.journal.finish(operation)
        XCTAssertFalse(h.journal.canRetry(claim,as:next))
        h.store.close(); try h.store.open()
        XCTAssertEqual(h.journal.operations.first?.phase,.uncertain)
        let read = await h.call(.read_panel(panelID:"notes"))
        XCTAssertEqual(read.result["operationHistory"]?.arrayValue?.first?.objectValue?["phase"],.string("uncertain"))
        XCTAssertTrue(read.operationReceipts?.isEmpty == true)
        let blocked = await h.call(.notes_set_text(panelID:"notes",text:"不得盲目再做"))
        XCTAssertEqual(blocked.error?.code,"outcome_unknown")
        XCTAssertEqual(h.journal.operations.count,1)
    }

    func testFailureAfterAnActualPanelWriteIsUnknownRatherThanRetryableNoChange() async throws {
        let h = try Harness(); defer { h.close() }
        let command = WorkspaceAgentCommand.notes_set_text(panelID:"notes",text:"確實已改動")
        let result = await h.manager.agentInterface.panelPolicy.perform(.init(command:command,source:h.source)) { _ in
            let applied = await h.manager.agentInterface.handle(.init(command:command))
            XCTAssertTrue(applied.ok)
            return .init(ok:false,error:.init(code:"invalid_argument",message:"測試：改動後遺失完整回覆"))
        }
        XCTAssertEqual(result.error?.code,"outcome_unknown")
        XCTAssertEqual(result.error?.operationID,h.journal.operations.first?.id)
        XCTAssertNil(result.operationReceipts)
        XCTAssertEqual(h.manager.panels["notes"]?.sampleContentModel?.note,"確實已改動")
        XCTAssertEqual(h.journal.operations.first?.phase,.uncertain)
        let claim=try XCTUnwrap(h.store.conversations.first?.panelMutationClaims?.last)
        var next=claim;next.source=h.continuation()
        XCTAssertFalse(h.journal.canRetry(claim,as:next))
        let read=await h.call(.read_panel(panelID:"notes"))
        XCTAssertEqual(read.result["operationHistory"]?.arrayValue?.first?.objectValue?["phase"],.string("uncertain"))
        XCTAssertTrue(read.operationReceipts?.isEmpty == true)
    }

    func testCompletedReceiptSurvivesWriterRebuildWithoutClaimingThePanelContentWasRestored() async throws {
        let h = try Harness(); defer { h.close() }
        let written=await h.call(.notes_set_text(panelID:"notes",text:"舊 writer 已確實改動"))
        XCTAssertTrue(written.ok)
        h.store.close();try h.store.open()
        let rebuilt=WorkspaceWindowManager(automaticallyFullscreen:false);rebuilt.synchronize();defer {rebuilt.stop()}
        rebuilt.agentInterface.panelPolicy.operationJournal=h.journal
        rebuilt.agentInterface.panelPolicy.validateSource={_ in .init(inputID:"human",text:"讀回先前操作",canReadExisting:true)}
        let read=await rebuilt.agentInterface.handleAgent(.init(command:.read_panel(panelID:"notes"),source:h.source))
        let row=try XCTUnwrap(read.result["operationHistory"]?.arrayValue?.first?.objectValue)
        XCTAssertEqual(row["phase"],.string("completed"));XCTAssertEqual(row["currentStateMatches"],.boolean(false))
        XCTAssertNotEqual(rebuilt.panels["notes"]?.sampleContentModel?.note,"舊 writer 已確實改動")
        let ack=await rebuilt.agentInterface.handleAgent(.init(command:.acknowledge_panel_operations(receipts:try XCTUnwrap(read.operationReceipts))))
        XCTAssertTrue(ack.ok);XCTAssertTrue(h.journal.operations[0].acknowledged)
        let previous=try XCTUnwrap(h.store.conversations.first?.panelMutationClaims?.last)
        var next=previous;next.source=h.continuation()
        XCTAssertFalse(h.journal.canRetry(previous,as:next))
    }

    func testJournalCannotFabricateTargetsTerminalReceiptsOrRewriteItsHistory() throws {
        let h = try Harness(); defer { h.close() }
        let claim = NativePanelMutationClaim(inputID:"human",targetID:"notes",category:"content",source:h.source,operationVersion:1)
        try h.store.updateConversation(h.conversationID) { $0.panelMutationClaims = [claim] }
        let hash = NativePanelOperationJournal.stamp("same-state")
        var operation = NativePanelOperation(id:"operation",inputID:"human",source:h.source,category:"content",targets:["notes","chart"],
            commandDigest:hash,instanceID:"writer",beforeStamp:hash,acknowledgementToken:"private-token")
        XCTAssertThrowsError(try h.journal.prepare(operation),"Every target requires its own saved human claim")
        operation = .init(id:"operation",inputID:"human",source:h.source,category:"content",targets:["notes"],
                          commandDigest:hash,instanceID:"writer",beforeStamp:hash,acknowledgementToken:"private-token")
        let prepared = operation
        operation.phase = .completed; operation.afterStamp = hash
        operation.responseData = try JSONEncoder().encode(WorkspaceAgentResponse(ok:true))
        XCTAssertThrowsError(try h.journal.prepare(operation),"Terminal evidence cannot be inserted after the fact")
        try h.journal.prepare(prepared); try h.journal.finish(operation)
        try h.journal.acknowledge([.init(id:operation.id,token:operation.acknowledgementToken)])
        XCTAssertThrowsError(try h.store.updateConversation(h.conversationID) { $0.panelOperations = [] })
        XCTAssertThrowsError(try h.store.updateConversation(h.conversationID) { $0.panelOperations?[0].acknowledged = false })
        XCTAssertThrowsError(try h.store.updateConversation(h.conversationID) { $0.panelOperations?[0].phase = .failedNoChange })
        XCTAssertThrowsError(try h.store.updateConversation(h.conversationID) { $0.panelOperations?[0].responseData = Data() })
        XCTAssertEqual(h.journal.operations.first?.phase,.completed)
        XCTAssertEqual(h.journal.operations.first?.acknowledged,true)
    }
    func testFreshStoreRestoresTerminalJournalAndAcceptsOnlyItsSavedAcknowledgement() async throws {
        let h=try Harness();defer {h.close()}
        let failed=await h.call(.chart_load_csv(panelID:"chart",csv:"invalid",sourceName:"測試"))
        let failedAck=await h.ack(try XCTUnwrap(failed.operationReceipts));XCTAssertTrue(failedAck.ok)
        let completed=await h.call(.chart_load_csv(panelID:"chart",csv:"X,A\n1,2\n2,3",sourceName:"更正資料"),source:h.continuation())
        XCTAssertTrue(completed.ok)
        let claims=h.store.conversations.first?.panelMutationClaims
        h.store.close()
        let restored=CodexTaskStore(url:h.directory.appendingPathComponent("tasks.json"));try restored.open();defer {restored.close()}
        let journal=NativePanelOperationJournal(store:restored,conversationID:h.conversationID)
        XCTAssertEqual(restored.conversations.first?.panelMutationClaims,claims)
        XCTAssertEqual(journal.operations.map(\.phase),[.failedNoChange,.completed])
        XCTAssertEqual(journal.operations.map(\.acknowledged),[true,false])
        try journal.acknowledge(try XCTUnwrap(completed.operationReceipts))
        XCTAssertTrue(journal.operations.allSatisfy(\.acknowledged))
        XCTAssertThrowsError(try restored.updateConversation(h.conversationID) {$0.panelOperations=[]})
        XCTAssertThrowsError(try restored.updateConversation(h.conversationID) {$0.panelOperations?[1].acknowledged=false})
    }

    func testFreshStoreRestoresPreparedAndUncertainWithoutAuthorizingRetry() throws {
        for phase in [NativePanelOperation.Phase.prepared,.uncertain] {
            let h=try Harness();defer {h.close()}
            let claim=NativePanelMutationClaim(inputID:"human",targetID:"notes",category:"content",source:h.source,operationVersion:1)
            try h.store.updateConversation(h.conversationID) {$0.panelMutationClaims=[claim]}
            let hash=NativePanelOperationJournal.stamp("state")
            var operation=NativePanelOperation(id:"operation",inputID:"human",source:h.source,category:"content",targets:["notes"],
                commandDigest:hash,instanceID:"old-writer",beforeStamp:hash,acknowledgementToken:"private-token")
            try h.journal.prepare(operation)
            if phase == .uncertain {
                operation.phase=phase;operation.afterStamp=hash
                operation.responseData=try JSONEncoder().encode(WorkspaceAgentResponse(ok:false,error:.init(code:"operation_failed",message:"結果未知")))
                try h.journal.finish(operation)
            }
            h.store.close()
            let restored=CodexTaskStore(url:h.directory.appendingPathComponent("tasks.json"));try restored.open();defer {restored.close()}
            let journal=NativePanelOperationJournal(store:restored,conversationID:h.conversationID)
            XCTAssertEqual(journal.operations.first?.phase,phase)
            var next=claim;next.source=h.continuation()
            XCTAssertFalse(journal.canRetry(claim,as:next))
            XCTAssertThrowsError(try journal.acknowledge([.init(id:operation.id,token:operation.acknowledgementToken)]))
        }
    }

    func testFreshStoreRejectsSnapshotClaimThatRecyclesACompletedMutation() async throws {
        let h=try Harness();defer {h.close()}
        let completed=await h.call(.notes_set_text(panelID:"notes",text:"已完成"))
        let ack=await h.ack(try XCTUnwrap(completed.operationReceipts));XCTAssertTrue(ack.ok)
        var forged=try XCTUnwrap(h.store.conversations.first?.panelMutationClaims?.last);forged.source=h.continuation();forged.autonomous=nil
        h.store.close()
        let url=h.directory.appendingPathComponent("tasks.json")
        var raw=try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:url)) as? [String:Any])
        var conversations=try XCTUnwrap(raw["conversations"] as? [[String:Any]])
        var claims=try XCTUnwrap(conversations[0]["panelMutationClaims"] as? [[String:Any]])
        claims.append(try XCTUnwrap(JSONSerialization.jsonObject(with:JSONEncoder().encode(forged)) as? [String:Any]))
        conversations[0]["panelMutationClaims"]=claims;raw["conversations"]=conversations
        try JSONSerialization.data(withJSONObject:raw,options:[.sortedKeys]).write(to:url)
        let restored=CodexTaskStore(url:url)
        XCTAssertThrowsError(try restored.open(),"Loading a snapshot must still verify the historical no-change proof")
    }

}
