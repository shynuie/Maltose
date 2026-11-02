import AppKit
import Foundation
import Combine
import Darwin

enum MaltoseProduct {
    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.7.0"
}

struct RuntimeLaunchConfiguration {
    var executable: URL
    var arguments: [String]
    var directory: URL
    var moduleDirectory: URL
    var logURL: URL
    var startupTimeout: Duration = .seconds(120)
    var shutdownGrace: Duration = .seconds(3)

    static func supportDirectory(environment: [String: String] = ProcessInfo.processInfo.environment) throws -> URL {
        if let path = environment["MALTOSE_DATA_DIR"] ?? environment["MYAGENT_DATA_DIR"] {
            let expanded = (path as NSString).expandingTildeInPath
            guard expanded.hasPrefix("/") else { throw RuntimeLaunchError.unavailable("Maltose 資料位置必須是絕對路徑。") }
            return URL(fileURLWithPath: expanded, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Maltose")
    }

    static func application() throws -> Self {
        let support = try supportDirectory()
        let environment = ProcessInfo.processInfo.environment
        let config: URL
        if let path = environment["MALTOSE_CONFIG"] ?? environment["MYAGENT_CONFIG"] {
            let expanded = (path as NSString).expandingTildeInPath
            guard expanded.hasPrefix("/") else { throw RuntimeLaunchError.unavailable("Maltose 設定位置必須是絕對路徑。") }
            config = URL(fileURLWithPath: expanded)
        } else { config = support.appendingPathComponent("maltose.toml") }
        guard FileManager.default.fileExists(atPath: config.path) else {
            throw RuntimeLaunchError.unavailable("尚未遷移主 Agent 設定，請完成 Maltose 執行環境設定。")
        }
        guard let resources = Bundle.main.resourceURL else {
            throw RuntimeLaunchError.unavailable("找不到 App 的主 Agent 資源。")
        }
        return .init(executable: support.appendingPathComponent("environments/main/bin/python"),
                     arguments: ["-m", "maltose.desktop", "--config", config.path],
                     directory: support, moduleDirectory: resources.appendingPathComponent("Runtime"),
                     logURL: support.appendingPathComponent("logs/runtime.log"))
    }
}

enum RuntimeLaunchError: LocalizedError {
    case unavailable(String)
    var errorDescription: String? { switch self { case let .unavailable(message): message } }
}

/// Owns one child and its private stdio connection. UI state stays on MainActor.
@MainActor final class RuntimeSupervisor: ObservableObject {
    enum State: Equatable {
        case stopped, starting, ready, stopping, failed(String)
        var title: String {
            switch self {
            case .stopped: "主 Agent 已停止"
            case .starting: "主 Agent 啟動中"
            case .ready: "主 Agent 已就緒"
            case .stopping: "主 Agent 正在結束"
            case let .failed(message): "主 Agent：\(message)"
            }
        }
    }

    @Published private(set) var state: State = .stopped { didSet { onStateChange?(state) } }
    @Published private(set) var autonomy: RuntimeAutonomySnapshot?
    var initialAutonomyOwner: String?
    var inputRoutingEnabled = false
    var conversationID: String?
    var onAutonomyChange: ((RuntimeAutonomySnapshot) -> Void)?
    private(set) var sessionID: String?
    private(set) var processID: Int32?
    var onStateChange: ((State) -> Void)?
    var onEvent: ((Data) -> Void)?
    var workflowEnabled = false
    var continuationsEnabled = true
    var visualPlanningEnabled = true
    var panelPolicyEnabled = true
    private(set) var panelPolicyVersion = 0
    private(set) var panelOperationVersion = 0
    private(set) var publicWebSourceVersion = 0
    private(set) var workerResultVersion = 0
    private(set) var visualPlanningVersion = 0
    var taskResumptionsEnabled = true
    private(set) var taskResumptionVersion = 0
    var foregroundContinuationsEnabled = true
    private(set) var foregroundContinuationVersion = 0
    private(set) var inputScopeVersion = 0
    // Negotiated only with the native workflow; legacy hosts keep their adapter.
    var foregroundResultsEnabled = true
    private(set) var foregroundResultVersion = 0
    var onWorkflowRequest: ((ProductWorkflowRequest) throws -> [String: UserViewValue])?
    var onPanelCommand: ((WorkspaceAgentRequest, NativePanelFileTransfer?) async -> WorkspaceAgentResponse)?
    var toolDefinitions = WorkspaceAgentToolDefinitions.all
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var log: FileHandle?
    private var buffer = Data()
    private var lastSequence = 0
    private var ownedProcessGroup: Int32?
    private var generation = UUID()
    private var timeoutTask: Task<Void, Never>?
    private var shutdownTask: Task<Void, Never>?
    private var stopCompletions: [() -> Void] = []
    private var pending: [String: (Bool, String?) -> Void] = [:]
    private struct PendingResult {
        var method: String
        var continuation: CheckedContinuation<[String: UserViewValue], Error>
        var timer: Task<Void, Never>
    }
    private var pendingResults: [String: PendingResult] = [:]
    private var panelReplies: [String: (fingerprint: Data, envelope: [String: Any])] = [:]
    private var panelInFlight: [String: Data] = [:]
    private var panelReplyOrder: [String] = []
    private let writes = DispatchQueue(label: "maltose.runtime.input")
    private var failureMessage: String?
    private(set) var configuration: RuntimeLaunchConfiguration?

    func startApplication() {
        do { try start(configuration: .application()) }
        catch { state = .failed(error.localizedDescription) }
    }

    func start(configuration: RuntimeLaunchConfiguration) throws {
        guard process == nil else { return }
        guard FileManager.default.isExecutableFile(atPath: configuration.executable.path) else {
            throw RuntimeLaunchError.unavailable("找不到已設定的主 Agent Python。")
        }
        let tools = try JSONSerialization.jsonObject(with: JSONEncoder().encode(toolDefinitions))
        try FileManager.default.createDirectory(at: configuration.logURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        if !FileManager.default.fileExists(atPath: configuration.logURL.path) {
            FileManager.default.createFile(atPath: configuration.logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let diagnostic = try FileHandle(forWritingTo: configuration.logURL)
        try diagnostic.seekToEnd()
        let child = Process()
        let stdinPipe = Pipe(), stdoutPipe = Pipe()
        child.executableURL = configuration.executable
        child.arguments = configuration.arguments
        child.currentDirectoryURL = configuration.directory
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = configuration.moduleDirectory.path
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        child.environment = environment
        child.standardInput = stdinPipe; child.standardOutput = stdoutPipe; child.standardError = diagnostic
        let token = UUID()
        generation = token; failureMessage = nil; lastSequence = 0; sessionID = nil; ownedProcessGroup = nil
        autonomy = nil
        panelReplies.removeAll(); panelInFlight.removeAll(); panelReplyOrder.removeAll()
        buffer.removeAll(); self.configuration = configuration
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            Task { @MainActor [weak self] in
                guard let self, self.generation == token else { return }
                self.receive(data)
            }
        }
        child.terminationHandler = { [weak self] child in
            let code = child.terminationStatus
            Task { @MainActor [weak self] in
                guard let self, self.generation == token else { return }
                self.didExit(code: code)
            }
        }
        _ = Darwin.fcntl(stdinPipe.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        input = stdinPipe.fileHandleForWriting; output = stdoutPipe.fileHandleForReading; log = diagnostic
        process = child; state = .starting
        do { try child.run() }
        catch {
            child.terminationHandler = nil
            failureMessage = error.localizedDescription
            didExit(code: -1)
            throw error
        }
        processID = child.processIdentifier
        var initialize: [String: Any] = ["clientInfo": ["name": "maltose", "version": MaltoseProduct.version], "tools": tools,
                                         "inputRouting": inputRoutingEnabled, "presentationVersion": 1, "resultDeliveryVersion": 1]
        initialize["resultChartVersion"] = 1
        initialize["panelPolicyVersion"] = panelPolicyEnabled ? 1 : 0
        initialize["panelOperationVersion"] = panelPolicyEnabled ? 1 : 0
        initialize["publicWebSourceVersion"] = workflowEnabled && foregroundResultsEnabled ? 1 : 0
        initialize["visualPlanningVersion"] = workflowEnabled && foregroundResultsEnabled && visualPlanningEnabled ? 1 : 0
        initialize["workflowVersion"] = workflowEnabled ? 1 : 0
        initialize["taskProgressVersion"] = workflowEnabled ? 1 : 0
        initialize["inputScopeVersion"] = workflowEnabled ? 1 : 0
        initialize["foregroundResultVersion"] = workflowEnabled && foregroundResultsEnabled ? 1 : 0
        initialize["foregroundContinuationVersion"] = workflowEnabled && foregroundResultsEnabled && continuationsEnabled && foregroundContinuationsEnabled ? 1 : 0
        initialize["taskResumptionVersion"] = workflowEnabled && foregroundResultsEnabled && continuationsEnabled && foregroundContinuationsEnabled && taskResumptionsEnabled ? 1 : 0
        initialize["workerResultVersion"] = initialize["taskResumptionVersion"]
        initialize["workerEvidenceVersion"] = workflowEnabled ? 1 : 0
        initialize["continuationVersion"] = workflowEnabled && continuationsEnabled ? 1 : 0
        if let initialAutonomyOwner { initialize["initialAutonomyOwner"] = initialAutonomyOwner }
        if let conversationID { initialize["conversationID"] = conversationID }
        request("initialize", params: initialize)
        timeoutTask = Task { @MainActor [weak self] in
            do { try await Task.sleep(for: configuration.startupTimeout) } catch { return }
            guard let self, self.generation == token, self.state == .starting else { return }
            self.fail("啟動逾時，請查看主 Agent 日誌。")
        }
    }

    @discardableResult func submitText(_ text: String, completion: ((Bool, String?) -> Void)? = nil) -> Bool {
        guard state == .ready, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        request("submit_text", params: ["text": text], completion: completion)
        return true
    }

    /// Only the product coordinator calls these methods; no model-facing resume tool.
    func call(_ method: String, params: [String: UserViewValue] = [:], timeout: Duration = .seconds(30)) async throws -> [String: UserViewValue] {
        guard state == .ready else { throw RuntimeRequestError.unavailable }
        let data = try JSONEncoder().encode(params)
        let body = try JSONSerialization.jsonObject(with: data)
        let id = UUID().uuidString, token = generation
        let result: [String: UserViewValue] = try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                let timer = Task { @MainActor [weak self] in
                    do { try await Task.sleep(for: timeout) } catch { return }
                    guard let self, self.generation == token else { return }
                    self.resolveResult(id, .failure(RuntimeRequestError.outcomeUnknown(method)))
                }
                pendingResults[id] = .init(method: method, continuation: continuation, timer: timer)
                sendEnvelope(["schemaVersion": 1, "requestID": id, "method": method, "params": body])
            }
        } onCancel: {
            Task { @MainActor [weak self] in
                guard let self, self.generation == token else { return }
                self.resolveResult(id, .failure(RuntimeRequestError.outcomeUnknown(method)))
            }
        }
        guard generation == token, state == .ready else { throw RuntimeRequestError.outcomeUnknown(method) }
        return result
    }

    func readAutonomy() async throws -> RuntimeAutonomySnapshot {
        let token = generation
        let result = try await call("snapshot")
        guard generation == token, state == .ready else { throw RuntimeRequestError.outcomeUnknown("snapshot") }
        guard let value = result["autonomy"] else { throw RuntimeRequestError.rejected("主 Agent 不支援執行權控制。") }
        let snapshot = try JSONDecoder().decode(RuntimeAutonomySnapshot.self, from: JSONEncoder().encode(value))
        try acceptAutonomy(snapshot)
        return snapshot
    }

    private func acceptAutonomy(_ snapshot: RuntimeAutonomySnapshot) throws {
        try snapshot.validate()
        guard snapshot.version >= (autonomy?.version ?? -1) else { return }
        if let previous = autonomy, previous.version == snapshot.version,
           (previous.state != snapshot.state || previous.epoch != snapshot.epoch || previous.ownerID != snapshot.ownerID || previous.leaseID != snapshot.leaseID) {
            throw RuntimeRequestError.rejected("主 Agent 執行權版本衝突。")
        }
        autonomy = snapshot; onAutonomyChange?(snapshot)
    }

    private func resolveResult(_ id: String, _ result: Result<[String: UserViewValue], Error>) {
        guard let pending = pendingResults.removeValue(forKey: id) else { return }
        pending.timer.cancel(); pending.continuation.resume(with: result)
    }

    /// Called only from a human confirmation control, never an exposed Agent tool.
    @discardableResult func submitUIAction(_ actionID: String, value: [String: String], completion: @escaping (Bool, String?) -> Void) -> Bool {
        guard state == .ready else { return false }
        request("ui_action", params: ["actionID": actionID, "value": value], completion: completion)
        return true
    }

    private func request(_ method: String, params: [String: Any] = [:], completion: ((Bool, String?) -> Void)? = nil) {
        guard input != nil else { completion?(false, "主 Agent 未連線。"); return }
        let id = UUID().uuidString
        if let completion { pending[id] = completion }
        sendEnvelope(["schemaVersion": 1, "requestID": id, "method": method, "params": params])
    }

    private func sendEnvelope(_ message: [String: Any]) {
        guard let input else { return }
        do {
            var data = try JSONSerialization.data(withJSONObject: message)
            data.append(10)
            let token = generation
            let encoded = data
            writes.async { [weak self] in
                do { try input.write(contentsOf: encoded) }
                catch {
                    Task { @MainActor [weak self] in
                        guard let self, self.generation == token else { return }
                        self.fail("與主 Agent 的連線已中斷。")
                    }
                }
            }
        } catch { fail("無法編碼主 Agent 指令。") }
    }

    private func receive(_ data: Data) {
        buffer.append(data)
        guard buffer.count <= 8 * 1024 * 1024 else { fail("主 Agent 回應超出大小限制。"); return }
        while let end = buffer.firstIndex(of: 10) {
            let line = buffer.subdata(in: buffer.startIndex..<end)
            buffer.removeSubrange(buffer.startIndex...end)
            if line.isEmpty { continue }
            guard let message = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any],
                  message["schemaVersion"] as? Int == 1 else { fail("主 Agent 合約版本或回應格式不正確。"); return }
            if let requestID = message["requestID"] as? String {
                let ok = message["ok"] as? Bool == true
                if let result = message["result"] as? [String: Any], result["product"] as? String == "Maltose" {
                    guard ok, let id = result["sessionID"] as? String, !id.isEmpty,
                          let pid = result["pid"] as? Int32, pid == processID else { fail("主 Agent 握手身分不相符。"); return }
                    sessionID = id
                    inputScopeVersion = (result["inputScopeVersion"] as? Int) == 1 ? 1 : 0
                    foregroundResultVersion = (result["foregroundResultVersion"] as? Int) == 1 ? 1 : 0
                    visualPlanningVersion = (result["visualPlanningVersion"] as? Int) == 1 ? 1 : 0
                    panelPolicyVersion = (result["panelPolicyVersion"] as? Int) == 1 ? 1 : 0
                    panelOperationVersion = panelPolicyVersion == 1 && (result["panelOperationVersion"] as? Int) == 1 ? 1 : 0
                    publicWebSourceVersion = (result["publicWebSourceVersion"] as? Int) == 1 ? 1 : 0
                    taskResumptionVersion = (result["taskResumptionVersion"] as? Int) == 1 ? 1 : 0
                    workerResultVersion = (result["workerResultVersion"] as? Int) == 1 ? 1 : 0
                    foregroundContinuationVersion = (result["foregroundContinuationVersion"] as? Int) == 1 ? 1 : 0
                    if let group = result["processGroupID"] as? Int32, group == pid { ownedProcessGroup = group }
                }
                if let sessionID, message["sessionID"] as? String != sessionID { fail("主 Agent 回應不屬於目前連線。"); return }
                if pendingResults[requestID] != nil {
                    if !ok { resolveResult(requestID, .failure(RuntimeRequestError.rejected((message["error"] as? [String: Any])?["message"] as? String ?? "主 Agent 拒絕操作。"))) }
                    else if let result = message["result"] as? [String: Any],
                            let data = try? JSONSerialization.data(withJSONObject: result),
                            let value = try? JSONDecoder().decode([String: UserViewValue].self, from: data) {
                        resolveResult(requestID, .success(value))
                    } else { fail("主 Agent 指令結果不正確。"); return }
                }
                pending.removeValue(forKey: requestID)?(ok, (message["error"] as? [String: Any])?["message"] as? String)
                if !ok, state == .starting { fail("主 Agent 拒絕初始化。"); return }
                continue
            }
            guard let sessionID, message["sessionID"] as? String == sessionID else { fail("主 Agent 事件不屬於目前連線。"); return }
            if let requestID = message["serverRequestID"] as? String {
                guard !requestID.isEmpty, requestID.count <= 128, message["method"] as? String == "panel.call",
                      let params = message["params"] as? [String: Any], let body = params["request"],
                      let fingerprint = try? JSONSerialization.data(withJSONObject: params, options: [.sortedKeys]),
                      let encoded = try? JSONSerialization.data(withJSONObject: body),
                      let request = try? JSONDecoder().decode(WorkspaceAgentRequest.self, from: encoded),
                      request.requestID == requestID else { fail("主 Agent 面板指令格式不正確。"); return }
                let fileTransfer: NativePanelFileTransfer?
                if let payload = params["fileTransfer"], !(payload is NSNull) {
                    guard let data = try? JSONSerialization.data(withJSONObject: payload),
                          let decoded = try? JSONDecoder().decode(NativePanelFileTransfer.self, from: data) else {
                        fail("主 Agent 檔案傳輸格式不正確。"); return
                    }
                    fileTransfer = decoded
                } else { fileTransfer = nil }
                if let previous = panelReplies[requestID] {
                    guard previous.fingerprint == fingerprint else { fail("面板指令識別碼被重複用於不同操作。"); return }
                    sendEnvelope(previous.envelope); continue
                }
                if let previous = panelInFlight[requestID] {
                    guard previous == fingerprint else { fail("執行中的面板指令識別碼被重複使用。"); return }
                    continue
                }
                panelInFlight[requestID] = fingerprint
                let token = generation
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    let response: WorkspaceAgentResponse
                    if case let .workflow(operation) = request.command {
                        do {
                            guard fileTransfer == nil, let handler = self.onWorkflowRequest else { throw CodexTaskStoreError.unavailable("共同任務服務尚未連接。") }
                            response = .init(requestID: requestID, ok: true, result: try handler(operation))
                        } catch { response = .init(requestID: requestID, ok: false, error: .init(code: "workflow_rejected", message: error.localizedDescription)) }
                    } else {
                        response = await self.onPanelCommand?(request, fileTransfer) ?? WorkspaceAgentResponse(requestID: requestID, ok: false,
                            error: .init(code: "unavailable", message: "原生面板尚未連線。"))
                    }
                    guard self.generation == token, self.process != nil else { return }
                    do {
                        let result = try JSONSerialization.jsonObject(with: JSONEncoder().encode(response))
                        let envelope: [String: Any] = ["schemaVersion": 1, "sessionID": sessionID, "replyTo": requestID, "ok": true, "result": result]
                        self.panelInFlight.removeValue(forKey: requestID)
                        self.panelReplies[requestID] = (fingerprint, envelope)
                        self.panelReplyOrder.append(requestID)
                        if self.panelReplyOrder.count > 512 { self.panelReplies.removeValue(forKey: self.panelReplyOrder.removeFirst()) }
                        self.sendEnvelope(envelope)
                    } catch { self.fail("無法編碼面板結果。") }
                }
                continue
            }
            if message["notification"] as? String == "ready" {
                if state == .starting { timeoutTask?.cancel(); state = .ready }
                continue
            }
            guard let sequence = message["sequence"] as? Int, sequence > lastSequence else { continue }
            lastSequence = sequence
            if let event = message["event"] as? [String: Any], event["type"] as? String == "autonomy_state" {
                do {
                    let data = try JSONSerialization.data(withJSONObject: event["payload"] ?? [:])
                    try acceptAutonomy(JSONDecoder().decode(RuntimeAutonomySnapshot.self, from: data))
                } catch { fail(error.localizedDescription); return }
            }
            onEvent?(line)
        }
    }

    private func fail(_ message: String) {
        guard failureMessage == nil else { return }
        failureMessage = message
        stop()
        state = .failed(message)
    }

    func stop(completion: (() -> Void)? = nil) {
        if let completion { stopCompletions.append(completion) }
        guard let process else { finishStopCompletions(); return }
        guard state != .stopping, shutdownTask == nil else { return }
        timeoutTask?.cancel()
        state = .stopping
        request("shutdown")
        if let input { writes.async { try? input.close() } }
        let token = generation
        let grace = configuration?.shutdownGrace ?? .seconds(3)
        shutdownTask = Task { @MainActor [weak self, weak process] in
            do { try await Task.sleep(for: grace) } catch { return }
            guard let self, self.generation == token, let process, process.isRunning else { return }
            self.signalOwnedProcess(SIGTERM)
            do { try await Task.sleep(for: .seconds(2)) } catch { return }
            guard self.generation == token, process.isRunning else { return }
            self.signalOwnedProcess(SIGKILL)
        }
    }

    private func signalOwnedProcess(_ signal: Int32) {
        guard let process, process.isRunning else { return }
        if let group = ownedProcessGroup, group == process.processIdentifier { _ = Darwin.kill(-group, signal) }
        else { _ = Darwin.kill(process.processIdentifier, signal) }
    }

    private func didExit(code: Int32) {
        let wasStarting = state == .starting
        timeoutTask?.cancel(); shutdownTask?.cancel()
        timeoutTask = nil; shutdownTask = nil
        output?.readabilityHandler = nil
        try? input?.close(); try? output?.close(); try? log?.close()
        input = nil; output = nil; log = nil; process = nil; processID = nil; ownedProcessGroup = nil
        let callbacks = pending.values; pending.removeAll()
        for callback in callbacks { callback(false, "主 Agent 已離線。") }
        for id in Array(pendingResults.keys) {
            resolveResult(id, .failure(RuntimeRequestError.outcomeUnknown(pendingResults[id]?.method ?? "request")))
        }
        if let failureMessage { state = .failed(failureMessage) }
        else if code != 0 || wasStarting { state = .failed("程序已結束（\(code)）。") }
        else { state = .stopped }
        finishStopCompletions()
    }

    private func finishStopCompletions() {
        let callbacks = stopCompletions; stopCompletions.removeAll()
        for callback in callbacks { callback() }
    }
}
