import Foundation
import Darwin

enum CodexTaskStatus: String, Codable {
    case prepared, running, waitingForUser, awaitingReview, completed, failed, interrupted, needsReconciliation
}
enum AgentControlState: String, Codable {
    case maltoseActive, handingOff, codexDirect, reportingToMaltose, awaitingUserIntent
}
enum CodexMessageAuthor: String, Codable { case user, maltose, codex, tool, integration }
enum CodexMessageOrigin: String, Codable { case native, voice, delegation, codex, synchronization }

struct CodexTaskMessage: Codable, Equatable, Identifiable {
    enum Delivery: String, Codable { case prepared, accepted, rejected, uncertain }
    let id: String
    let author: CodexMessageAuthor
    let origin: CodexMessageOrigin
    let content: String
    let threadID: String?
    var turnID: String?
    var delivery: Delivery? = nil
}

struct CodexDelegation: Codable, Equatable {
    var objective: String
    var constraints: [String]
    var acceptanceCriteria: [String]
    var context: String? = nil
}

struct CodexTaskRecord: Codable, Equatable, Identifiable {
    let id: UUID
    let conversationID: String
    let repositoryPath: String
    let worktreePath: String
    let delegation: CodexDelegation
    let createdAt: Date
    var updatedAt: Date
    var threadID: String?
    var activeTurnID: String?
    var lastFinishedTurnID: String?
    var status: CodexTaskStatus = .prepared
    var control: AgentControlState = .maltoseActive
    var messages: [CodexTaskMessage] = []
    var outcomeSummary: String?
    var failureMessage: String?
    var ownerSpeakerID: String?
    var workspaceChanges: UserViewValue?
    var model: String?
    var panelToolsRegistered: Bool?
    /// Durable intent precedes RPC. An uncertain mutation is reconciled, never replayed blindly.
    var pendingOperation: Operation?

    struct Operation: Codable, Equatable {
        enum Kind: String, Codable { case startThread, startTurn, steerTurn, interruptTurn }
        enum Phase: String, Codable { case prepared, acknowledged, uncertain }
        let id: UUID
        let kind: Kind
        let clientMessageID: String?
        var phase: Phase
    }

    init(id: UUID = UUID(), conversationID: String, repositoryPath: String, worktreePath: String, delegation: CodexDelegation) {
        self.id = id; self.conversationID = conversationID
        self.repositoryPath = repositoryPath; self.worktreePath = worktreePath; self.delegation = delegation
        createdAt = Date(); updatedAt = createdAt
    }
}

enum CodexTaskStoreError: Error, LocalizedError {
    case invalid(String), conflict, unavailable(String)
    var errorDescription: String? {
        switch self {
        case let .invalid(message), let .unavailable(message): message
        case .conflict: "Codex 任務紀錄已變更，請重新讀取。"
        }
    }
}

/// Product task mapping only; Codex remains the authority for its conversation/runtime.
/// One owner, versioned snapshots, atomic replacement, explicit corruption errors.
@MainActor final class CodexTaskStore {
    private struct Document: Codable {
        var schemaVersion = 2
        var revision: Int = 0
        var tasks: [CodexTaskRecord] = []
        var conversations: [AgentConversationState]?
        var activeConversationID: String?
        var preferredModel: String?
    }
    private let url: URL
    private var lease: Int32 = -1
    private var document = Document()
    private var isOpen = false
    var revision: Int { document.revision }
    var tasks: [CodexTaskRecord] { document.tasks }
    var conversations: [AgentConversationState] { document.conversations ?? [] }
    var activeConversation: AgentConversationState? { conversations.first { $0.id == document.activeConversationID } }
    var preferredModel: String? { document.preferredModel }
    func setPreferredModel(_ model: String) throws {
        guard !model.isEmpty, model.count <= 200 else { throw CodexTaskStoreError.invalid("Codex 模型識別碼不正確。") }
        var next = document; next.preferredModel = model; try commit(next)
    }

    init(url: URL) { self.url = url }
    deinit { if lease >= 0 { _ = Darwin.close(lease) } }

    func open() throws {
        guard !isOpen else { return }
        let directory = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        guard (try directory.resourceValues(forKeys: [.isSymbolicLinkKey])).isSymbolicLink != true else {
            throw CodexTaskStoreError.unavailable("Codex 任務目錄不能是符號連結。")
        }
        let fd = Darwin.open(url.appendingPathExtension("lock").path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw CodexTaskStoreError.unavailable("無法取得 Codex 任務紀錄鎖。") }
        do {
            try validatePrivateFile(fd)
            guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
                throw CodexTaskStoreError.unavailable("另一個 Maltose 正在使用 Codex 任務紀錄。")
            }
            var loaded = Document()
            let dataFD = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            if dataFD >= 0 {
                let file = FileHandle(fileDescriptor: dataFD, closeOnDealloc: true)
                defer { try? file.close() }
                try validatePrivateFile(dataFD)
                var info = stat(); guard fstat(dataFD, &info) == 0, info.st_size <= 64 * 1024 * 1024 else {
                    throw CodexTaskStoreError.invalid("Codex 任務紀錄超過大小限制。")
                }
                var restored = try JSONDecoder().decode(Document.self, from: file.readToEnd() ?? Data())
                if restored.schemaVersion == 1 { restored.schemaVersion = 2 }
                try validate(restored); loaded = restored
            } else if errno != ENOENT { throw CodexTaskStoreError.unavailable("無法安全開啟 Codex 任務紀錄。") }
            document = loaded; lease = fd; isOpen = true
        } catch { _ = Darwin.close(fd); throw error }
    }

    func close() { if lease >= 0 { _ = Darwin.close(lease) }; lease = -1; isOpen = false }
    func task(_ id: UUID) -> CodexTaskRecord? { document.tasks.first { $0.id == id } }

    @discardableResult func ensureConversation(_ id: String? = nil) throws -> AgentConversationState {
        if let id, let existing = conversations.first(where: { $0.id == id }) { return existing }
        if id == nil, let activeConversation { return activeConversation }
        let conversation = AgentConversationState(id: id ?? UUID().uuidString)
        var next = document
        next.conversations = conversations + [conversation]; next.activeConversationID = conversation.id
        try commit(next); return conversation
    }

    func selectConversation(_ id: String) throws {
        guard conversations.contains(where: { $0.id == id }) else { throw CodexTaskStoreError.invalid("找不到協作對話。") }
        var next = document; next.activeConversationID = id; try commit(next)
    }

    func updateConversation(_ id: String, _ change: (inout AgentConversationState) throws -> Void) throws {
        guard let index = conversations.firstIndex(where: { $0.id == id }) else { throw CodexTaskStoreError.invalid("找不到協作對話。") }
        var next = document; var records = conversations
        try change(&records[index])
        guard records[index].id == id else { throw CodexTaskStoreError.invalid("對話識別碼不可替換。") }
        next.conversations = records; try commit(next)
    }

    @discardableResult func enqueue(_ input: AgentInputRecord, conversationID: String) throws -> Bool {
        guard let conversation = conversations.first(where: { $0.id == conversationID }) else { throw CodexTaskStoreError.invalid("找不到協作對話。") }
        if let previous = conversation.inputs.first(where: { $0.id == input.id }) {
            guard previous.text == input.text, previous.author == input.author, previous.origin == input.origin,
                  previous.speakerID == input.speakerID, previous.speakerStatus == input.speakerStatus,
                  previous.runtimeSessionID == input.runtimeSessionID else {
                throw CodexTaskStoreError.invalid("協作訊息來源或內容衝突。")
            }
            return false
        }
        try updateConversation(conversationID) { $0.inputs.append(input) }; return true
    }

    func create(_ task: CodexTaskRecord) throws {
        guard !document.tasks.contains(where: { $0.id == task.id }) else { throw CodexTaskStoreError.conflict }
        var next = document; next.tasks.append(task); try commit(next)
    }

    func update(_ id: UUID, expectedRevision: Int? = nil, _ change: (inout CodexTaskRecord) throws -> Void) throws {
        if let expectedRevision, expectedRevision != document.revision { throw CodexTaskStoreError.conflict }
        guard let index = document.tasks.firstIndex(where: { $0.id == id }) else {
            throw CodexTaskStoreError.invalid("找不到 Codex 任務。")
        }
        var next = document
        let old = next.tasks[index]
        try change(&next.tasks[index])
        guard next.tasks[index].id == old.id, next.tasks[index].conversationID == old.conversationID,
              next.tasks[index].repositoryPath == old.repositoryPath, next.tasks[index].worktreePath == old.worktreePath,
              next.tasks[index].delegation == old.delegation,
              old.model == nil || next.tasks[index].model == old.model,
              next.tasks[index].panelToolsRegistered == old.panelToolsRegistered,
              old.threadID == nil || next.tasks[index].threadID == old.threadID else {
            throw CodexTaskStoreError.invalid("既有 Codex 任務的對話與工作位置不可替換。")
        }
        next.tasks[index].updatedAt = Date()
        try commit(next)
    }

    /// Stable source IDs deduplicate delivery without erasing provenance.
    @discardableResult func append(_ message: CodexTaskMessage, to id: UUID) throws -> Bool {
        guard let task = task(id) else { throw CodexTaskStoreError.invalid("找不到 Codex 任務。") }
        if let existing = task.messages.first(where: { $0.id == message.id }) {
            guard existing.author == message.author, existing.origin == message.origin, existing.content == message.content,
                  existing.threadID == message.threadID, message.turnID == nil || existing.turnID == message.turnID else {
                throw CodexTaskStoreError.invalid("重複訊息的內容或來源不一致。")
            }
            return false
        }
        try update(id) { $0.messages.append(message) }
        return true
    }

    private func commit(_ candidate: Document) throws {
        guard isOpen else { throw CodexTaskStoreError.unavailable("Codex 任務紀錄尚未開啟。") }
        var next = candidate; next.revision += 1
        try validate(next)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(next)
        guard data.count <= 64 * 1024 * 1024 else { throw CodexTaskStoreError.invalid("Codex 任務紀錄超過大小限制。") }
        let temporary = url.deletingLastPathComponent().appendingPathComponent(".codex-tasks-\(UUID().uuidString).tmp")
        let directoryFD = Darwin.open(url.deletingLastPathComponent().path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard directoryFD >= 0 else { throw CodexTaskStoreError.unavailable("Codex 任務目錄不可用。") }
        defer { _ = Darwin.close(directoryFD) }
        let fd = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw CodexTaskStoreError.unavailable("無法儲存 Codex 任務紀錄。") }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close(); try? FileManager.default.removeItem(at: temporary) }
        try handle.write(contentsOf: data); try handle.synchronize(); try handle.close()
        guard Darwin.rename(temporary.path, url.path) == 0 else {
            throw CodexTaskStoreError.unavailable("無法完成 Codex 任務紀錄寫入。")
        }
        document = next
        guard fsync(directoryFD) == 0 else {
            throw CodexTaskStoreError.unavailable("任務紀錄已寫入，但無法確認目錄同步；請核對狀態。")
        }
    }

    private func validatePrivateFile(_ fd: Int32) throws {
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_mode & 0o077 == 0, info.st_nlink == 1 else {
            throw CodexTaskStoreError.unavailable("Codex 任務紀錄必須是目前使用者專用的普通檔案。")
        }
    }
    private func validate(_ candidate: Document) throws {
        if let model = candidate.preferredModel, model.isEmpty || model.count > 200 { throw CodexTaskStoreError.invalid("Codex 模型設定不正確。") }
        guard candidate.schemaVersion == 2, candidate.revision >= 0,
              Set(candidate.tasks.map(\.id)).count == candidate.tasks.count else {
            throw CodexTaskStoreError.invalid("Codex 任務紀錄版本或識別碼不正確。")
        }
        let conversations = candidate.conversations ?? []
        guard Set(conversations.map(\.id)).count == conversations.count,
              candidate.activeConversationID == nil || conversations.contains(where: { $0.id == candidate.activeConversationID }) else {
            throw CodexTaskStoreError.invalid("協作對話識別碼不正確。")
        }
        for conversation in conversations {
            guard !conversation.id.isEmpty, conversation.sequence >= 0,
                  Set(conversation.inputs.map(\.id)).count == conversation.inputs.count,
                  conversation.inputs.allSatisfy({ !$0.id.isEmpty }) else { throw CodexTaskStoreError.invalid("協作輸入紀錄不正確。") }
            if let taskID = conversation.activeTaskID {
                guard candidate.tasks.contains(where: { $0.id == taskID && $0.conversationID == conversation.id }) else {
                    throw CodexTaskStoreError.invalid("協作任務不屬於目前對話。")
                }
            }
        }
        var threads = Set<String>()
        for task in candidate.tasks {
            if let model = task.model, model.isEmpty || model.count > 200 { throw CodexTaskStoreError.invalid("Codex 任務模型不正確。") }
            guard !task.conversationID.isEmpty, !task.delegation.objective.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  task.repositoryPath.hasPrefix("/"), task.worktreePath.hasPrefix("/"),
                  Set(task.messages.map(\.id)).count == task.messages.count,
                  task.messages.allSatisfy({ !$0.id.isEmpty && ($0.threadID == nil || $0.threadID == task.threadID) }) else {
                throw CodexTaskStoreError.invalid("Codex 任務缺少必要的來源、對話或絕對路徑。")
            }
            if let thread = task.threadID {
                guard !thread.isEmpty, threads.insert(thread).inserted else {
                    throw CodexTaskStoreError.invalid("Codex thread 不可對應到多個產品任務。")
                }
            }
            if task.activeTurnID != nil && task.threadID == nil {
                throw CodexTaskStoreError.invalid("Codex 回合必須屬於已知 thread。")
            }
            if task.status == .completed && (task.outcomeSummary?.isEmpty != false || task.activeTurnID != nil) {
                throw CodexTaskStoreError.invalid("Codex 任務完成需要成果，且不能仍有執行中的回合。")
            }
        }
    }
}
