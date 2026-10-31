import Foundation
public actor HostState {
    let store: SQLiteStore
    let toolkit:ToolkitArtifact?
    var runtimes:[String:AgentRuntimeView]=[:]
    var runtimeInputs:[String:[JSON]]=[:]
    var durable: DurableState
    var live: [String:LiveContext] = [:]
    var focusedSurface: String?
    var focusedNode: String?
    var activeApp = false
    var contextRevisions: [String:Int] = [:]
    var subscriptions: [String:Subscription] = [:]
    var sessions: [String:String] = [:]
    var replies: [String:CachedReply] = [:]
    var transientIdempotency: [String:CachedReply] = [:]
    var controlEvents: [String:[JSON]] = [:]
    var bridgeEpochs: [String:String] = [:]
    var streams: [String:DataStream] = [:]
    public init(path:String,toolkit:ToolkitArtifact?=nil) throws {store=try SQLiteStore(path:path);durable=try store.load();self.toolkit=toolkit}
    public func connect(principal: String, sessionID: String) throws {
        guard sessions[sessionID] == nil else { throw MUPError("unavailable", "Session already active") }
        guard sessions.count < 64 else { throw MUPError("quota", "Connection limit reached") }
        if let existing = sessions[sessionID], existing != principal { throw MUPError("forbidden", "Session unavailable") }
        sessions[sessionID] = principal
    }
    public func disconnect(sessionID: String) {
        let principal=sessions.removeValue(forKey:sessionID)
        runtimeInputs.removeValue(forKey:sessionID)
        if let principal,runtimes[principal]?.sessionID == sessionID {runtimes[principal]?.connected=false;runtimes[principal]?.modelActive=false;runtimes[principal]?.speechActive=false}
        subscriptions=subscriptions.filter {$0.value.sessionID != sessionID}
        controlEvents.removeValue(forKey:sessionID)
        replies=replies.filter {!$0.key.contains(":"+sessionID+":")}
        if let principal,!sessions.values.contains(principal) {markStreamsStale(principal:principal)}
    }
    public func revokePrincipal(_ principal: String) {
        sessions = sessions.filter { $0.value != principal }
        subscriptions = subscriptions.filter { $0.value.principal != principal }
        runtimes[principal]?.connected=false
        markStreamsStale(principal:principal)
    }
    public func surfacesForHost() -> [Surface] { durable.surfaces.values.sorted { $0.id < $1.id } }
    func allows(_ principal: String, _ surface: Surface, _ scope: Scope) -> Bool {
        surface.owner == principal || durable.grants.contains { $0.grantee == principal && $0.surfaceID == surface.id && $0.scopes.contains(scope) }
    }
    func visibleTo(_ principal: String, _ surface: Surface) -> Bool { surface.owner == principal || durable.grants.contains { $0.grantee == principal && $0.surfaceID == surface.id && !$0.scopes.isEmpty } }
    func surface(_ id: String, principal: String, scope: Scope? = nil, write: Bool = false) throws -> Surface {
        guard let s = durable.surfaces[id], visibleTo(principal, s), (!write || s.owner == principal), (scope == nil || allows(principal, s, scope!)) else { throw MUPError("forbidden", "Surface unavailable") }
        return s
    }
    public func handle(_ data: Data, principal: String, sessionID: String) -> JSON {
        var requestID = "00000000-0000-4000-8000-000000000000"
        do {
            if data.count<=1_048_576,let unvalidated=try? JSON.decode(data),let id=unvalidated["request_id"].string,UUID(uuidString:id) != nil {requestID=id}
            let request = try SchemaValidator.command(data)
            requestID = request["request_id"].string!
            guard sessions[sessionID] == principal, request["session_id"].string == sessionID else { throw MUPError("unauthenticated", "Session unavailable") }
            let name = request["name"].string!
            guard name != "host.authenticate" else { throw MUPError("invalid_state", "Already authenticated") }
            let payload = request["payload"]
            let fingerprint = JSON.object(["name":.s(name),"payload":payload])
            let key = principal + ":" + sessionID + ":" + requestID
            if let reply = replies[key] {
                guard reply.fingerprint == fingerprint else { throw MUPError("duplicate_request", "Request ID reused with different content") }
                if isMutation(name) || name.hasSuffix("subscribe") || name.hasPrefix("data.") || name.hasPrefix("agent.") { return success(requestID, reply.result) }
            }
            let ikey = request["idempotency_key"].string.map { principal + ":" + $0 }
            if let ikey, let cached = isMutation(name) ? durable.idempotency[ikey] : (name.hasPrefix("data.") ? transientIdempotency[ikey] : nil) {
                guard cached.fingerprint == fingerprint else { throw MUPError("duplicate_request", "Idempotency key reused with different content") }
                return success(requestID, cached.result)
            }
            let old = durable
            let oldLive=live, oldSubs=subscriptions, oldRevisions=contextRevisions, oldStreams=streams
            let oldSurface=focusedSurface, oldNode=focusedNode
            do {
                let result = try route(name, payload, principal: principal, sessionID: sessionID)
                if let ikey {
                    if isMutation(name) { durable.idempotency[ikey] = CachedReply(fingerprint:fingerprint,result:result) }
                    else if name.hasPrefix("data.") {if transientIdempotency.count>=2048 {transientIdempotency.removeAll()};transientIdempotency[ikey]=CachedReply(fingerprint:fingerprint,result:result)}
                }
                if durable.idempotency.count > 2048, let first = durable.idempotency.keys.sorted().first { durable.idempotency.removeValue(forKey: first) }
                if isMutation(name) {
                    try store.save(durable, principal: principal, action: name)
                    if let sid = payload["surface_id"].string {
                        if name == "surface.close", let removed=old.surfaces[sid] {
                            invalidateSurface(removed,principals:Set([removed.owner]+old.grants.filter {$0.surfaceID == sid}.map(\.grantee)))
                        }
                        let kind = name == "surface.detach" ? "context.surface_detached" : name == "surface.attach" ? "context.surface_attached" : name == "surface.set_visibility" ? "context.surface_visibility_changed" : "context.stale"
                        changed(kind,surfaceID:sid,fields: name == "surface.set_visibility" ? .object(["visible":payload["visible"]]) : .object([:]))
                    }
                }
                if replies.count >= 2048 { replies.removeAll(keepingCapacity: true) }
                replies[key] = CachedReply(fingerprint: fingerprint, result: result)
                return success(requestID, result)
            } catch { durable=old; live=oldLive; subscriptions=oldSubs; contextRevisions=oldRevisions; streams=oldStreams; focusedSurface=oldSurface; focusedNode=oldNode; throw error }
        } catch let error as MUPError { return .object(["protocol":.s(MUP.version),"request_id":.s(requestID),"ok":.bool(false),"error":error.json]) }
        catch { return .object(["protocol":.s(MUP.version),"request_id":.s(requestID),"ok":.bool(false),"error":MUPError("internal", "Command failed").json]) }
    }
    func success(_ id: String, _ result: JSON) -> JSON { .object(["protocol":.s(MUP.version),"request_id":.s(id),"ok":.bool(true),"result":result]) }
    func isMutation(_ name: String) -> Bool { name.hasPrefix("surface.") && !["surface.list","surface.get"].contains(name) || ["ui.render","ui.patch"].contains(name) }
    func route(_ name: String, _ p: JSON, principal: String, sessionID: String) throws -> JSON {
        switch name {
        case "host.toolkit.get":guard let toolkit else {throw MUPError("unavailable","Toolkit not bundled")};return toolkit.download
        case "agent.runtime.publish":return try runtimePublish(p,principal:principal,sessionID:sessionID)
        case "agent.input.poll":return runtimeInputsPoll(sessionID:sessionID)
        case "host.capabilities": return .object(["protocol":.s(MUP.version),"components":.array(["stack","text","button","table","chart.line","canvas","canvas.rect","canvas.ellipse","canvas.triangle","canvas.text"].map(JSON.s)),"commands":try SchemaValidator(name:"command").root["properties"]["name"]["enum"],"awareness":.bool(true),"max_message_bytes":.n(1_048_576),"overlays":.bool(false)])
        case "surface.create":
            let id = p["surface_id"].string!
            guard durable.surfaces[id] == nil else { throw MUPError("unavailable", "Surface ID unavailable") }
            guard durable.surfaces.count<256,durable.surfaces.values.filter({$0.owner == principal}).count < 32 else { throw MUPError("quota", "Surface quota reached") }
            guard p["kind"].string != "overlay" else { throw MUPError("unsupported", "Overlays are reserved") }
            try Document.validate(p["document"])
            let now = timestamp()
            let s = Surface(id: id, owner: principal, kind: p["kind"].string ?? "workspace", revision: 1, title: p["title"].string!, document: p["document"], placement: p["placement"].object == nil ? .object([:]) : p["placement"], visible: true, lifecycle: "active", createdAt: now, updatedAt: now)
            durable.surfaces[id] = s
            return s.json
        case "surface.list": return .array(durable.surfaces.values.filter { visibleTo(principal, $0) }.sorted { $0.id < $1.id }.map { summary($0) })
        case "surface.get", "ui.inspect": return try surface(p["surface_id"].string!, principal: principal, scope: .document).json
        case "surface.close", "surface.set_visibility", "surface.detach", "surface.attach":
            let id = p["surface_id"].string!
            var s = try surface(id, principal: principal, write: true)
            if name == "surface.close" { durable.surfaces.removeValue(forKey: id); durable.grants.removeAll { $0.surfaceID == id } }
            else { if name == "surface.set_visibility" { s.visible = p["visible"].bool! } else { s.kind = name == "surface.detach" ? "window" : "workspace" }; s.updatedAt = timestamp(); durable.surfaces[id] = s }
            return .object(["surface_id":.s(id),"kind":.s(s.kind),"visible":.bool(s.visible)])
        case "data.register", "data.publish", "data.unregister": return try dataCommand(name,p,principal:principal)
        case "ui.context.get": return try contextSnapshot(principal:principal,filters:p)
        case "ui.context.resolve_reference": return try resolveReference(principal:principal,query:p)
        case "ui.context.subscribe", "events.subscribe": return try subscribe(p,principal:principal,sessionID:sessionID,contextOnly:name == "ui.context.subscribe")
        case "ui.context.unsubscribe", "events.unsubscribe": return try unsubscribe(p,principal:principal,sessionID:sessionID)
        case "ui.render", "ui.patch":
            let id = p["surface_id"].string!
            var s = try surface(id, principal: principal, write: true)
            guard s.revision == p["expected_revision"].int else { throw MUPError("revision_conflict", "Document revision changed") }
            let doc = name == "ui.render" ? p["document"] : try Document.patch(s.document, operations: p["operations"].array!)
            try Document.validate(doc)
            if var context=live[id] {
                let ids=Set(Document.nodes(doc["root"]).filter {$0["props"]["sensitive"].bool != true}.compactMap {$0["node_id"].string})
                if let selected=context.selection["node_id"].string,!ids.contains(selected) {context.selection = .null}
                if let viewed=context.viewport["node_id"].string,!ids.contains(viewed) {context.viewport = .null}
                if let interacted=context.interaction["node_id"].string,!ids.contains(interacted) {context.interaction = .null}
                if focusedSurface == id,let focus=focusedNode,!ids.contains(focus) {focusedNode=nil}
                live[id]=context
            }
            s.document = doc; s.revision += 1; s.updatedAt = timestamp(); durable.surfaces[id] = s
            return .object(["surface_id":.s(id),"revision":.n(s.revision)])
        default: throw MUPError("unsupported", "Command not implemented")
        }
    }
    func summary(_ s: Surface) -> JSON { .object(["surface_id":.s(s.id),"owner_agent_id":.s(s.owner),"title":.s(s.title),"kind":.s(s.kind),"revision":.n(s.revision),"visible":.bool(s.visible)]) }
}
