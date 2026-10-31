import Foundation
extension HostState {
    /// Invoked by AppKit only. Renderer cannot claim another native window has focus.
    public func nativeFocus(surfaceID: String?, active: Bool = true) {
        guard focusedSurface != (active ? surfaceID : nil) || activeApp != active else {return}
        let old = focusedSurface
        if let surfaceID { var c = live[surfaceID] ?? LiveContext(); c.updated = Date();c.observedAt=Date(); live[surfaceID] = c }
        activeApp = active
        focusedSurface = active ? surfaceID : nil
        if old != focusedSurface { focusedNode = nil }
        if let old, old != focusedSurface { changed("context.focus_changed",surfaceID:old) }
        if let current = focusedSurface { changed("context.focus_changed",surfaceID:current) }
    }
    public func openBridge(surfaceID: String, epoch: String) {
        bridgeEpochs[surfaceID] = epoch
        var context = live[surfaceID] ?? LiveContext()
        context.bridgeSequence = -1
        live[surfaceID] = context
    }
    public func acceptBridge(_ message: JSON, boundSurface: String, epoch: String) throws {
        try SchemaValidator(name:"bridge").validate(message)
        guard bridgeEpochs[boundSurface] == epoch, message["surface_id"].string == boundSurface, let s = durable.surfaces[boundSurface], s.visible, s.revision == message["document_revision"].int else { throw MUPError("invalid_bridge", "Stale or unbound renderer") }
        let nodeID = message["node_id"].string!
        guard let node = Document.nodes(s.document["root"]).first(where:{$0["node_id"].string == nodeID}), node["props"]["sensitive"].bool != true else {throw MUPError("invalid_bridge","Node unavailable")}
        var context = live[boundSurface] ?? LiveContext()
        guard message["sequence"].int! > context.bridgeSequence else { throw MUPError("duplicate_event","Out-of-order bridge event") }
        let kind = message["kind"].string!
        switch kind {
        case "focus_changed": break
        case "selection_changed":
            guard message["selection"] == .null || message["selection"]["node_id"].string == nodeID, message["selection"]["kind"].string != "chart.time_range" || node["type"].string == "chart.line" else { throw MUPError("invalid_bridge","Invalid selection target") }
            context.selection = message["selection"]
        case "viewport_changed":
            guard message["viewport"]["node_id"].string == nodeID, node["type"].string == "chart.line" else { throw MUPError("invalid_bridge","Viewport requires a chart") }
            var updated=s
            updated.userOverrides["viewport"] = message["viewport"]
            let old=durable
            durable.surfaces[boundSurface]=updated
            do {try store.save(durable,principal:"local.user",action:"viewport.override")} catch {durable=old;throw error}
            context.viewport = message["viewport"]
            changed("context.user_override_changed",surfaceID:boundSurface)
        case "action":
            let action = message["action_id"].string!
            guard node["type"].string == "button", node["props"]["action_id"].string == action, (s.document["actions"].array ?? []).contains(.s(action)) else {throw MUPError("invalid_action","Action unavailable")}
        default: throw MUPError("invalid_bridge","Unsupported semantic event")
        }
        context.bridgeSequence = message["sequence"].int!
        context.updated = Date()
        context.observedAt=Date()
        context.interaction = .object(["node_id":.s(nodeID),"at":.s(timestamp())])
        live[boundSurface] = context
        if focusedSurface == boundSurface, focusedNode != nodeID { focusedNode = nodeID; changed("context.focus_changed",surfaceID:boundSurface) }
        if kind == "focus_changed" {return}
        if kind == "action" {
            for principal in audience(s) where allows(principal,s,.events) { enqueue("ui.action",surface:s,principal:principal,changes:.object(["node_id":.s(nodeID),"action_id":message["action_id"]])) }
        } else { changed(kind == "selection_changed" ? "context.selection_changed" : "context.viewport_changed",surfaceID:boundSurface,fields:.object([kind == "selection_changed" ? "selection" : "viewport":kind == "selection_changed" ? context.selection : context.viewport])) }
    }
    public func rendererSnapshot(surfaceID:String,epoch:String?=nil) throws->JSON {
        if let epoch {
            guard bridgeEpochs[surfaceID] == epoch else {throw MUPError("invalid_bridge","Renderer epoch expired")}
            if var context=live[surfaceID] {context.observedAt=Date();live[surfaceID]=context}
        }
        guard let s = durable.surfaces[surfaceID] else {throw MUPError("unavailable","Surface unavailable")}
        var data: [String:JSON] = [:]
        for node in Document.nodes(s.document["root"]) {
            if let id = node["props"]["data_id"].string {
                let stream = streams[s.owner+":"+id]
                if stream == nil || stream?.owner == s.owner { data[id] = .object(["points":stream?.points ?? .array([]),"stale":.bool(stream?.stale ?? true)]) }
            }
        }
        return .object(["surface_id":.s(s.id),"document_revision":.n(s.revision),"document":s.document,"selection":live[s.id]?.selection ?? .null,"viewport":(live[s.id]?.viewport != .null ? live[s.id]?.viewport : nil) ?? s.userOverrides["viewport"],"streams":.object(data)])
    }
}
