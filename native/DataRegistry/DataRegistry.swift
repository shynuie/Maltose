import Foundation
extension HostState {
    func dataCommand(_ name:String,_ p:JSON,principal:String) throws -> JSON {
        let id=p["data_id"].string!, key=principal+":"+id
        switch name {
        case "data.register":
            guard streams[key] == nil else {throw MUPError("unavailable","Stream already registered")}
            guard streams.values.filter({$0.owner == principal}).count<32 else {throw MUPError("quota","Stream quota reached")}
            streams[key]=DataStream(owner:principal)
        case "data.publish":
            guard var stream=streams[key] else {throw MUPError("forbidden","Stream unavailable")}
            guard p["sequence"].int!>stream.sequence else {throw MUPError("duplicate_event","Data sequence must increase")}
            stream.sequence=p["sequence"].int!;stream.points=p["points"];stream.stale=false;streams[key]=stream
            for s in durable.surfaces.values where s.owner == principal && Document.nodes(s.document["root"]).contains(where:{$0["props"]["data_id"].string == id}) {
                for receiver in audience(s) where allows(receiver,s,.data) {enqueue("data.updated",surface:s,principal:receiver,changes:.object(["data_id":.s(id),"sequence":.n(stream.sequence),"stale":.bool(false)]))}
            }
        case "data.unregister":
            guard streams[key] != nil else {throw MUPError("forbidden","Stream unavailable")}
            streams.removeValue(forKey:key)
            for s in durable.surfaces.values where s.owner == principal && Document.nodes(s.document["root"]).contains(where:{$0["props"]["data_id"].string == id}) {changed("context.stale",surfaceID:s.id,fields:.object(["data_stale":.bool(true)]))}
        default: throw MUPError("unsupported","Unknown data command")
        }
        return .object(["data_id":.s(id),"accepted":.bool(true)])
    }
    func markStreamsStale(principal:String) {
        for key in streams.keys where streams[key]?.owner == principal {streams[key]?.stale=true}
        for s in durable.surfaces.values where s.owner == principal {changed("context.stale",surfaceID:s.id,fields:.object(["data_stale":.bool(true)]))}
    }
}
