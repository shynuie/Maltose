import Foundation
import Combine
import Darwin

/// Exact JSON-RPC IDs: a numeric ID and a string with the same digits are distinct.
enum CodexRPCID: Codable, Hashable, Sendable {
    case string(String), integer(Int64)
    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if let string = try? value.decode(String.self) { self = .string(string) }
        else { self = .integer(try value.decode(Int64.self)) }
    }
    func encode(to encoder: Encoder) throws {
        var value = encoder.singleValueContainer()
        switch self {
        case let .string(id): try value.encode(id)
        case let .integer(id): try value.encode(id)
        }
    }
}

struct CodexRPCFailure: Error, Codable, Equatable, LocalizedError {
    var code: Int
    var message: String
    var data: UserViewValue?
    var method: String? = nil
    enum CodingKeys: String, CodingKey { case code, message, data }
    var errorDescription: String? { message }
}

enum CodexConnectionError: Error, LocalizedError {
    case unavailable(String), protocolViolation(String), disconnected, outcomeUnknown(String)
    var errorDescription: String? {
        switch self {
        case let .unavailable(message), let .protocolViolation(message): message
        case .disconnected: "Codex 連線已中斷。請先核對任務狀態，再繼續操作。"
        case let .outcomeUnknown(method): "尚無法確認 Codex 的 \(method) 結果；請先讀回狀態，避免重複執行。"
        }
    }
}

struct CodexLaunchConfiguration {
    var executable: URL
    var arguments: [String] = ["app-server"]
    var directory: URL
    var logURL: URL
    var environment: [String: String]? = nil
    var startupTimeout: Duration = .seconds(20)
    var requestTimeout: Duration = .seconds(30)
    var shutdownGrace: Duration = .seconds(3)
    var ownsProcessGroup = false

    static func application() throws -> Self {
        let environment = ProcessInfo.processInfo.environment
        let paths = environment["MALTOSE_CODEX_EXECUTABLE"].map { [$0] }
            ?? ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"]
        guard let path = paths.first(where: { $0.hasPrefix("/") && FileManager.default.isExecutableFile(atPath: $0) }) else {
            throw CodexConnectionError.unavailable("找不到 Codex，請安裝 CLI 或設定 MALTOSE_CODEX_EXECUTABLE 絕對路徑。")
        }
        let support = try RuntimeLaunchConfiguration.supportDirectory()
        guard let resources = Bundle.main.resourceURL else { throw CodexConnectionError.unavailable("找不到 Codex 管理程序。") }
        var childEnvironment = environment
        childEnvironment["PYTHONPATH"] = resources.appendingPathComponent("Runtime").path
        childEnvironment["PYTHONDONTWRITEBYTECODE"] = "1"
        return .init(executable: support.appendingPathComponent("environments/main/bin/python"),
                     arguments: ["-m", "maltose.codex.runner", path, "app-server"], directory: support,
                     logURL: support.appendingPathComponent("logs/codex.log"), environment: childEnvironment, ownsProcessGroup: true)
    }
}

struct CodexServerRequest {
    let id: CodexRPCID
    let method: String
    let params: UserViewValue
    /// A response to a previous process must never answer a new process's request.
    let connectionID: UUID
}

/// Private stdio JSON-RPC transport. It never retries mutations or grants approval.
/// A single stream consumer preserves frame order, including exit after final stdout.
@MainActor final class CodexConnection: ObservableObject {
    enum State: Equatable { case stopped, starting, ready, stopping, failed(String) }
    @Published private(set) var state: State = .stopped
    private(set) var ownedCleanupConfirmed = true
    private var lifetimeToken: String?
    private var lifetimeFailed = false
    private var initializationCompleted = false
    private(set) var processID: Int32?
    private(set) var connectionID = UUID()
    var onNotification: ((String, UserViewValue) -> Void)?
    var onServerRequest: ((CodexServerRequest) -> Void)?
    var experimentalAPI = false
    var onDisconnect: (() -> Void)?

    private struct Message: Codable {
        var id: CodexRPCID?
        var method: String?
        var params: UserViewValue?
        var result: UserViewValue?
        var error: CodexRPCFailure?

        init(id: CodexRPCID? = nil, method: String? = nil, params: UserViewValue? = nil,
             result: UserViewValue? = nil, error: CodexRPCFailure? = nil) {
            self.id = id; self.method = method; self.params = params; self.result = result; self.error = error
        }
        enum CodingKeys: String, CodingKey { case id, method, params, result, error }
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            id = try values.decodeIfPresent(CodexRPCID.self, forKey: .id)
            method = try values.decodeIfPresent(String.self, forKey: .method)
            params = try values.decodeIfPresent(UserViewValue.self, forKey: .params)
            // JSON-RPC permits a literal null result; distinguish it from a missing result.
            result = values.contains(.result) ? try values.decode(UserViewValue.self, forKey: .result) : nil
            error = try values.decodeIfPresent(CodexRPCFailure.self, forKey: .error)
        }
    }
    private struct Pending {
        var method: String
        var continuation: CheckedContinuation<UserViewValue, Error>
        var timeout: Task<Void, Never>
    }
    private enum ReadEvent: Sendable { case bytes(Data), eof, exit(Int32), readFailed }
    private struct ServerPending { var fingerprint: Data }
    private struct ServerReply { var fingerprint: Data; var bytes: Data? }
    private struct ResolvedNotification: Decodable {
        struct Params: Decodable { var requestId: CodexRPCID }
        var params: Params
    }
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var diagnostic: FileHandle?
    private var buffer = Data()
    private var discardingFrame = false
    private var pending: [CodexRPCID: Pending] = [:]
    private var serverPending: [CodexRPCID: ServerPending] = [:]
    private var serverReplies: [CodexRPCID: ServerReply] = [:]
    private var serverReplyOrder: [CodexRPCID] = []
    private var reader: Task<Void, Never>?
    private var shutdownTask: Task<Void, Never>?
    private var configuration: CodexLaunchConfiguration?
    private var exitCode: Int32?
    private var hasEOF = false
    private var failure: String?
    private var ownedGroup: Int32?
    private var stopCompletions: [() -> Void] = []
    private let writes = DispatchQueue(label: "maltose.codex.stdin")
    private static let maximumFrame = 16 * 1024 * 1024

    func start(configuration: CodexLaunchConfiguration) async throws {
        guard process == nil else {
            if state == .ready { return }
            throw CodexConnectionError.unavailable("Codex 正在啟動或結束，請等待連線狀態確認。")
        }
        guard ownedCleanupConfirmed else { throw CodexConnectionError.unavailable("上一個 Codex 的背景程序清理尚未確認，請先檢查程序狀態。") }
        guard FileManager.default.isExecutableFile(atPath: configuration.executable.path) else {
            throw CodexConnectionError.unavailable("Codex 執行檔不可用。")
        }
        try FileManager.default.createDirectory(at: configuration.logURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        if !FileManager.default.fileExists(atPath: configuration.logURL.path) {
            FileManager.default.createFile(atPath: configuration.logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let log = try FileHandle(forWritingTo: configuration.logURL)
        try log.seekToEnd()
        let child = Process(), stdinPipe = Pipe(), stdoutPipe = Pipe()
        child.executableURL = configuration.executable
        child.arguments = configuration.arguments
        child.currentDirectoryURL = configuration.directory
        child.environment = configuration.environment ?? ProcessInfo.processInfo.environment
        child.standardInput = stdinPipe; child.standardOutput = stdoutPipe; child.standardError = log
        let token = UUID()
        connectionID = token; self.configuration = configuration
        failure = nil; exitCode = nil; hasEOF = false; ownedGroup = nil; buffer.removeAll(); discardingFrame = false
        ownedCleanupConfirmed = !configuration.ownsProcessGroup; lifetimeToken = nil; lifetimeFailed = false; initializationCompleted = false
        serverPending.removeAll(); serverReplies.removeAll(); serverReplyOrder.removeAll()
        let (stream, continuation) = AsyncStream<ReadEvent>.makeStream()
        child.terminationHandler = { child in continuation.yield(.exit(child.terminationStatus)) }
        _ = Darwin.fcntl(stdinPipe.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        process = child; input = stdinPipe.fileHandleForWriting; output = stdoutPipe.fileHandleForReading
        diagnostic = log; state = .starting
        do { try child.run() }
        catch {
            child.terminationHandler = nil
            hasEOF = true; exitCode = -1; failure = error.localizedDescription
            finishExit(); throw error
        }
        processID = child.processIdentifier
        if configuration.ownsProcessGroup, Darwin.getpgid(child.processIdentifier) == child.processIdentifier { ownedGroup = child.processIdentifier }
        let outputFD = stdoutPipe.fileHandleForReading.fileDescriptor
        DispatchQueue(label: "maltose.codex.stdout").async {
            // FileHandle.read(upToCount:) may wait to fill the requested count on a
            // pipe. POSIX read returns an available fragment so handshakes cannot stall.
            var bytes = [UInt8](repeating: 0, count: 64 * 1024)
            while true {
                let count = bytes.withUnsafeMutableBytes { Darwin.read(outputFD, $0.baseAddress, $0.count) }
                if count > 0 { continuation.yield(.bytes(Data(bytes.prefix(count)))) }
                else if count == 0 { break }
                else if errno != EINTR { continuation.yield(.readFailed); break }
            }
            continuation.yield(.eof)
        }
        reader = Task { @MainActor [weak self] in
            for await event in stream {
                guard let self, self.connectionID == token else { break }
                switch event {
                case let .bytes(data): self.receive(data)
                case .eof:
                    self.hasEOF = true
                    if !self.buffer.isEmpty { self.fail("Codex 在 JSON 訊框完成前中斷。") }
                    else if self.exitCode == nil && self.state != .stopping { self.fail("Codex 已關閉輸出。") }
                case let .exit(code):
                    self.exitCode = code
                    if let group = self.ownedGroup { _ = Darwin.kill(-group, SIGKILL) }
                case .readFailed: self.fail("無法讀取 Codex 回覆。")
                }
                if self.hasEOF, self.exitCode != nil { self.finishExit(); break }
            }
            continuation.finish()
        }
        do {
            _ = try await request("initialize", params: .object([
                "clientInfo": .object(["name": .string("maltose"), "title": .string("Maltose"), "version": .string(MaltoseProduct.version)]),
                "capabilities": .object(["experimentalApi": .boolean(experimentalAPI)])
            ]), timeout: configuration.startupTimeout, duringInitialization: true)
            guard connectionID == token, state == .starting else { throw CodexConnectionError.disconnected }
            try send(Message(method: "initialized", params: .object([:])))
            if configuration.ownsProcessGroup, Darwin.getpgid(child.processIdentifier) == child.processIdentifier {
                ownedGroup = child.processIdentifier
            } else if configuration.ownsProcessGroup {
                throw CodexConnectionError.protocolViolation("Codex 管理程序沒有建立獨立的程序群組。")
            }
            initializationCompleted = true
            state = .ready
        } catch {
            if connectionID == token, state != .stopping { fail("Codex 初始化失敗：\(error.localizedDescription)") }
            throw error
        }
    }

    func request(_ method: String, params: UserViewValue = .object([:]), timeout: Duration? = nil) async throws -> UserViewValue {
        try await request(method, params: params, timeout: timeout, duringInitialization: false)
    }

    private func request(_ method: String, params: UserViewValue, timeout: Duration?, duringInitialization: Bool) async throws -> UserViewValue {
        guard state == .ready || (duringInitialization && state == .starting), input != nil else {
            throw CodexConnectionError.disconnected
        }
        guard pending.count < 256 else { throw CodexConnectionError.unavailable("Codex 待處理請求過多。") }
        let id = CodexRPCID.string(UUID().uuidString), token = connectionID
        let duration = timeout ?? configuration?.requestTimeout ?? .seconds(30)
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                let timer = Task { @MainActor [weak self] in
                    do { try await Task.sleep(for: duration) } catch { return }
                    guard let self, self.connectionID == token else { return }
                    self.resolve(id, result: .failure(CodexConnectionError.outcomeUnknown(method)))
                }
                pending[id] = Pending(method: method, continuation: continuation, timeout: timer)
                do { try send(Message(id: id, method: method, params: params)) }
                catch { resolve(id, result: .failure(error)) }
            }
        } onCancel: {
            Task { @MainActor [weak self] in
                guard let self, self.connectionID == token else { return }
                // Cancelling observation does not prove that the server cancelled the operation.
                self.resolve(id, result: .failure(CodexConnectionError.outcomeUnknown(method)))
            }
        }
    }

    @discardableResult func respond(to request: CodexServerRequest, result: Result<UserViewValue, CodexRPCFailure>) -> Bool {
        guard request.connectionID == connectionID, state == .ready,
              let item = serverPending.removeValue(forKey: request.id) else { return false }
        let message: Message
        switch result {
        case let .success(value): message = Message(id: request.id, result: value)
        case let .failure(error): message = Message(id: request.id, error: error)
        }
        do {
            let bytes = try encode(message)
            cacheReply(request.id, fingerprint: item.fingerprint, bytes: bytes)
            try write(bytes); return true
        } catch { fail("無法回傳 Codex 確認結果。"); return false }
    }

    /// The task coordinator must interrupt/reconcile active work before closing its transport.
    func stop(completion: (() -> Void)? = nil) {
        if let completion { stopCompletions.append(completion) }
        guard let child = process else { completeStops(); return }
        guard state != .stopping else { return }
        state = .stopping
        rejectPending()
        let token = connectionID, grace = configuration?.shutdownGrace ?? .seconds(3)
        let handle = input; input = nil
        writes.async { try? handle?.close() }
        shutdownTask = Task { @MainActor [weak self] in
            do { try await Task.sleep(for: grace) } catch { return }
            guard let self, self.connectionID == token, self.process != nil else { return }
            if let group = self.ownedGroup { _ = Darwin.kill(-group, SIGTERM) }
            else if child.isRunning { child.terminate() }
            do { try await Task.sleep(for: .seconds(2)) } catch { return }
            guard self.connectionID == token, self.process != nil else { return }
            if let group = self.ownedGroup { _ = Darwin.kill(-group, SIGKILL) }
            else if child.isRunning { _ = Darwin.kill(child.processIdentifier, SIGKILL) }
        }
    }

    private func receive(_ data: Data) {
        if failure != nil, configuration?.ownsProcessGroup != true { return }
        var offset = 0
        while offset < data.count {
            // Search only the new fragment. Rescanning an accumulated large
            // frame on every read otherwise makes framing quadratic on MainActor.
            let boundary: Int? = data.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) -> Int? in
                guard let base = bytes.baseAddress,
                      let found = Darwin.memchr(base.advanced(by: offset), 10, bytes.count - offset) else { return nil }
                return base.distance(to: UnsafeRawPointer(found))
            }
            let end = boundary ?? data.count
            if !discardingFrame {
                let lower = data.index(data.startIndex, offsetBy: offset)
                let upper = data.index(data.startIndex, offsetBy: end)
                buffer.append(data[lower..<upper])
                if buffer.count > Self.maximumFrame {
                    fail("Codex 訊框超過大小限制。")
                    buffer.removeAll(); discardingFrame = true
                }
            }
            offset = end + (boundary == nil ? 0 : 1)
            guard boundary != nil else { break }
            if discardingFrame { discardingFrame = false; buffer.removeAll(); continue }
            let line = buffer; buffer = Data()
            if line.isEmpty, lifetimeToken != nil { continue }
            guard !line.isEmpty else { fail("Codex 訊框大小或內容不正確。"); return }
            do {
                if failure != nil {
                    let message = try JSONDecoder().decode(Message.self, from: line)
                    guard message.method?.hasPrefix("maltose/lifetime/") == true else { continue }
                }
                try receiveMessage(line)
            }
            catch {
                fail("Codex 協定不相容：\(error.localizedDescription)")
                if lifetimeToken == nil { return }
            }
        }
    }

    private func receiveMessage(_ bytes: Data) throws {
        let message = try JSONDecoder().decode(Message.self, from: bytes)
        if let method = message.method {
            guard message.result == nil, message.error == nil else {
                throw CodexConnectionError.protocolViolation("請求不能同時包含回應。")
            }
            let params = message.params ?? .object([:])
            guard let id = message.id else {
                if method.hasPrefix("maltose/lifetime/"), configuration?.ownsProcessGroup == true {
                    guard params["rootPID"] == .number(Double(processID ?? -1)) else {
                        throw CodexConnectionError.protocolViolation("Codex 收尾訊息的來源不符。")
                    }
                    if method == "maltose/lifetime/startup_aborted" {
                        guard !initializationCompleted else { throw CodexConnectionError.protocolViolation("已就緒的 Codex 不能宣稱未啟動。") }
                        ownedCleanupConfirmed = true
                        return
                    }
                    guard let token = params["token"]?.stringValue, UUID(uuidString: token) != nil else {
                        throw CodexConnectionError.protocolViolation("Codex 收尾訊息的來源不符。")
                    }
                    if method == "maltose/lifetime/started" {
                        guard lifetimeToken == nil else { throw CodexConnectionError.protocolViolation("Codex 收尾保護重複註冊。") }
                        lifetimeToken = token
                        if let pid = processID, Darwin.getpgid(pid) == pid { ownedGroup = pid }
                    } else {
                        guard lifetimeToken == token else { throw CodexConnectionError.protocolViolation("Codex 收尾保護已失效。") }
                        if method == "maltose/lifetime/cleaned" {
                            guard !lifetimeFailed else { throw CodexConnectionError.protocolViolation("失敗的收尾保護不能被覆寫。") }
                            ownedCleanupConfirmed = true
                        }
                        else if method == "maltose/lifetime/failed" { lifetimeFailed = true; ownedCleanupConfirmed = false; fail("Codex 背景程序清理尚未確認。") }
                        else { throw CodexConnectionError.protocolViolation("不支援的 Codex 收尾狀態。") }
                    }
                    return
                }
                if method == "serverRequest/resolved" {
                    let id = try JSONDecoder().decode(ResolvedNotification.self, from: bytes).params.requestId
                    if let pending = serverPending.removeValue(forKey: id) {
                        cacheReply(id, fingerprint: pending.fingerprint, bytes: nil)
                    }
                }
                onNotification?(method, params); return
            }
            guard state == .ready else { throw CodexConnectionError.protocolViolation("初始化完成前收到工具或批准請求。") }
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
            let fingerprint = try encoder.encode(Message(method: method, params: params))
            if let reply = serverReplies[id] {
                guard reply.fingerprint == fingerprint else { throw CodexConnectionError.protocolViolation("請求識別碼重複但內容不同。") }
                if let bytes = reply.bytes { try write(bytes) }; return
            }
            if let existing = serverPending[id] {
                guard existing.fingerprint == fingerprint else { throw CodexConnectionError.protocolViolation("等待中的請求識別碼衝突。") }
                return
            }
            guard serverPending.count < 256 else { throw CodexConnectionError.protocolViolation("Codex 待處理確認過多。") }
            let request = CodexServerRequest(id: id, method: method, params: params, connectionID: connectionID)
            serverPending[id] = ServerPending(fingerprint: fingerprint)
            if let onServerRequest { onServerRequest(request) }
            else { _ = respond(to: request, result: .failure(.init(code: -32601, message: "Maltose 尚未支援此請求。"))) }
        } else {
            guard let id = message.id, (message.result != nil) != (message.error != nil) else {
                throw CodexConnectionError.protocolViolation("回應缺少識別碼或結果。")
            }
            if var error = message.error {
                error.method = pending[id]?.method
                resolve(id, result: .failure(error))
            }
            else if let result = message.result { resolve(id, result: .success(result)) }
        }
    }

    private func resolve(_ id: CodexRPCID, result: Result<UserViewValue, Error>) {
        guard let item = pending.removeValue(forKey: id) else { return }
        item.timeout.cancel(); item.continuation.resume(with: result)
    }
    private func cacheReply(_ id: CodexRPCID, fingerprint: Data, bytes: Data?) {
        serverReplies[id] = ServerReply(fingerprint: fingerprint, bytes: bytes)
        serverReplyOrder.append(id)
        if serverReplyOrder.count > 256 { serverReplies.removeValue(forKey: serverReplyOrder.removeFirst()) }
    }
    private func rejectPending() {
        for id in Array(pending.keys) {
            let method = pending[id]?.method ?? "request"
            resolve(id, result: .failure(CodexConnectionError.outcomeUnknown(method)))
        }
    }
    private func encode(_ message: Message) throws -> Data {
        var data = try JSONEncoder().encode(message)
        guard data.count <= Self.maximumFrame else { throw CodexConnectionError.unavailable("Codex 請求超過大小限制。") }
        data.append(10); return data
    }
    private func send(_ message: Message) throws { try write(encode(message)) }
    private func write(_ bytes: Data) throws {
        guard let handle = input else { throw CodexConnectionError.disconnected }
        let token = connectionID
        writes.async { [weak self] in
            do { try handle.write(contentsOf: bytes) }
            catch {
                Task { @MainActor [weak self] in
                    guard let self, self.connectionID == token else { return }
                    self.fail("無法送出 Codex 請求。")
                }
            }
        }
    }
    private func fail(_ message: String) {
        if failure == nil { failure = message }
        stop()
    }
    private func finishExit() {
        if configuration?.ownsProcessGroup == true, !ownedCleanupConfirmed, failure == nil { failure = "Codex 背景程序清理尚未確認。" }
        let wasStopping = state == .stopping
        shutdownTask?.cancel(); shutdownTask = nil
        rejectPending(); serverPending.removeAll()
        try? output?.close(); output = nil
        try? input?.close(); input = nil
        try? diagnostic?.close(); diagnostic = nil
        process?.terminationHandler = nil; process = nil; processID = nil; ownedGroup = nil
        state = failure.map(State.failed) ?? (wasStopping ? .stopped : .failed("Codex 程序已退出（\(exitCode ?? -1)）。"))
        onDisconnect?(); completeStops()
    }
    private func completeStops() {
        let callbacks = stopCompletions; stopCompletions.removeAll()
        callbacks.forEach { $0() }
    }
}

extension UserViewValue {
    var objectValue: [String: UserViewValue]? { if case let .object(value) = self { value } else { nil } }
    var stringValue: String? { if case let .string(value) = self { value } else { nil } }
    subscript(_ key: String) -> UserViewValue? { objectValue?[key] }
}
