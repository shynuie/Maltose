import Foundation

extension AgentSessionCoordinator {
    /// A delivered independent answer can reopen the original task scope. It
    /// neither changes its requirements nor supplies a new execution grant.
    func isCurrentProductSource(_ inputID: String, task: ProductTask, resumeAfterID: String?, continuationID: String? = nil) -> Bool {
        guard let resumeAfterID else { return latestProductHumanInputID == inputID }
        guard runtime.taskResumptionVersion == 1, let latest = latestProductHumanInputID,
              let question = conversation.inputs.first(where: { $0.id == latest }), question.productRelation == .standalone,
              question.delivery == .accepted, question.recipient == .maltose,
              let interlude = question.interlude, interlude.taskID == task.id,
              interlude.requirementsRevision == task.requirementsRevision, interlude.planVersion == task.planVersion,
              task.requirements.last?.inputID == inputID, canAccessProductTask(task, input: question),
              conversation.activeProductTaskID == task.id, !task.held, !task.cancelled,
              let answer = conversation.foregroundPublications?.first(where: { $0.publicationID == resumeAfterID }),
              answer.inputID == question.id, answer.taskID == nil, answer.state == "delivered", answer.answerKind == "answer" else { return false }
        // An interrupted work scope may contain unknown effects. Reconciliation
        // is required before continuing the original request.
        return !(task.continuations ?? []).contains(where: { $0.mode == "work" && $0.state == "interrupted" && $0.id != continuationID })
    }

    func handleTaskResumption(_ request: ProductWorkflowRequest, input: AgentInputRecord) throws -> [String: UserViewValue] {
        let none: [String: UserViewValue] = ["schemaVersion": .number(1), "candidate": .null]
        guard runtime.taskResumptionVersion == 1, latestProductHumanInputID == input.id,
              let publicationID = request.resultID, let id = input.interlude?.taskID,
              let task = store.productTask(id), let originalID = task.requirements.last?.inputID,
              isCurrentProductSource(originalID, task: task, resumeAfterID: publicationID),
              let original = conversation.inputs.first(where: { $0.id == originalID }),
              let outcome = task.outcomes.last else { return none }
        let sourceID = outcome.id.hasPrefix("assessment:") ? String(outcome.id.dropFirst("assessment:".count)) : outcome.id
        let root = sourceID.hasPrefix("main-result:") ? sourceID : task.continuations?.first(where: { $0.id == sourceID })?.foregroundID
        guard root != nil || (runtime.workerResultVersion==1 && workerRoot(task,outcomeID:sourceID) != nil) else {return none}
        var continuation = ProductWorkflowRequest(operation: .continuationContext, runtimeSessionID: request.runtimeSessionID, inputID: originalID)
        continuation.taskID = id; continuation.requirementsRevision = task.requirementsRevision; continuation.planVersion = task.planVersion
        continuation.foregroundID = root; continuation.resumeAfterID = publicationID; continuation.resultID = sourceID
        return try handleProductContinuation(continuation, input: original)
    }
}
