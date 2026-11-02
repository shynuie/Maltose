import Foundation
import Combine

struct AgentActivityEntry: Identifiable, Equatable {
    let id: UUID
    let date: Date
    let engine: String
    let text: String
    let taskID: UUID?
    let failed: Bool
    var repetitions = 1
}

enum WorkProgressState: String, Equatable {
    case pending, running, completed, paused, needsInput, failed, cancelled, uncertain, reviewing
    var title: String {
        switch self {
        case .pending: "待執行"
        case .running: "執行中"
        case .completed: "已完成"
        case .paused: "已暫停"
        case .needsInput: "等待回覆"
        case .failed: "執行失敗"
        case .cancelled: "已取消"
        case .uncertain: "待核對執行結果"
        case .reviewing: "核對與交付中"
        }
    }
    var animated: Bool { self == .running || self == .reviewing }
}

struct WorkProgressNode: Identifiable, Equatable {
    let id: String
    let taskID: UUID
    let title: String
    var state: WorkProgressState
    var fraction: Double?
    var detail: String
    var engine: String
    var children: [WorkProgressNode] = []
    var leafCount: Int { children.isEmpty ? 1 : children.reduce(0) { $0 + $1.leafCount } }
    var completedLeaves: Int { children.isEmpty ? (state == .completed ? 1 : 0) : children.reduce(0) { $0 + $1.completedLeaves } }
}

/// Read-only projections of the existing task store and observed runtime events.
/// Progress reports never close a product task or create execution permission.
@MainActor final class AgentWorkMonitor: ObservableObject {
    @Published private(set) var roots: [WorkProgressNode] = []
    @Published private(set) var entries: [AgentActivityEntry] = []
    @Published private(set) var collapsed: Set<String> = []
    @Published private(set) var selectedTaskID: UUID?
    @Published private(set) var selectionRevision = 0
    let scrollState = ConversationAutoScrollState()
    var onSelectTask: ((UUID) -> Void)?
    var onProgressNeeded: (() -> Void)?
    private var hasSnapshot = false
    private var knownStates: [String: WorkProgressState] = [:]
    private var knownSteps: [String: WorkProgressState] = [:]
    private var runtimeActivities: Set<String> = []
    private var eventSessionID: String?
    private var codexPlans: [UUID: (turn: String, steps: [(String, WorkProgressState)])] = [:]

    func append(engine: String, text: String, taskID: UUID? = nil, failed: Bool = false, at date: Date = Date()) {
        if let last = entries.last, last.engine == engine, last.text == text, last.taskID == taskID,
           last.failed == failed, date.timeIntervalSince(last.date) < 3 {
            entries[entries.count - 1].repetitions += 1
        } else {
            entries.append(.init(id: UUID(), date: date, engine: engine, text: String(text.prefix(300)), taskID: taskID, failed: failed))
            if entries.count > 500 { entries.removeFirst(entries.count - 500) }
        }
    }

    func update(tasks: [ProductTask], codexTasks: [CodexTaskRecord]) {
        let logChanges = hasSnapshot
        hasSnapshot = true
        let ids = Set(tasks.map(\.id))
        func state(_ task: ProductTask) -> WorkProgressState {
            switch task.state {
            case .completed: return .completed
            case .held: return .paused
            case .cancelled: return .cancelled
            case .needsInput: return .needsInput
            case .awaitingEvidence, .partial:
                let current = task.executions.filter { $0.requirementsRevision == task.requirementsRevision && $0.planVersion == task.planVersion }
                if current.contains(where: { $0.state == .uncertain }) { return .uncertain }
                if current.last?.state == .failed { return .failed }
                return .reviewing
            case .running: return .running
            case .planned:
                let progress = (task.stepProgress ?? []).filter { $0.requirementsRevision == task.requirementsRevision && $0.planVersion == task.planVersion }
                if progress.contains(where: { $0.state == .failed }) { return .failed }
                if progress.contains(where: { $0.state == .running || $0.state == .completed }) { return .running }
                return .pending
            }
        }
        func executionState(_ execution: ProductExecution) -> WorkProgressState {
            switch execution.state {
            case .prepared: .pending
            case .running: .running
            case .succeeded: .completed
            case .failed: .failed
            case .cancelled: .cancelled
            case .uncertain: .uncertain
            }
        }
        func build(_ task: ProductTask, depth: Int) -> WorkProgressNode {
            let taskState = state(task), taskID = task.id
            let current = task.executions.filter { $0.requirementsRevision == task.requirementsRevision && $0.planVersion == task.planVersion }
            let progress = (task.stepProgress ?? []).filter { $0.requirementsRevision == task.requirementsRevision && $0.planVersion == task.planVersion }
            let allSteps = task.plan.steps
            func stepNode(_ step: ProductPlanStep, depth: Int) -> WorkProgressNode {
                let children = depth < 16 ? allSteps.filter { $0.parentID == step.id }.map { stepNode($0, depth: depth + 1) } : []
                let matching = current.last(where: { $0.externalID == step.id })
                let reported = progress.first { $0.stepID == step.id }
                let s: WorkProgressState = taskState == .completed ? .completed : matching.map(executionState) ?? reported.map {
                    switch $0.state { case .pending: .pending; case .running: .running; case .completed: .completed; case .failed: .failed }
                } ?? .pending
                var node = WorkProgressNode(id: "step:\(taskID):\(step.id)", taskID: taskID,
                    title: String(step.title.prefix(180)), state: s, fraction: s == .completed ? 1 : s == .pending ? 0 : nil,
                    detail: reported?.detail ?? "", engine: matching?.engine == .python ? "背景工作" : "麥芽糖", children: children)
                if !children.isEmpty {
                    node.fraction = Double(node.completedLeaves) / Double(max(1, node.leafCount))
                    if children.allSatisfy({ $0.state == .completed }) { node.state = .completed }
                    else if children.contains(where: { $0.state == .failed }) { node.state = .failed }
                    else if children.contains(where: { $0.state.animated }) { node.state = .running }
                    else { node.state = .pending }
                }
                if taskState == .paused || taskState == .cancelled, node.state != .completed { node.state = taskState }
                return node
            }
            var children = allSteps.filter { $0.parentID == nil }.map { stepNode($0, depth: 0) }
            if depth < 16 {
                children += tasks.filter { $0.parentID == taskID }.map { build($0, depth: depth + 1) }
            }
            for codex in codexTasks.filter({ $0.productTaskID == taskID }) {
                let turn = codex.activeTurnID ?? codex.lastFinishedTurnID
                let plan = codexPlans[codex.id].flatMap { $0.turn == turn ? $0.steps : nil } ?? []
                let execution = current.last { $0.engine == .codex && $0.externalID == codex.id.uuidString }
                let s = taskState == .completed ? WorkProgressState.completed : execution.map(executionState) ?? .pending
                let steps = plan.enumerated().map { index, item in
                    WorkProgressNode(id: "codex-step:\(codex.id):\(turn ?? ""):\(index)", taskID: taskID,
                                     title: item.0, state: taskState == .completed ? .completed : taskState == .paused || taskState == .cancelled ? taskState : item.1, fraction: taskState == .completed || item.1 == .completed ? 1 : item.1 == .pending ? 0 : nil,
                                     detail: "", engine: "Codex")
                }
                children.append(.init(id: "codex:\(codex.id)", taskID: taskID, title: "Codex · \(String(codex.delegation.objective.prefix(100)))",
                    state: taskState == .paused || taskState == .cancelled ? taskState : s,
                    fraction: steps.isEmpty ? (s == .completed ? 1 : nil) : Double(steps.filter { $0.state == .completed }.count) / Double(steps.count),
                    detail: codex.status == .waitingForUser ? "等待回覆" : "", engine: "Codex", children: steps))
            }
            let completed = taskState == .completed
            children.append(.init(id: "review:\(taskID)", taskID: taskID, title: "核對並交付",
                state: completed ? .completed : taskState == .reviewing ? .reviewing : taskState == .needsInput ? .needsInput : taskState == .paused || taskState == .cancelled ? taskState : .pending,
                fraction: completed ? 1 : 0, detail: "", engine: "麥芽糖"))
            let done = children.reduce(0) { $0 + $1.completedLeaves }, total = children.reduce(0) { $0 + $1.leafCount }
            let fraction: Double? = completed ? 1 : done == 0 && taskState.animated ? nil : Double(done) / Double(max(1, total))
            return .init(id: "task:\(taskID)", taskID: taskID, title: String(task.objective.prefix(180)), state: taskState,
                fraction: fraction, detail: "\(done)／\(total) 步驟", engine: "", children: children)
        }
        let next = tasks.filter { $0.parentID == nil || !ids.contains($0.parentID!) }.sorted {
            let order: [WorkProgressState: Int] = [.running: 0, .reviewing: 0, .needsInput: 1, .uncertain: 1, .failed: 1, .paused: 2, .pending: 3, .completed: 4, .cancelled: 4]
            let a = order[state($0), default: 0], b = order[state($1), default: 0]
            return a == b ? $0.createdAt > $1.createdAt : a < b
        }.map { build($0, depth: 0) }
        var newStates: [String: WorkProgressState] = [:]
        var newSteps: [String: WorkProgressState] = [:]
        func observe(_ node: WorkProgressNode) {
            if node.id.hasPrefix("task:") {
                newStates[node.id] = node.state
                if knownStates[node.id] != node.state {
                    if logChanges { append(engine: "麥芽糖", text: "\(node.title) · \(node.state.title)", taskID: node.taskID, failed: node.state == .failed) }
                    if node.state == .completed || node.state == .pending { collapsed.insert(node.id) }
                    else if knownStates[node.id] == .pending { collapsed.remove(node.id) }
                }
            } else if node.id.hasPrefix("step:") {
                newSteps[node.id] = node.state
                if logChanges, knownSteps[node.id] != node.state, node.state != .pending {
                    append(engine: node.engine, text: "\(node.title) · \(node.state.title)", taskID: node.taskID, failed: node.state == .failed)
                }
            }
            node.children.forEach(observe)
        }
        next.forEach(observe)
        let needsProgress = newStates.contains { id, state in
            state != .completed && state != .cancelled && knownStates[id] != state
        }
        knownStates = newStates; knownSteps = newSteps
        if roots != next { roots = next }
        if needsProgress { onProgressNeeded?() }
    }

    func receiveCodex(task: CodexTaskRecord, method: String, value: UserViewValue) {
        if method == "turn/plan/updated" {
            guard let turn = value["turnId"]?.stringValue, turn == task.activeTurnID,
                  let plan = value["plan"]?.arrayValue, plan.count <= 64 else { return }
            let steps: [(String, WorkProgressState)] = plan.compactMap { item in
                guard let title = item["step"]?.stringValue, let status = item["status"]?.stringValue,
                      ["pending", "inProgress", "completed"].contains(status) else { return nil }
                return (String(title.prefix(180)), status == "completed" ? .completed : status == "inProgress" ? .running : .pending)
            }
            guard steps.count == plan.count else { return }
            codexPlans[task.id] = (turn, steps)
        }
        let text: String?
        switch method {
        case "turn/started": text = "開始處理開發任務"
        case "turn/completed": text = "本回合已返回，交由麥芽糖核對成果"
        case "turn/plan/updated": text = "已更新執行步驟"
        case "item/started":
            switch value["item"]?["type"]?.stringValue {
            case "commandExecution": text = "執行專案指令與檢查"
            case "fileChange": text = "修改專案檔案"
            case "webSearch": text = "搜尋開發資料"
            case "mcpToolCall", "dynamicToolCall": text = "執行工具操作"
            default: text = nil
            }
        default: text = nil
        }
        if let text { append(engine: "Codex", text: text, taskID: task.productTaskID) }
    }

    func receive(_ envelope: ConversationHistoryModel.RuntimeEnvelope) {
        guard !envelope.sessionID.hasPrefix("coordination:") else { return }
        if eventSessionID != envelope.sessionID { eventSessionID = envelope.sessionID; runtimeActivities.removeAll() }
        let event = envelope.event
        switch event.type {
        case "model_started":
            if runtimeActivities.insert("model").inserted { append(engine: "麥芽糖", text: "分析需求與整理下一步") }
        case "model_finished", "model_failed": runtimeActivities.remove("model")
        case "tool_started", "tool_finished", "tool_failed":
            let name = event.payload["tool"]?.stringValue ?? ""
            let titles = ["web_search":"搜尋資料", "read_web_page":"讀取網頁資料", "read_file":"讀取文件", "execute_command":"執行指令與檢查",
                "maltose_get_user_view":"查看工作區", "maltose_list_capabilities":"查看面板清單", "maltose_read_panel":"讀取面板內容",
                "maltose_chart_load_csv":"更新圖表資料", "maltose_create_panel":"建立面板", "set_task_plan":"規劃任務步驟", "update_task_progress":"更新任務進度"]
            let action = titles[name] ?? (name.hasPrefix("maltose_") ? "操作面板" : "執行工具")
            let suffix = event.type == "tool_finished" ? "已返回" : event.type == "tool_failed" ? "失敗" : "開始"
            append(engine: "麥芽糖", text: "\(action) · \(suffix)", failed: event.type == "tool_failed")
        case "runtime_worker_failed": append(engine: "麥芽糖", text: "背景服務已停止，需要重新啟動", failed: true)
        default: break
        }
    }

    func toggle(_ id: String) { if collapsed.contains(id) { collapsed.remove(id) } else { collapsed.insert(id) } }
    func selectTask(_ id: UUID) {
        func reveal(_ node: WorkProgressNode, path: [String]) -> Bool {
            let next = path + [node.id]
            if node.id == "task:\(id)" { for item in next { collapsed.remove(item) }; return true }
            return node.children.contains { reveal($0, path: next) }
        }
        _ = roots.contains { reveal($0, path: []) }
        selectedTaskID = id; selectionRevision += 1; onSelectTask?(id)
    }
    struct Row: Identifiable { let node: WorkProgressNode; let depth: Int; var id: String { node.id } }
    var rows: [Row] {
        var result: [Row] = []
        func visit(_ node: WorkProgressNode, _ depth: Int) {
            result.append(.init(node: node, depth: depth))
            if !collapsed.contains(node.id) { node.children.forEach { visit($0, depth + 1) } }
        }
        roots.forEach { visit($0, 0) }; return result
    }
    func summary(kind: WorkspacePanel.Kind) -> [String: UserViewValue] {
        if kind == .agentActivity { return ["entryCount": .number(Double(entries.count)), "scope": .string("current_app_session")] }
        return ["taskCount": .number(Double(roots.count)), "activeCount": .number(Double(roots.filter { $0.state != .completed && $0.state != .cancelled }.count))]
    }
    func details(kind: WorkspacePanel.Kind) -> [String: UserViewValue] {
        var value = summary(kind: kind)
        if kind == .agentActivity { value["recentEntries"] = .strings(entries.suffix(40).map { "\($0.engine)：\($0.text)" }) }
        else {
            value["visibleTasks"] = .array(rows.prefix(100).map { row in .object([
                "id": .string(row.id), "taskID": .string(row.node.taskID.uuidString), "title": .string(row.node.title), "depth": .number(Double(row.depth)),
                "state": .string(row.node.state.rawValue), "progress": row.node.fraction.map(UserViewValue.number) ?? .null]) })
            value["truncated"] = .boolean(rows.count > 100)
        }
        return value
    }
}

extension AgentSessionCoordinator {
    func installWorkMonitoring(_ model: AgentWorkMonitor) {
        workMonitor = model
        store.onCommit = { [weak self] in self?.refreshWorkMonitoring() }
        refreshWorkMonitoring()
    }
    func refreshWorkMonitoring() {
        workMonitor?.update(tasks: store.productTasks.filter { $0.conversationID == conversation.id },
                            codexTasks: taskChoices)
    }
}
