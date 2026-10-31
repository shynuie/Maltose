import Foundation
extension HostState {
    public func updateWorkspaceLayout(surfaceID:String,placement:JSON) throws {
        guard durable.surfaces[surfaceID]?.kind == "workspace" else {return}
        try updateLayout(surfaceID:surfaceID,placement:placement)
    }
    public func updateLayout(surfaceID:String,placement:JSON) throws {
        guard var s=durable.surfaces[surfaceID] else {throw MUPError("unavailable","Surface unavailable")}
        // Reuse schema validation for bounds/unknown fields before persisting host geometry.
        let validator=try SchemaValidator(name:"command")
        let command:JSON = .object(["protocol":.s(MUP.version),"message_id":.s(UUID().uuidString),"request_id":.s(UUID().uuidString),"session_id":.s(UUID().uuidString),"type":.s("command"),"name":.s("surface.create"),"payload":.object(["surface_id":.s(s.id),"title":.s(s.title),"document":s.document,"placement":placement])])
        try validator.validate(command)
        guard s.placement != placement else {return}
        let old=durable
        s.placement=placement;if s.kind == "window" {s.userOverrides["window_placement"]=placement};s.updatedAt=timestamp();durable.surfaces[surfaceID]=s
        do {try store.save(durable,principal:"local.user",action:"layout.set")} catch {durable=old;throw error}
        changed("context.surface_moved",surfaceID:surfaceID,fields:.object(["layout":placement]))
    }
}
