import Foundation
import CryptoKit

struct CodexModelChoice: Equatable, Identifiable {
    let id: String
    let model: String
    let displayName: String
    let isDefault: Bool
}

/// Product lifecycle above JSON-RPC. It does not infer product completion from turn completion.
@MainActor final class CodexAdapter {
    let connection: CodexConnection
    let store: CodexTaskStore
    var onEvent: ((UUID, String, UserViewValue) -> Void)?
    var onInteraction: ((UUID, CodexServerRequest) -> Void)?
    var onInteractionResolved: ((CodexRPCID) -> Void)?
    var onIssue: ((String) -> Void)?
    var turnOutputSchema: UserViewValue?
    var developerInstructions: String?
    var workflowContext: ((UUID) throws -> UserViewValue?)?
    var modelID: String?
    var panelTools: [WorkspaceAgentToolDefinition] = []
    var onPanelTool: ((UUID, CodexServerRequest, String, [String: UserViewValue]) async throws -> UserViewValue)?
    private(set) var activePanelCalls: Set<String> = []
    var onAccountNotification: ((String, UserViewValue) -> Void)?
    private var interactions: [CodexRPCID: (UUID, CodexServerRequest)] = [:]
    private var operations = Set<UUID>()
    private var attachedThreads: [String: UUID] = [:]

    init(connection: CodexConnection, store: CodexTaskStore) throws {
        self.connection = connection; self.store = store
        try store.open()
        // Persisted control/identity survive. A previous process's execution state needs inspection.
        for task in store.tasks where task.activeTurnID != nil || task.pendingOperation != nil || task.status == .waitingForUser {
            try store.update(task.id) { $0.status = .needsReconciliation }
        }
        connection.onNotification = { [weak self] method, value in self?.receive(method, value) }
        connection.onServerRequest = { [weak self] request in self?.receive(request) }
        connection.onDisconnect = { [weak self] in self?.disconnected() }
    }

    func authenticationAvailable() async throws -> Bool {
        let result = try await connection.request("account/read", params: .object(["refreshToken": .boolean(false)]))
        if result["requiresOpenaiAuth"] == .boolean(false) { return true }
        return result["account"]?.objectValue != nil
    }

    func models() async throws -> [CodexModelChoice] {
        var choices: [CodexModelChoice] = [], cursors: Set<String> = [], cursor: String?
        repeat {
            var params: [String: UserViewValue] = ["limit": .number(100), "includeHidden": .boolean(false)]
            if let cursor { params["cursor"] = .string(cursor) }
            let result = try await connection.request("model/list", params: .object(params))
            guard let data = result["data"]?.arrayValue else { throw CodexConnectionError.protocolViolation("Codex 模型清單格式不正確。") }
            for value in data {
                guard let id = value["id"]?.stringValue, !id.isEmpty, let model = value["model"]?.stringValue, !model.isEmpty else {
                    throw CodexConnectionError.protocolViolation("Codex 模型缺少識別碼。")
                }
                choices.append(.init(id: id, model: model, displayName: value["displayName"]?.stringValue ?? model, isDefault: value["isDefault"] == .boolean(true)))
            }
            cursor = result["nextCursor"]?.stringValue
            if let cursor, !cursors.insert(cursor).inserted { throw CodexConnectionError.protocolViolation("Codex 模型清單分頁重複。") }
            guard choices.count <= 1000, cursors.count <= 20 else { throw CodexConnectionError.protocolViolation("Codex 模型清單超出大小限制。") }
        } while cursor != nil
        guard Set(choices.map(\.id)).count == choices.count else { throw CodexConnectionError.protocolViolation("Codex 模型識別碼重複。") }
        return choices
    }

    var attachedTaskIDs: [UUID] {
        guard connection.state == .ready else { return [] }
        return store.tasks.filter { task in task.threadID.map { attachedThreads[$0] == connection.connectionID } ?? false }.map(\.id)
    }

    func backgroundTerminals(_ id: UUID) async throws -> [UserViewValue] {
        let task = try requireTask(id)
        guard connection.state == .ready, connection.experimentalAPI, let thread = task.threadID,
              attachedThreads[thread] == connection.connectionID else {
            throw CodexTaskStoreError.unavailable("無法確認此 Codex 任務的背景程序；主 Agent 保持暫停。")
        }
        var values: [UserViewValue] = [], cursors: Set<String> = [], cursor: String?
        repeat {
            var params: [String: UserViewValue] = ["threadId": .string(thread), "limit": .number(100)]
            if let cursor { params["cursor"] = .string(cursor) }
            let response = try await connection.request("thread/backgroundTerminals/list", params: .object(params), timeout: .seconds(5))
            guard let data = response["data"]?.arrayValue,
                  data.allSatisfy({ $0["processId"]?.stringValue?.isEmpty == false }),
                  response["nextCursor"] == nil || response["nextCursor"] == .null || response["nextCursor"]?.stringValue != nil else {
                throw CodexConnectionError.protocolViolation("Codex 背景程序清單格式不正確。")
            }
            values.append(contentsOf: data); cursor = response["nextCursor"]?.stringValue
            if let cursor, !cursors.insert(cursor).inserted { throw CodexConnectionError.protocolViolation("Codex 背景程序分頁重複。") }
            guard values.count <= 1000, cursors.count <= 20 else { throw CodexConnectionError.protocolViolation("Codex 背景程序清單超出限制。") }
        } while cursor != nil
        guard Set(values.compactMap { $0["processId"]?.stringValue }).count == values.count else {
            throw CodexConnectionError.protocolViolation("Codex 背景程序識別碼重複。")
        }
        return values
    }

    func stopBackgroundTerminals(_ id: UUID, allowActive: Bool = false) async throws {
        let task = try requireTask(id)
        guard allowActive || task.activeTurnID == nil && task.pendingOperation == nil else {
            throw CodexTaskStoreError.unavailable("先停止 Codex 回合，再清理背景程序。")
        }
        let before = try await backgroundTerminals(id)
        guard !before.isEmpty, let thread = task.threadID else { return }
        _ = try await connection.request("thread/backgroundTerminals/clean", params: .object(["threadId": .string(thread)]), timeout: .seconds(5))
        let deadline = Date().addingTimeInterval(5)
        while !(try await backgroundTerminals(id)).isEmpty {
            guard Date() < deadline else { throw CodexConnectionError.outcomeUnknown("Codex 背景程序仍在執行；不能交回麥芽糖。") }
            try await Task.sleep(for: .milliseconds(100))
        }
        let receipt: UserViewValue = .object(["method": .string("thread/backgroundTerminals/clean"), "verifiedStopped": .boolean(true),
            "processIDs": .array(before.compactMap { $0["processId"] })])
        try store.append(.init(id: "background-clean:" + UUID().uuidString, author: .integration, origin: .synchronization,
            content: String(decoding: try JSONEncoder().encode(receipt), as: UTF8.self), threadID: thread, turnID: task.lastFinishedTurnID), to: id)
    }

    /// The caller provisions an isolated worktree and persists its baseline before calling this.
    /// A thread-less uncertain creation is retained for reconciliation, not automatically recreated.
    func createTask(_ task: CodexTaskRecord) async throws -> UUID {
        guard connection.state == .ready else { throw CodexConnectionError.disconnected }
        var prepared = task; prepared.model = task.model ?? modelID
        prepared.panelToolsRegistered = !panelTools.isEmpty
        try store.create(prepared)
        try beginOperation(task.id, kind: .startThread)
        defer { operations.remove(task.id) }
        do {
            var params: [String: UserViewValue] = [
                "cwd": .string(task.worktreePath), "sandbox": .string("workspace-write"),
                "approvalPolicy": .string("on-request"), "serviceName": .string("maltose")
            ]
            if let model = prepared.model { params["model"] = .string(model) }
            if let developerInstructions { params["developerInstructions"] = .string(developerInstructions) }
            if !panelTools.isEmpty {
                guard connection.experimentalAPI else { throw CodexConnectionError.unavailable("共用面板工具需要 Codex experimentalApi 支援。") }
                params["dynamicTools"] = .array(panelTools.map { .object([
                    "type": .string("function"), "name": .string($0.name), "description": .string($0.description),
                    "inputSchema": .object($0.inputSchema)]) })
            }
            let response = try await connection.request("thread/start", params: .object(params))
            let thread = try requireThread(response, expectedID: nil, worktree: task.worktreePath)
            try store.update(task.id) { $0.threadID = thread; $0.pendingOperation = nil; $0.model = prepared.model ?? response["model"]?.stringValue }
            attachedThreads[thread] = connection.connectionID
            return task.id
        } catch { try recordFailure(task.id, error); throw error }
    }

    /// Text provenance is explicit; viewing another panel never changes this task mapping.
    @discardableResult func submit(_ text: String, to id: UUID, author: CodexMessageAuthor, origin: CodexMessageOrigin,
                                   messageID: String = UUID().uuidString) async throws -> String {
        let task = try requireTask(id)
        guard task.status != .needsReconciliation, task.status != .completed, task.status != .waitingForUser,
              let thread = task.threadID else {
            throw CodexTaskStoreError.invalid("請先核對 Codex 任務狀態，或回覆目前等待中的問題。")
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              (author == .user && (origin == .native || origin == .voice)) || (author == .maltose && origin == .delegation) else {
            throw CodexTaskStoreError.invalid("Codex 輸入缺少內容或有效來源。")
        }
        if let existing = task.messages.first(where: { $0.id == messageID }) {
            guard existing.author == author, existing.origin == origin, existing.content == text else { throw CodexTaskStoreError.conflict }
            if existing.delivery == .accepted, let turn = existing.turnID { return turn }
            throw CodexConnectionError.outcomeUnknown("previous input")
        }
        let connectionID = connection.connectionID
        let active = task.activeTurnID
        try beginOperation(id, kind: active == nil ? .startTurn : .steerTurn, clientMessageID: messageID)
        defer { operations.remove(id) }
        do {
            try store.append(.init(id: messageID, author: author, origin: origin, content: text, threadID: thread,
                                   turnID: active, delivery: .prepared), to: id)
            var input: [UserViewValue] = [.object(["type": .string("text"), "text": .string(text)])]
            if let context = try workflowContext?(id) {
                let data = try JSONEncoder().encode(context)
                guard data.count <= 128 * 1024 else { throw CodexTaskStoreError.invalid("共同任務的委派摘要超出限制。") }
                input.append(.object(["type": .string("text"), "text": .string(String(decoding: data, as: UTF8.self))]))
            }
            var params: [String: UserViewValue] = ["threadId": .string(thread), "clientUserMessageId": .string(messageID), "input": .array(input)]
            if let active { params["expectedTurnId"] = .string(active) }
            else if let turnOutputSchema { params["outputSchema"] = turnOutputSchema }
            let response = try await connection.request(active == nil ? "turn/start" : "turn/steer", params: .object(params))
            guard let turnID = active == nil ? response["turn"]?["id"]?.stringValue : response["turnId"]?.stringValue,
                  !turnID.isEmpty else { throw CodexConnectionError.protocolViolation("Codex 未回傳回合識別碼。") }
            let connected = connection.state == .ready && connection.connectionID == connectionID
            try store.update(id) { record in
                record.pendingOperation = nil
                if let index = record.messages.firstIndex(where: { $0.id == messageID }) {
                    record.messages[index].turnID = turnID; record.messages[index].delivery = .accepted
                }
                // Completion can arrive before the RPC response. Do not resurrect a finished turn.
                if record.lastFinishedTurnID != turnID {
                    record.activeTurnID = turnID
                    if record.status != .waitingForUser && record.status != .needsReconciliation {
                        record.status = connected ? .running : .needsReconciliation
                    }
                }
            }
            return turnID
        } catch { try recordFailure(id, error); throw error }
    }

    func interrupt(_ id: UUID) async throws {
        let task = try requireTask(id)
        guard let thread = task.threadID, let turn = task.activeTurnID else {
            throw CodexTaskStoreError.invalid("沒有已確認正在執行的 Codex 回合。")
        }
        try beginOperation(id, kind: .interruptTurn)
        defer { operations.remove(id) }
        do {
            do {
                _ = try await connection.request("turn/interrupt", params: .object(["threadId": .string(thread), "turnId": .string(turn)]))
            } catch let rejected as CodexRPCFailure {
                // The turn can finish (or still be registering) between start and interrupt.
                // Inspect the same thread/turn; a rejected cancellation is not task failure.
                try store.update(id) { $0.pendingOperation = nil }
                operations.remove(id)
                try await reconcile(id)
                let inspected = try requireTask(id)
                if inspected.activeTurnID == nil, inspected.lastFinishedTurnID == turn { return }
                guard inspected.activeTurnID == turn else { throw rejected }
                try await Task.sleep(for: .milliseconds(100))
                try beginOperation(id, kind: .interruptTurn)
                _ = try await connection.request("turn/interrupt", params: .object(["threadId": .string(thread), "turnId": .string(turn)]))
            }
            // RPC acceptance is not proof that tools/processes have stopped. Wait for terminal event.
            try store.update(id) { $0.pendingOperation = nil }
        } catch { try recordFailure(id, error); throw error }
    }

    /// Reattach/read before issuing any new mutation. A missing turn remains uncertain.
    func attachIfNeeded(_ id: UUID) async throws {
        let task = try requireTask(id)
        guard let thread = task.threadID else { throw CodexTaskStoreError.invalid("Codex 建立結果未確認，不能自動另建任務。") }
        if task.status == .needsReconciliation || attachedThreads[thread] != connection.connectionID { try await reconcile(id) }
    }

    func reconcile(_ id: UUID) async throws {
        let task = try requireTask(id)
        guard !operations.contains(id), let thread = task.threadID else {
            throw CodexTaskStoreError.invalid("Codex 建立結果未確認，不能自動另建任務。")
        }
        operations.insert(id); defer { operations.remove(id) }
        try store.update(id) { if $0.status != .completed { $0.status = .needsReconciliation } }
        var resumeParams: [String: UserViewValue] = [
            "threadId": .string(thread), "cwd": .string(task.worktreePath),
            "sandbox": .string("workspace-write"), "approvalPolicy": .string("on-request"), "excludeTurns": .boolean(true)
        ]
        if let model = task.model { resumeParams["model"] = .string(model) }
        let resumed = try await connection.request("thread/resume", params: .object(resumeParams))
        _ = try requireThread(resumed, expectedID: thread, worktree: task.worktreePath)
        attachedThreads[thread] = connection.connectionID
        let response: UserViewValue
        do {
            response = try await connection.request("thread/read", params: .object(["threadId": .string(thread), "includeTurns": .boolean(true)]))
        } catch let error as CodexRPCFailure where error.code == -32601 {
            // Older storage backends lack paginated history. Use the documented full-history
            // resume response only when the server explicitly reports that method unsupported.
            resumeParams.removeValue(forKey: "excludeTurns")
            response = try await connection.request("thread/resume", params: .object(resumeParams))
        }
        _ = try requireThread(response, expectedID: thread, worktree: task.worktreePath)
        if task.status == .completed, task.activeTurnID == nil, task.pendingOperation == nil { return }
        let turns = response["thread"]?["turns"]?.arrayValue ?? []
        let relevant: UserViewValue?
        if let messageID = task.pendingOperation?.clientMessageID {
            relevant = turns.last { turn in
                (turn["items"]?.arrayValue ?? []).contains { $0["type"]?.stringValue == "userMessage" && $0["clientId"]?.stringValue == messageID }
            }
            guard relevant != nil else { throw CodexConnectionError.outcomeUnknown("turn/start or turn/steer") }
        } else if let active = task.activeTurnID {
            relevant = turns.first { $0["id"]?.stringValue == active }
            guard relevant != nil else { throw CodexConnectionError.outcomeUnknown("thread/read active turn") }
        } else { relevant = turns.last }
        if let relevant {
            guard let turn = relevant["id"]?.stringValue, let status = relevant["status"]?.stringValue else {
                throw CodexConnectionError.protocolViolation("Codex 回合紀錄不完整。")
            }
            try store.update(id) { record in
                record.activeTurnID = turn; record.pendingOperation = nil
                if let messageID = task.pendingOperation?.clientMessageID,
                   let index = record.messages.firstIndex(where: { $0.id == messageID }) {
                    record.messages[index].delivery = .accepted; record.messages[index].turnID = turn
                }
            }
            for item in relevant["items"]?.arrayValue ?? [] { try saveItem(item, taskID: id, turnID: turn) }
            if status == "inProgress" {
                let flags = response["thread"]?["status"]?["activeFlags"]?.arrayValue ?? []
                let waiting = flags.contains(.string("waitingOnApproval")) || flags.contains(.string("waitingOnUserInput"))
                    || interactions.values.contains { $0.0 == id }
                try store.update(id) { $0.status = waiting ? .waitingForUser : .running }
            } else { try finishTurn(relevant, taskID: id) }
        } else {
            guard task.pendingOperation == nil else { throw CodexConnectionError.outcomeUnknown("thread/read") }
            try store.update(id) { $0.status = .prepared }
        }
    }

    /// Only a human UI/controller can supply this response, scoped to its original connection.
    @discardableResult func respond(to request: CodexServerRequest, result: Result<UserViewValue, CodexRPCFailure>, origin: CodexMessageOrigin = .native) -> Bool {
        guard let (id, original) = interactions[request.id], original.connectionID == request.connectionID,
              let task = store.task(id), task.threadID == request.params["threadId"]?.stringValue,
              task.activeTurnID == request.params["turnId"]?.stringValue else { return false }
        let receiptID = interactionID(request, kind: "response")
        guard !task.messages.contains(where: { $0.id == receiptID }) else { return false }
        do {
            let recorded: UserViewValue
            switch result {
            case let .success(value):
                var safe = value.objectValue ?? [:]
                if var answers = safe["answers"]?.objectValue {
                    for question in request.params["questions"]?.arrayValue ?? [] where question["isSecret"] == .boolean(true) {
                        if let id = question["id"]?.stringValue, answers[id] != nil {
                            answers[id] = .object(["answers": .strings(["[已隱藏的回答]"])])
                        }
                    }
                    safe["answers"] = .object(answers)
                }
                recorded = .object(["method": .string(request.method), "result": .object(safe)])
            case let .failure(error): recorded = .object(["method": .string(request.method), "error": .string(error.message)])
            }
            try store.append(.init(id: receiptID, author: .integration, origin: origin,
                content: String(decoding: try JSONEncoder().encode(recorded), as: UTF8.self),
                threadID: task.threadID, turnID: task.activeTurnID, delivery: .prepared), to: id)
            let sent = connection.respond(to: original, result: result)
            try store.update(id) { record in
                if let index = record.messages.firstIndex(where: { $0.id == receiptID }) { record.messages[index].delivery = sent ? .accepted : .uncertain }
            }
            return sent
        } catch { issue(error); return false }
    }

    private func interactionID(_ request: CodexServerRequest, kind: String) -> String {
        let id = (try? JSONEncoder().encode(request.id).base64EncodedString()) ?? "invalid"
        return "codex-interaction:\(request.connectionID.uuidString):\(kind):\(id)"
    }

    private func beginOperation(_ id: UUID, kind: CodexTaskRecord.Operation.Kind, clientMessageID: String? = nil) throws {
        let task = try requireTask(id)
        guard !operations.contains(id), task.pendingOperation == nil else {
            throw CodexTaskStoreError.invalid("Codex 上一次操作尚未確認。")
        }
        try store.update(id) { $0.pendingOperation = .init(id: UUID(), kind: kind, clientMessageID: clientMessageID, phase: .prepared) }
        operations.insert(id)
    }
    private func recordFailure(_ id: UUID, _ error: Error) throws {
        try store.update(id) { task in
            task.failureMessage = error.localizedDescription
            if let messageID = task.pendingOperation?.clientMessageID,
               let index = task.messages.firstIndex(where: { $0.id == messageID }) {
                task.messages[index].delivery = error is CodexRPCFailure ? .rejected : .uncertain
            }
            if error is CodexRPCFailure {
                let creation = task.pendingOperation?.kind == .startThread
                task.pendingOperation = nil
                if creation { task.status = .failed }
                else if task.activeTurnID != nil { task.status = .needsReconciliation }
            }
            else { task.pendingOperation?.phase = .uncertain; task.status = .needsReconciliation }
        }
    }
    private func requireTask(_ id: UUID) throws -> CodexTaskRecord {
        guard let task = store.task(id) else { throw CodexTaskStoreError.invalid("找不到 Codex 任務。") }
        return task
    }
    private func requireThread(_ response: UserViewValue, expectedID: String?, worktree: String) throws -> String {
        guard let id = response["thread"]?["id"]?.stringValue, !id.isEmpty,
              expectedID == nil || id == expectedID,
              let cwd = response["thread"]?["cwd"]?.stringValue,
              URL(fileURLWithPath: cwd).standardizedFileURL.path == URL(fileURLWithPath: worktree).standardizedFileURL.path else {
            throw CodexConnectionError.protocolViolation("Codex 回傳的對話或工作目錄不符。")
        }
        return id
    }
    private func receivePanelTool(_ request: CodexServerRequest) {
        guard request.connectionID == connection.connectionID, connection.state == .ready,
              let thread = request.params["threadId"]?.stringValue, let turn = request.params["turnId"]?.stringValue,
              let call = request.params["callId"]?.stringValue, !call.isEmpty, call.count <= 256,
              let tool = request.params["tool"]?.stringValue, panelTools.contains(where: { $0.name == tool }),
              request.params["namespace"] == nil || request.params["namespace"] == .null,
              let arguments = request.params["arguments"]?.objectValue,
              let task = store.tasks.first(where: { $0.threadID == thread && $0.activeTurnID == turn }),
              task.panelToolsRegistered == true else {
            _ = connection.respond(to: request, result: .failure(.init(code: -32602, message: "面板工具不屬於目前的 Codex 任務或未註冊。")))
            return
        }
        do {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
            let identityData = try encoder.encode([task.id.uuidString, turn, call])
            let key = "panel:" + SHA256.hash(data: identityData).map { String(format: "%02x", $0) }.joined()
            let payload = try encoder.encode(UserViewValue.object(["tool": .string(tool), "arguments": .object(arguments)]))
            guard payload.count <= 256 * 1024 else { throw CodexTaskStoreError.invalid("面板工具參數超出大小限制。") }
            let content = String(decoding: payload, as: UTF8.self)
            if let saved = task.messages.first(where: { $0.id == key + ":request" }) {
                guard saved.content == content, saved.author == .codex else { throw CodexTaskStoreError.conflict }
                let response = task.messages.first { $0.id == key + ":response" }
                let value = try response.map { try JSONDecoder().decode(UserViewValue.self, from: Data($0.content.utf8)) }
                    ?? Self.panelFailure("outcome_unknown", "此面板操作已開始，尚無已保存的結果；請先核對實際狀態，不要重送。")
                _ = connection.respond(to: request, result: .success(value))
                return
            }
            guard activePanelCalls.count < 8 else { throw CodexTaskStoreError.unavailable("面板操作正在處理，請稍後再試。") }
            try store.append(.init(id: key + ":request", author: .codex, origin: .codex, content: content,
                threadID: thread, turnID: turn, delivery: .accepted), to: task.id)
            activePanelCalls.insert(key)
            Task { @MainActor [weak self] in
                guard let self else { return }
                defer {
                    self.activePanelCalls.remove(key)
                    self.onEvent?(task.id, "maltose/panelTool/completed", .object(["turnId": .string(turn)]))
                }
                do {
                    let value: UserViewValue
                    do {
                        guard request.connectionID == self.connection.connectionID,
                              self.store.task(task.id)?.activeTurnID == turn, let execute = self.onPanelTool else {
                            throw CodexTaskStoreError.unavailable("面板工具連線或回合已失效。")
                        }
                        let result = try await execute(task.id, request, tool, arguments)
                        let data = try encoder.encode(result)
                        guard data.count <= 3 * 1024 * 1024 else { throw CodexTaskStoreError.invalid("面板工具結果超出大小限制。") }
                        value = .object(["success": .boolean(result["ok"] == .boolean(true)), "contentItems": .array([
                            .object(["type": .string("inputText"), "text": .string(String(decoding: data, as: UTF8.self))])])])
                    } catch { value = Self.panelFailure("outcome_unknown", error.localizedDescription + " 請先核對實際面板狀態，不要重送操作。") }
                    try self.store.append(.init(id: key + ":response", author: .tool, origin: .synchronization,
                        content: String(decoding: try encoder.encode(value), as: UTF8.self), threadID: thread, turnID: turn, delivery: .prepared), to: task.id)
                    let sent = self.store.task(task.id)?.activeTurnID == turn && self.connection.respond(to: request, result: .success(value))
                    try self.store.update(task.id) { record in
                        if let index = record.messages.firstIndex(where: { $0.id == key + ":response" }) { record.messages[index].delivery = sent ? .accepted : .uncertain }
                    }
                } catch { self.issue(error) }
            }
        } catch {
            _ = connection.respond(to: request, result: .failure(.init(code: -32602, message: error.localizedDescription)))
        }
    }

    private static func panelFailure(_ code: String, _ message: String) -> UserViewValue {
        let data = try? JSONEncoder().encode(UserViewValue.object(["ok": .boolean(false), "retryable": .boolean(false),
            "error": .object(["code": .string(code), "message": .string(message)])]))
        return .object(["success": .boolean(false), "contentItems": .array([.object([
            "type": .string("inputText"), "text": .string(String(decoding: data ?? Data(), as: UTF8.self))])])])
    }

    private func receive(_ request: CodexServerRequest) {
        if request.method == "item/tool/call" { receivePanelTool(request); return }
        let supported: Set<String> = ["item/commandExecution/requestApproval", "item/fileChange/requestApproval",
            "item/permissions/requestApproval", "item/tool/requestUserInput", "mcpServer/elicitation/request"]
        guard supported.contains(request.method),
              let thread = request.params["threadId"]?.stringValue, let turn = request.params["turnId"]?.stringValue,
              let task = store.tasks.first(where: { $0.threadID == thread && $0.activeTurnID == turn }) else {
            _ = connection.respond(to: request, result: .failure(.init(code: -32601, message: "不支援的請求，或不屬於目前的 Codex 任務。")))
            return
        }
        do {
            let content = UserViewValue.object(["method": .string(request.method), "params": request.params])
            try store.append(.init(id: interactionID(request, kind: "request"), author: .integration, origin: .codex,
                content: String(decoding: try JSONEncoder().encode(content), as: UTF8.self),
                threadID: task.threadID, turnID: task.activeTurnID), to: task.id)
            try store.update(task.id) { $0.status = .waitingForUser }
            interactions[request.id] = (task.id, request)
            if let onInteraction { onInteraction(task.id, request) }
            else { _ = respond(to: request, result: .failure(.init(code: -32601, message: "尚無可用的人員確認介面。")), origin: .synchronization) }
        } catch { issue(error) }
    }
    private func receive(_ method: String, _ value: UserViewValue) {
        if method == "account/login/completed" || method == "account/updated" {
            onAccountNotification?(method, value); return
        }
        guard let thread = value["threadId"]?.stringValue,
              let task = store.tasks.first(where: { $0.threadID == thread }) else { return }
        do {
            switch method {
            case "turn/started":
                guard let turn = value["turn"]?["id"]?.stringValue else { return }
                if task.lastFinishedTurnID == turn { return }
                guard task.activeTurnID == nil || task.activeTurnID == turn else { return }
                try store.update(task.id) { $0.activeTurnID = turn; $0.status = .running; $0.failureMessage = nil }
            case "turn/completed":
                guard let active = task.activeTurnID, value["turn"]?["id"]?.stringValue == active else { return }
                for item in value["turn"]?["items"]?.arrayValue ?? [] {
                    try saveItem(item, taskID: task.id, turnID: active)
                }
                if let turn = value["turn"] { try finishTurn(turn, taskID: task.id) }
            case "item/completed":
                guard let turn = value["turnId"]?.stringValue, turn == task.activeTurnID, let item = value["item"] else { return }
                try saveItem(item, taskID: task.id, turnID: turn)
            case "item/started":
                guard let turn = value["turnId"]?.stringValue, turn == task.activeTurnID, let item = value["item"] else { return }
                try saveProductOrigin(item, taskID: task.id, turnID: turn)
            case "serverRequest/resolved":
                guard let rawID = value["requestId"], let data = try? JSONEncoder().encode(rawID),
                      let requestID = try? JSONDecoder().decode(CodexRPCID.self, from: data),
                      interactions[requestID]?.0 == task.id else { return }
                interactions.removeValue(forKey: requestID); onInteractionResolved?(requestID)
                if !interactions.values.contains(where: { $0.0 == task.id }), task.activeTurnID != nil {
                    try store.update(task.id) { $0.status = .running }
                }
            default:
                if let turn = value["turnId"]?.stringValue, turn != task.activeTurnID { return }
            }
            onEvent?(task.id, method, value)
        } catch { issue(error) }
    }
    private func saveItem(_ item: UserViewValue, taskID: UUID, turnID: String) throws {
        guard let itemID = item["id"]?.stringValue, let type = item["type"]?.stringValue else { return }
        let task = try requireTask(taskID)
        if type == "agentMessage", let text = item["text"]?.stringValue {
            try store.append(.init(id: "codex:\(turnID):\(itemID)", author: .codex, origin: .codex,
                                   content: text, threadID: task.threadID, turnID: turnID), to: taskID)
        } else if type == "commandExecution" || type == "fileChange" {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
            let data = try encoder.encode(item)
            try store.append(.init(id: "codex:\(turnID):\(itemID)", author: .tool, origin: .codex,
                                   content: String(decoding: data, as: UTF8.self), threadID: task.threadID, turnID: turnID), to: taskID)
        }
    }

    private func saveProductOrigin(_ item: UserViewValue, taskID: UUID, turnID: String) throws {
        guard let itemID = item["id"]?.stringValue, let type = item["type"]?.stringValue,
              ["commandExecution", "fileChange"].contains(type), let task = store.task(taskID),
              let product = task.productTaskID.flatMap(store.productTask) else { return }
        let accepted = task.messages.last { ($0.author == .user || $0.author == .maltose) && $0.turnID == turnID && $0.delivery == .accepted }
        let starting = task.pendingOperation?.kind == .startTurn ? task.pendingOperation?.clientMessageID : nil
        guard let inputID = accepted?.id ?? starting,
              let execution = product.executions.last(where: { $0.engine == .codex && $0.externalID == taskID.uuidString && $0.inputID == inputID }) else { return }
        let origin = CodexProductObservationOrigin(itemID: itemID, itemType: type, executionID: execution.id,
            requirementsRevision: execution.requirementsRevision, planVersion: execution.planVersion, command: item["command"]?.stringValue)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let identity = CodexProductObservation.originID(turn: turnID, item: itemID)
        if task.messages.contains(where: { $0.id == identity }) { return }
        try store.append(.init(id: identity, author: .integration, origin: .synchronization,
            content: String(decoding: try encoder.encode(origin), as: UTF8.self), threadID: task.threadID, turnID: turnID, delivery: .accepted), to: taskID)
    }
    private func finishTurn(_ turn: UserViewValue, taskID: UUID) throws {
        guard let id = turn["id"]?.stringValue, let status = turn["status"]?.stringValue,
              ["completed", "failed", "interrupted"].contains(status) else {
            throw CodexConnectionError.protocolViolation("無法確認 Codex 回合的結束狀態。")
        }
        try store.update(taskID) { task in
            task.activeTurnID = nil; task.lastFinishedTurnID = id
            task.status = status == "completed" ? .awaitingReview : (status == "failed" ? .failed : .interrupted)
            task.failureMessage = status == "failed" ? turn["error"]?["message"]?.stringValue : nil
        }
        let resolved = interactions.filter { $0.value.0 == taskID }.map(\.key)
        for requestID in resolved { interactions.removeValue(forKey: requestID); onInteractionResolved?(requestID) }
    }
    private func disconnected() {
        let resolved = Array(interactions.keys); interactions.removeAll()
        resolved.forEach { onInteractionResolved?($0) }
        do {
            for task in store.tasks where task.activeTurnID != nil || task.pendingOperation != nil {
                try store.update(task.id) { $0.status = .needsReconciliation; $0.pendingOperation?.phase = .uncertain }
            }
        } catch { onIssue?(error.localizedDescription) }
        if !connection.ownedCleanupConfirmed {
            onIssue?("Codex 背景程序清理尚未確認；麥芽糖保持暫停，請先檢查程序狀態。")
        }
    }
    private func issue(_ error: Error) {
        onIssue?(error.localizedDescription)
        connection.stop()
    }
}

extension UserViewValue {
    var arrayValue: [UserViewValue]? {
        switch self { case let .array(values): values; case let .strings(values): values.map(Self.string); default: nil }
    }
}
