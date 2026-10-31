import Foundation
@preconcurrency import Network
/// Network.framework provides RFC6455 framing/upgrade, message limits and ping handling.
public final class LoopbackServer: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "maltose.loopback")
    private let host: HostState
    private let registry: AgentRegistry
    private let admission=ConnectionAdmission()
    public let pairing:PairingCoordinator
    public let instanceID:String
    public let hostID:String
    public init(host:HostState,registry:AgentRegistry,port:UInt16=0,pairing:PairingCoordinator?=nil,instanceID:String=UUID().uuidString,hostID:String?=nil) throws {
        self.pairing=pairing ?? PairingCoordinator(registry:registry);self.instanceID=instanceID;self.hostID=hostID ?? instanceID
        self.host = host; self.registry = registry
        let options = NWProtocolWebSocket.Options()
        options.autoReplyPing = true
        options.maximumMessageSize = 1_048_576
        options.setClientRequestHandler(queue) { _, headers in
            // SDK-only endpoint. Browser origins (including null/file) have no access.
            let browser = headers.contains { $0.name.lowercased() == "origin" }
            return NWProtocolWebSocket.Response(status: browser ? .reject : .accept, subprotocol: nil)
        }
        let params = NWParameters.tcp
        params.defaultProtocolStack.applicationProtocols.insert(options, at: 0)
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!)
        listener = try NWListener(using: params)
    }
    public func start() async throws -> UInt16 {
        try await withCheckedThrowingContinuation { continuation in
            let once = StartContinuation(continuation)
            listener.stateUpdateHandler = { [listener] state in
                switch state { case .ready: once.finish(.success(listener.port!.rawValue)); case .failed(let error): once.finish(.failure(error)); case .cancelled: once.finish(.failure(MUPError("transport", "Listener cancelled"))); default: break }
            }
            listener.newConnectionHandler = { [host, registry, queue, admission, pairing, instanceID, hostID] connection in
                guard admission.acquire(connection) else {connection.cancel();return}
                connection.start(queue: queue)
                let peer = Peer(connection: connection, host: host, registry: registry, admission:admission,pairing:pairing,instanceID:instanceID,hostID:hostID)
                Task { await peer.run() }
            }
            listener.start(queue: queue)
        }
    }
    public func stop() { listener.cancel();admission.cancelAll() }
}
private final class StartContinuation: @unchecked Sendable {
    let lock = NSLock()
    var continuation: CheckedContinuation<UInt16, any Error>?
    init(_ c: CheckedContinuation<UInt16, any Error>) { continuation = c }
    func finish(_ result: Result<UInt16, any Error>) { lock.lock(); let c = continuation; continuation = nil; lock.unlock(); c?.resume(with: result) }
}
private final class ConnectionAdmission:@unchecked Sendable {
    private let lock=NSLock();private var connections:[ObjectIdentifier:NWConnection]=[:]
    func acquire(_ connection:NWConnection)->Bool {lock.lock();defer {lock.unlock()};guard connections.count<64 else {return false};connections[ObjectIdentifier(connection)]=connection;return true}
    func release(_ connection:NWConnection){lock.lock();connections.removeValue(forKey:ObjectIdentifier(connection));lock.unlock()}
    func cancelAll(){lock.lock();let active=Array(connections.values);lock.unlock();for connection in active {connection.cancel()}}
}
private actor Peer {
    let connection: NWConnection
    let host: HostState
    let registry: AgentRegistry
    let admission:ConnectionAdmission
    let pairing:PairingCoordinator
    let instanceID:String
    let hostID:String
    let admittedAt=Date()
    var authDeadline=Date().addingTimeInterval(5)
    var rateStart=Date(), rateCount=0
    var principal: String?
    var sessionID: String?
    var token: String?
    var pump: Task<Void,Never>?
    init(connection:NWConnection,host:HostState,registry:AgentRegistry,admission:ConnectionAdmission,pairing:PairingCoordinator,instanceID:String,hostID:String){self.connection=connection;self.host=host;self.registry=registry;self.admission=admission;self.pairing=pairing;self.instanceID=instanceID;self.hostID=hostID}
    func run() async {
        let timeout=Task {while self.principal == nil,!Task.isCancelled {do {try await Task.sleep(for:.milliseconds(250))} catch {return};if Date()>self.authDeadline {self.connection.cancel();return}}}
        defer { timeout.cancel(); pump?.cancel(); connection.cancel(); admission.release(connection) }
        do {
            while true {
                let data = try await receive()
                if Date().timeIntervalSince(rateStart)>=1 {rateStart=Date();rateCount=0}
                rateCount += 1
                guard rateCount<=200 else {throw MUPError("quota","Request rate exceeded")}
                guard let principal, let sessionID, let token else {
                    let request = try SchemaValidator.command(data)
                    let name=request["name"].string!,payload=request["payload"]
                    if ["host.discover","host.pair.request","host.pair.poll"].contains(name) {
                        do {
                            let result:JSON
                            switch name {
                            case "host.discover":result = .object(["protocol":.s(MUP.version),"instance_id":.s(instanceID),"host_id":.s(hostID),"name":.s("Maltose UI Host"),"pairing":.bool(true)])
                            case "host.pair.request":
                                result=try await pairing.request(name:payload["name"].string!,agentID:payload["agent_id"].string!,claim:payload["claim"].string!)
                                authDeadline=admittedAt.addingTimeInterval(125)
                            default:result=try await pairing.poll(id:payload["pairing_id"].string!,claim:payload["claim"].string!)
                            }
                            try await send(.object(["protocol":.s(MUP.version),"request_id":request["request_id"],"ok":.bool(true),"result":result]))
                        } catch let error as MUPError {try await send(.object(["protocol":.s(MUP.version),"request_id":request["request_id"],"ok":.bool(false),"error":error.json]))}
                        continue
                    }
                    guard name == "host.authenticate" else {throw MUPError("unauthenticated","Authenticate first")}
                    let secret = request["payload"]["token"].string!
                    let authenticated = try await registry.authenticate(secret)
                    let session = UUID().uuidString
                    try await host.connect(principal: authenticated, sessionID: session)
                    self.principal = authenticated; self.sessionID = session; self.token = secret
                    let reply: JSON = .object(["protocol":.s(MUP.version),"request_id":request["request_id"],"ok":.bool(true),"result":.object(["principal":.s(authenticated),"session_id":.s(session),"protocol":.s(MUP.version)])])
                    try await send(reply)
                    pump = Task { await self.events() }
                    continue
                }
                guard try await registry.authenticate(token) == principal else { throw MUPError("unauthenticated", "Credential revoked") }
                let response = await host.handle(data, principal: principal, sessionID: sessionID)
                try await send(response)
            }
        } catch { /* Intentionally omit payloads/tokens and cross-agent diagnostics. */ }
        if let sessionID { await host.disconnect(sessionID: sessionID) }
    }
    func receive() async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            connection.receiveMessage { data, context, _, error in
                if let error { continuation.resume(throwing: error); return }
                let metadata = context?.protocolMetadata(definition: NWProtocolWebSocket.definition) as? NWProtocolWebSocket.Metadata
                guard metadata?.opcode == .text, let data, data.count <= 1_048_576 else { continuation.resume(throwing: MUPError("invalid_message", "Expected text message")); return }
                continuation.resume(returning: data)
            }
        }
    }
    func send(_ value: JSON) async throws {
        let data = try value.data()
        let context = NWConnection.ContentContext(identifier: "mup", metadata: [NWProtocolWebSocket.Metadata(opcode: .text)])
        try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, any Error>) in
            connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { error in if let error { c.resume(throwing: error) } else { c.resume() } })
        }
    }
    func events() async {
        while !Task.isCancelled {
            do {
                try await Task.sleep(for: .milliseconds(50))
                guard let principal, let sessionID, let token, try await registry.authenticate(token) == principal else { connection.cancel(); return }
                for event in await host.drainEvents(principal: principal, sessionID: sessionID) { try await send(event) }
            } catch { connection.cancel(); return }
        }
    }
}
