import Foundation
import CryptoKit

extension AgentSessionCoordinator {
    func validatePanelContinuation(_ reference: NativePanelSource.Continuation) throws {
        guard let task = store.productTask(reference.taskID), task.conversationID == conversation.id,
              let scope = task.continuations?.first(where: { $0.id == reference.continuationID }), scope.state == "running", scope.mode == "work",
              scope.inputID == reference.inputID, scope.requirementsRevision == reference.requirementsRevision,
              scope.planVersion == reference.planVersion, scope.foregroundID == reference.foregroundID,
              scope.resumeAfterID == reference.resumeAfterID else { throw CodexTaskStoreError.conflict }
        try checkContinuation(task, scope: scope)
    }

    func validateContinuationPublication(_ publication: ResultDeliveryRecord) throws {
        try validateWorkerPublication(publication)
        try validateForegroundPublication(publication)
        guard publication.publicationID.hasPrefix("task-continuation:") else { return }
        let identity = publication.publicationID.hasSuffix(":assessment") ? String(publication.publicationID.dropLast(":assessment".count)) : publication.publicationID
        guard let task = store.productTasks.first(where: { ($0.continuations ?? []).contains(where: { $0.id == identity }) }),
              let scope = task.continuations?.first(where: { $0.id == identity }) else { throw CodexTaskStoreError.conflict }
        try checkContinuation(task, scope: scope)
    }

    private func foregroundRoot(_ task: ProductTask, outcome: ProductTaskOutcome) -> String? {
        let identity = outcome.id.hasPrefix("assessment:") ? String(outcome.id.dropFirst("assessment:".count)) : outcome.id
        if identity.hasPrefix("main-result:") { return identity }
        return task.continuations?.first(where: { $0.id == identity })?.foregroundID
    }

    private func checkForegroundContinuationRoot(_ task: ProductTask, inputID: String, identity: String) throws {
        guard runtime.foregroundContinuationVersion == 1,
              let root = conversation.foregroundPublications?.first(where: { $0.publicationID == identity }),
              root.state == "delivered", root.taskID == task.id, root.inputID == inputID,
              root.requirementsRevision == task.requirementsRevision, root.planVersion == task.planVersion else { throw CodexTaskStoreError.conflict }
    }

    private func checkContinuation(_ task: ProductTask, scope: ProductContinuation) throws {
        if let root = scope.foregroundID { try checkForegroundContinuationRoot(task, inputID: scope.inputID, identity: root) }
        if scope.foregroundID==nil,scope.resumeAfterID != nil {
            guard runtime.workerResultVersion==1,let root=workerRoot(task,outcomeID:scope.sourceOutcomeID),root.inputID==scope.inputID,
                  root.requirementsRevision==scope.requirementsRevision,root.planVersion==scope.planVersion else {throw CodexTaskStoreError.conflict}
        }
        guard runtime.state == .ready, runtime.autonomy?.state == .active,
              conversation.activeProductTaskID == task.id, conversation.phase == .maltoseActive, conversation.recipient == .maltose,
              conversation.stopRequested != true, !conversation.inputs.contains(where: { $0.delivery == .queued || $0.delivery == .dispatching }),
              isCurrentProductSource(scope.inputID, task: task, resumeAfterID: scope.resumeAfterID, continuationID: scope.id),
              !task.held, !task.cancelled, task.requirementsRevision == scope.requirementsRevision, task.planVersion == scope.planVersion,
              scope.runtimeSessionID == runtime.sessionID, (scope.state != "interrupted" || scope.recoveryState == "uncertain") else { throw CodexTaskStoreError.conflict }
    }

    func handleProductContinuation(_ request: ProductWorkflowRequest, input: AgentInputRecord) throws -> [String: UserViewValue] {
        guard let id = request.taskID, let task = store.productTask(id), task.conversationID == conversation.id,
              input.productTaskID == id, canAccessProductTask(task, input: input) else { throw CodexTaskStoreError.conflict }
        let executionID = request.continuationID.map { "continue:\($0)" }
        if request.operation == .continuationContext {
            guard conversation.activeProductTaskID == id, !task.held, !task.cancelled,
                  !hasUndeliveredWorkerResults(task),
                  isCurrentProductSource(input.id, task: task, resumeAfterID: request.resumeAfterID),
                  task.requirementsRevision == request.requirementsRevision, task.planVersion == request.planVersion,
                  !task.executions.contains(where: { [.prepared, .running, .uncertain].contains($0.state) }),
                  let source = task.outcomes.last, source.id == request.resultID || source.id == "assessment:\(request.resultID ?? "")" else {
                return ["schemaVersion": .number(1), "candidate": .null]
            }
            let root = foregroundRoot(task, outcome: source)
            guard request.foregroundID == root else { throw CodexTaskStoreError.conflict }
            if let root {
                try checkForegroundContinuationRoot(task, inputID: input.id, identity: root)
                guard !task.isVerifiedComplete(source), ![.needsInput, .cancelled].contains(source.reportedState) else {
                    return ["schemaVersion": .number(1), "candidate": .null]
                }
                let parent = source.id.hasPrefix("assessment:") ? String(source.id.dropFirst("assessment:".count)) : source.id
                if parent != root, task.continuations?.first(where: { $0.id == parent })?.state != "delivered" {
                    return ["schemaVersion": .number(1), "candidate": .null]
                }
            }
            if root==nil,runtime.workerResultVersion==1,task.isVerifiedComplete(source) {
                let identity=source.id.hasPrefix("assessment:") ? String(source.id.dropFirst("assessment:".count)):source.id
                if (task.continuations ?? []).contains(where:{$0.state=="delivered" && ($0.id==identity || ($0.mode=="finalize" && $0.sourceOutcomeID==source.id))}) {return ["schemaVersion":.number(1),"candidate":.null]}
            }
            let count = (task.continuations ?? []).filter { $0.requirementsRevision == task.requirementsRevision }.count
            if count >= 9 { return ["schemaVersion": .number(1), "candidate": .null] }
            let capped = count >= 8
            let mode = capped ? "clarify" : task.isVerifiedComplete(source) ? "finalize" : source.reportedState == .needsInput && source.assessment == nil ? "clarify" : "work"
            let raw = "\(id.uuidString):\(task.requirementsRevision):\(task.planVersion):\(source.id)" + (request.resumeAfterID.map { ":resume:\($0)" } ?? "")
            let key = "task-continuation:" + SHA256.hash(data: Data(raw.utf8)).map { String(format: "%02x", $0) }.joined()
            if (task.continuations ?? []).contains(where: { $0.id == key }) { return ["schemaVersion": .number(1), "candidate": .null] }
            let context = try productAssessmentContext(id)
            guard context["complete"] == .boolean(true) else { return ["schemaVersion": .number(1), "candidate": .null] }
            var candidate: [String: UserViewValue] = ["id": .string(key), "taskID": .string(id.uuidString),
                "inputID": .string(input.id), "sourceOutcomeID": .string(source.id), "mode": .string(mode),
                "requirementsRevision": .number(Double(task.requirementsRevision)), "planVersion": .number(Double(task.planVersion)),
                "context": context, "task": .object(try productSnapshot(id)), "inputSource": .string(input.origin.rawValue),
                "stopReason": .string(capped ? "本次需求已達八次自動接續的上限，仍有剩餘事項，需要確認下一步。" : "")]
            if let root { candidate["foregroundID"] = .string(root) }
            if root==nil,runtime.workerResultVersion==1,let worker=workerRoot(task,outcomeID:source.id) {candidate["workerResultID"] = .string(worker.publicationID)}
            if let resumed = request.resumeAfterID {
                candidate["resumeAfterID"] = .string(resumed)
                if let question=conversation.inputs.first(where:{$0.id==latestProductHumanInputID}) {candidate["deliverySource"] = .string(question.origin.rawValue)}
                if root==nil {
                    guard runtime.workerResultVersion==1,let worker=workerRoot(task,outcomeID:source.id) else {return ["schemaVersion":.number(1),"candidate":.null]}
                    candidate["workerResultID"] = .string(worker.publicationID)
                }
            }
            return ["schemaVersion": .number(1), "candidate": .object(candidate)]
        }
        guard let key = request.continuationID else { throw CodexTaskStoreError.conflict }
        if request.operation == .continuationStart {
            let previous = task.continuations?.first(where: { $0.id == key })
            guard let source = task.outcomes.first(where: { $0.id == request.sourceOutcomeID }),
                  task.outcomes.last?.id == source.id || (previous != nil && (task.outcomes.last?.id == key || task.outcomes.last?.id == "assessment:\(key)")),
                  task.requirementsRevision == request.requirementsRevision, task.planVersion == request.planVersion,
                  !task.executions.contains(where: { [.prepared, .running, .uncertain].contains($0.state) && $0.id != executionID }) else { throw CodexTaskStoreError.conflict }
            let root = foregroundRoot(task, outcome: source)
            guard request.foregroundID == root, previous == nil || (previous?.foregroundID == root && previous?.resumeAfterID == request.resumeAfterID) else { throw CodexTaskStoreError.conflict }
            if let root {
                try checkForegroundContinuationRoot(task, inputID: input.id, identity: root)
                if previous == nil {
                    guard !task.isVerifiedComplete(source), ![.needsInput, .cancelled].contains(source.reportedState) else { throw CodexTaskStoreError.conflict }
                    let parent = source.id.hasPrefix("assessment:") ? String(source.id.dropFirst("assessment:".count)) : source.id
                    guard parent == root || task.continuations?.first(where: { $0.id == parent })?.state == "delivered" else { throw CodexTaskStoreError.conflict }
                }
            }
            let raw = "\(id.uuidString):\(task.requirementsRevision):\(task.planVersion):\(source.id)" + (request.resumeAfterID.map { ":resume:\($0)" } ?? "")
            let expected = "task-continuation:" + SHA256.hash(data: Data(raw.utf8)).map { String(format: "%02x", $0) }.joined()
            guard key == expected else { throw CodexTaskStoreError.conflict }
            let capped = (task.continuations ?? []).filter { $0.requirementsRevision == task.requirementsRevision }.count >= 8
            let mode = previous?.mode ?? (capped ? "clarify" : task.isVerifiedComplete(source) ? "finalize" : source.reportedState == .needsInput && source.assessment == nil ? "clarify" : "work")
            let scope = ProductContinuation(id: key, sourceOutcomeID: source.id, inputID: input.id,
                requirementsRevision: task.requirementsRevision, planVersion: task.planVersion, mode: mode,
                runtimeSessionID: request.runtimeSessionID, state: "running", foregroundID: root, resumeAfterID: request.resumeAfterID)
            if root != nil && runtime.autonomy?.state != .active { return ["schemaVersion": .number(1), "deferred": .boolean(true)] }
            try checkContinuation(task, scope: scope)
            try store.beginProductContinuation(id, scope: scope, recoveredPhase: root == nil ? nil : request.continuationPhase)
            return ["schemaVersion": .number(1), "mode": .string(mode)]
        }
        guard let scope = task.continuations?.first(where: { $0.id == key }), scope.inputID == input.id, scope.foregroundID == request.foregroundID, scope.resumeAfterID == request.resumeAfterID,
              scope.runtimeSessionID == request.runtimeSessionID else { throw CodexTaskStoreError.conflict }
        if request.operation != .continuationAbort { try checkContinuation(task, scope: scope) }
        if request.operation == .continuationCheck {
            guard task.outcomes.last?.id == scope.sourceOutcomeID || task.outcomes.last?.id == key || task.outcomes.last?.id == "assessment:\(key)" else { throw CodexTaskStoreError.conflict }
            return ["schemaVersion": .number(1), "valid": .boolean(true)]
        }
        if request.operation == .continuationACK {
            try store.setProductContinuationState(id, identity: key, state: "delivered")
            return ["schemaVersion": .number(1)]
        }
        guard request.operation == .continuationResult || request.operation == .continuationAbort else { throw CodexTaskStoreError.conflict }
        if scope.mode == "work", !(request.operation == .continuationAbort && task.outcomes.contains(where: { $0.id == key })),
           var execution = task.executions.first(where: { $0.id == executionID }) {
            let aborted = request.operation == .continuationAbort
            execution.state = aborted ? .cancelled : request.answerKind == "failed" ? .failed : .succeeded
            let observations = request.observations ?? []
            guard observations.count <= 64 else { throw CodexTaskStoreError.conflict }
            var evidence = try observations.map { try $0.evidence(executionID: execution.id) }
            if scope.foregroundID != nil && !aborted {
                guard let saved = readResultPublication?(key) else { throw CodexTaskStoreError.conflict }
                evidence.append(try answerDeliveryEvidence(saved, executionID: execution.id))
            }
            try store.recordProductReport(id, execution: execution, evidence: evidence,
                outcome: .init(id: key, executionID: execution.id, requirementsRevision: scope.requirementsRevision, planVersion: scope.planVersion,
                    reportedState: aborted ? .cancelled : request.answerKind == "needs_input" ? .needsInput : request.answerKind == "failed" ? .failed : .partial,
                    summary: request.answerSummary ?? "接續已中斷；保留已發生操作，不自動重做。", remaining: ["依目前要求核對接續成果。"], artifactID: key))
        } else if scope.mode == "clarify", request.operation == .continuationResult {
            let execution = ProductExecution(id: "continue:\(key)", engine: .main, externalID: key, inputID: input.id,
                requirementsRevision: scope.requirementsRevision, planVersion: scope.planVersion, state: .succeeded, turnID: key)
            try store.recordProductReport(id, execution: execution, outcome: .init(id: key, executionID: execution.id,
                requirementsRevision: scope.requirementsRevision, planVersion: scope.planVersion, reportedState: .needsInput,
                summary: request.answerSummary ?? "接續需要使用者決定。", remaining: ["請確認剩餘事項與下一步。"], artifactID: key))
        }
        try store.setProductContinuationState(id, identity: key, state: request.operation == .continuationAbort ? "interrupted" : "stored")
        var response: [String: UserViewValue] = ["schemaVersion": .number(1)]
        if scope.mode == "work", request.operation == .continuationResult {
            let current = store.productTask(id)!
            if let saved = current.outcomes.last, saved.id == "assessment:\(key)", saved.reportedState != .completed || current.isVerifiedComplete(saved) {
                response["assessment"] = try JSONDecoder().decode(UserViewValue.self, from: JSONEncoder().encode(CodexTaskStore.assessment(from: saved)))
            } else if current.outcomes.contains(where: { $0.id == "assessment:\(key)" }) {
                response["assessmentContext"] = .object(["stale": .boolean(true)])
            } else { response["assessmentContext"] = try productAssessmentContext(id) }
        }
        return response
    }
}
