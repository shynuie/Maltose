import Foundation

/// Immutable worker/attempt provenance with a separately renewable delivery
/// session. Neither the current chat input nor a model supplies a worker owner.
struct WorkerResultPublication: Codable, Equatable {
    let publicationID: String
    let taskID: UUID
    let inputID: String
    let workerID: String
    let attemptID: String
    let requirementsRevision: Int
    let planVersion: Int
    let resultDigest: String
    let workerState: String
    let title: String
    let markdownSHA256: String
    let createDocument: Bool
    let chart: ResultChart?
    var deliverySessionID: String
    var resumeAfterID: String?
    var state = "prepared"
    var assessment: ForegroundPublication.Assessment?

    func validate() throws {
        guard publicationID.range(of:"^task-result:[A-Za-z0-9._:-]{1,96}$",options:.regularExpression) != nil,
              attemptID.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil,
              [resultDigest,markdownSHA256].allSatisfy({$0.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil}),
              requirementsRevision>0,planVersion>0,["succeeded","failed","cancelled","held"].contains(workerState),
              ["prepared","delivered"].contains(state),
              !inputID.isEmpty,inputID.utf8.count<=128,!workerID.isEmpty,workerID.utf8.count<=128,
              !title.isEmpty,title.utf8.count<=200,
              deliverySessionID.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil else {throw CodexTaskStoreError.conflict}
        try chart?.validate()
        if let assessment {
            guard assessment.title=="任務核對",assessment.markdownSHA256.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil else {throw CodexTaskStoreError.conflict}
        }
    }
    func sameSource(as other: Self) -> Bool {
        var left=self,right=other
        left.deliverySessionID="";right.deliverySessionID="";left.resumeAfterID=nil;right.resumeAfterID=nil
        left.state="";right.state="";left.assessment=nil;right.assessment=nil
        return left==right
    }
    func matches(_ record: ResultDeliveryRecord) -> Bool {
        if record.publicationID==publicationID {
            return record.messageID==publicationID && record.title==title && record.createDocument==createDocument
                && record.chart==chart && ForegroundPublication.digest(record.markdown)==markdownSHA256
        }
        return record.publicationID==publicationID+":assessment" && record.messageID==record.publicationID
            && !record.createDocument && record.chart==nil && record.title==assessment?.title
            && ForegroundPublication.digest(record.markdown)==assessment?.markdownSHA256
    }
    static func root(task: ProductTask, outcomeID: String, publications: [Self]) -> Self? {
        var identity=outcomeID;var seen=Set<String>()
        while seen.insert(identity).inserted {
            if identity.hasPrefix("assessment:"){identity=String(identity.dropFirst("assessment:".count));continue}
            if let source=publications.first(where:{$0.publicationID==identity && $0.taskID==task.id && $0.state=="delivered"}) {return source}
            guard let scope=task.continuations?.first(where:{$0.id==identity}) else {return nil}
            identity=scope.sourceOutcomeID
        }
        return nil
    }
}

extension AgentSessionCoordinator {
    func pendingWorkerScopes(_ input: AgentInputRecord) throws -> [String:UserViewValue] {
        guard runtime.workerResultVersion==1,runtime.autonomy?.state == .active,latestProductHumanInputID==input.id,input.delivery == .accepted,
              let id=conversation.activeProductTaskID,let task=store.productTask(id),canAccessProductTask(task,input:input),
              let original=task.requirements.last?.inputID,!task.held,!task.cancelled else {return ["schemaVersion":.number(1),"workers":.array([])]}
        let resumed=latestProductHumanInputID==original ? nil:conversation.foregroundPublications?.last(where:{$0.inputID==input.id && $0.taskID==nil && $0.state=="delivered" && $0.answerKind=="answer"})?.publicationID
        guard isCurrentProductSource(original,task:task,resumeAfterID:resumed),
              !conversation.inputs.contains(where:{$0.delivery == .queued || $0.delivery == .dispatching}) else {return ["schemaVersion":.number(1),"workers":.array([])]}
        let workers=task.executions.filter {$0.engine == .python && $0.inputID==original && $0.requirementsRevision==task.requirementsRevision && $0.planVersion==task.planVersion && $0.turnID != nil}.map {execution in
            UserViewValue.object(["workerID":.string(execution.externalID),"attemptID":.string(execution.turnID!),"taskID":.string(task.id.uuidString),"inputID":.string(original),"requirementsRevision":.number(Double(task.requirementsRevision)),"planVersion":.number(Double(task.planVersion)),
                "managedResults":.strings((conversation.workerPublications ?? []).filter {$0.taskID==task.id && $0.workerID==execution.externalID && $0.attemptID==execution.turnID && $0.requirementsRevision==task.requirementsRevision && $0.planVersion==task.planVersion}.map(\.publicationID))])
        }
        return ["schemaVersion":.number(1),"workers":.array(workers)]
    }
    func hasUndeliveredWorkerResults(_ task: ProductTask) -> Bool {
        (conversation.workerPublications ?? []).contains {$0.taskID==task.id && $0.requirementsRevision==task.requirementsRevision && $0.planVersion==task.planVersion && $0.state != "delivered"}
    }
    func workerRoot(_ task: ProductTask, outcomeID: String) -> WorkerResultPublication? {
        WorkerResultPublication.root(task:task,outcomeID:outcomeID,publications:conversation.workerPublications ?? [])
    }
    func checkWorkerPublication(_ source: WorkerResultPublication) throws {
        guard runtime.workerResultVersion==1,runtime.state == .ready,runtime.autonomy?.state == .active,
              source.deliverySessionID==runtime.sessionID,conversation.phase == .maltoseActive,conversation.recipient == .maltose,
              conversation.stopRequested != true,!conversation.inputs.contains(where:{$0.delivery == .queued || $0.delivery == .dispatching}),
              let task=store.productTask(source.taskID),conversation.activeProductTaskID==task.id,!task.held,!task.cancelled,
              task.requirementsRevision==source.requirementsRevision,task.planVersion==source.planVersion,
              isCurrentProductSource(source.inputID,task:task,resumeAfterID:source.resumeAfterID) else {throw CodexTaskStoreError.conflict}
    }
    func validateWorkerPublication(_ record: ResultDeliveryRecord) throws {
        guard record.publicationID.hasPrefix("task-result:") else {return}
        let id=record.publicationID.hasSuffix(":assessment") ? String(record.publicationID.dropLast(":assessment".count)):record.publicationID
        guard let source=conversation.workerPublications?.first(where:{$0.publicationID==id}) else {
            if runtime.workerResultVersion==0 || !store.productTasks.contains(where:{$0.outcomes.contains(where:{$0.id==id})}) {return}
            throw CodexTaskStoreError.conflict
        }
        guard record.conversationID==conversation.id,source.matches(record) else {throw CodexTaskStoreError.conflict}
        try checkWorkerPublication(source)
    }
    func handleWorkerPublication(_ request: ProductWorkflowRequest, input: AgentInputRecord) throws -> [String:UserViewValue] {
        guard runtime.workerResultVersion==1,let proposed=request.workerPublication,
              proposed.inputID==input.id,input.productTaskID==proposed.taskID,
              let task=store.productTask(proposed.taskID),task.conversationID==conversation.id,canAccessProductTask(task,input:input),
              let execution=task.executions.first(where:{$0.id=="python:\(proposed.workerID):\(proposed.attemptID)"}),
              execution.engine == .python,execution.externalID==proposed.workerID,execution.turnID==proposed.attemptID,
              execution.inputID==input.id,execution.requirementsRevision==proposed.requirementsRevision,
              execution.planVersion==proposed.planVersion else {throw CodexTaskStoreError.conflict}
        try proposed.validate()
        var source=proposed
        if request.operation == .workerPrepare {
            guard source.deliverySessionID==request.runtimeSessionID,source.assessment==nil,source.state=="prepared",source.resumeAfterID==nil else {throw CodexTaskStoreError.conflict}
            // Save actual completed attempt facts before any publication. A new
            // human input may defer delivery but never erases worker results.
            var report=ProductWorkflowRequest(operation:.pythonResult,runtimeSessionID:request.runtimeSessionID,inputID:input.id)
            report.taskID=source.taskID;report.workerID=source.workerID;report.attemptID=source.attemptID
            report.requirementsRevision=source.requirementsRevision;report.planVersion=source.planVersion
            report.resultID=source.publicationID;report.resultDigest=source.resultDigest;report.workerState=source.workerState
            report.observations=request.observations
            _=try handleProductWorkflow(report)
            if latestProductHumanInputID != input.id,let latest=latestProductHumanInputID {
                source.resumeAfterID=conversation.foregroundPublications?.last(where:{$0.inputID==latest && $0.taskID==nil && $0.state=="delivered" && $0.answerKind=="answer"})?.publicationID
            }
            if let previous=conversation.workerPublications?.first(where:{$0.publicationID==source.publicationID}) {
                guard previous.sameSource(as:source) else {throw CodexTaskStoreError.conflict}
                source.state=previous.state;source.assessment=previous.assessment
            }
            try store.updateConversation(conversation.id) {record in
                if let i=record.workerPublications?.firstIndex(where:{$0.publicationID==source.publicationID}) {record.workerPublications![i]=source}
                else {record.workerPublications=(record.workerPublications ?? [])+[source]}
            }
            do {try checkWorkerPublication(source)} catch {return ["schemaVersion":.number(1),"deferred":.boolean(true)]}
            return ["schemaVersion":.number(1),"resumeAfterID":source.resumeAfterID.map(UserViewValue.string) ?? .null]
        }
        guard let saved=conversation.workerPublications?.first(where:{$0.publicationID==source.publicationID}),
              saved.sameSource(as:source),saved.deliverySessionID==request.runtimeSessionID else {throw CodexTaskStoreError.conflict}
        source=saved;try checkWorkerPublication(source)
        guard let body=readResultPublication?(source.publicationID),source.matches(body) else {throw CodexTaskStoreError.conflict}
        if request.operation == .workerFollowup {
            guard source.state=="delivered",let current=store.productTask(task.id),let outcome=current.outcomes.last else {throw CodexTaskStoreError.conflict}
            var next=ProductWorkflowRequest(operation:.continuationContext,runtimeSessionID:request.runtimeSessionID,inputID:input.id)
            next.taskID=task.id;next.requirementsRevision=source.requirementsRevision;next.planVersion=source.planVersion
            next.resultID=outcome.id.hasPrefix("assessment:") ? String(outcome.id.dropFirst("assessment:".count)):outcome.id
            next.resumeAfterID=source.resumeAfterID
            return try handleProductContinuation(next,input:input)
        }
        if request.operation == .workerDelivered {
            guard !body.createDocument || body.panelApplied || body.closed,body.chart==nil || body.chartApplied==true || body.chartClosed==true else {throw CodexTaskStoreError.conflict}
            source.state="delivered"
        }
        else if request.operation == .workerAssessment {
            guard source.state=="delivered",let outcome=store.productTask(task.id)?.outcomes.first(where:{$0.id=="assessment:\(source.publicationID)"}),let actual=outcome.assessment else {throw CodexTaskStoreError.conflict}
            var body="任務核對："+actual.summary
            if !actual.remaining.isEmpty {body+="\n\n尚待處理：\n"+actual.remaining.map {"• "+$0}.joined(separator:"\n")}
            let metadata=ForegroundPublication.Assessment(title:"任務核對",markdownSHA256:ForegroundPublication.digest(body))
            guard source.assessment==nil || source.assessment==metadata else {throw CodexTaskStoreError.conflict}
            source.assessment=metadata
        } else {throw CodexTaskStoreError.conflict}
        try store.updateConversation(conversation.id) {record in
            guard let i=record.workerPublications?.firstIndex(where:{$0.publicationID==source.publicationID}) else {throw CodexTaskStoreError.conflict}
            record.workerPublications![i]=source
        }
        return ["schemaVersion":.number(1)]
    }
}
