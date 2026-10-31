import Foundation
import Darwin
public final class DiscoveryPublisher:@unchecked Sendable {
    public let instanceID=UUID().uuidString
    public let hostID:String
    private let directory:URL
    private var record:URL?
    public init(directory:URL?=nil) throws {
        self.directory=directory ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("MaltoseUIHost/discovery")
        try FileManager.default.createDirectory(at:self.directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        let identity=self.directory.deletingLastPathComponent().appendingPathComponent("host-id")
        try FileManager.default.setAttributes([.posixPermissions:0o700],ofItemAtPath:self.directory.path)
        if !FileManager.default.fileExists(atPath:identity.path) {
            let temp=identity.deletingLastPathComponent().appendingPathComponent(".host-id-"+UUID().uuidString)
            defer {try? FileManager.default.removeItem(at:temp)}
            try Data(UUID().uuidString.utf8).write(to:temp,options:.withoutOverwriting)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:temp.path)
            // Publish a fully written identity once, including simultaneous Host launches.
            guard link(temp.path,identity.path)==0 || errno==EEXIST else {throw MUPError("discovery","Cannot publish host identity")}
        }
        let existing=try String(contentsOf:identity,encoding:.utf8)
        guard UUID(uuidString:existing) != nil else {throw MUPError("discovery","Invalid host identity; inspect it before replacing")}
        hostID=existing
    }
    public func publish(port:UInt16) throws {
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        let url=directory.appendingPathComponent(instanceID+".json")
        let value:JSON = .object(["protocol":.s(MUP.version),"instance_id":.s(instanceID),"host_id":.s(hostID),"name":.s("Maltose UI Host"),"endpoint":.s("ws://127.0.0.1:\(port)"),"pid":.n(Int(ProcessInfo.processInfo.processIdentifier)),"started_at":.s(timestamp())])
        let temp=directory.appendingPathComponent("."+UUID().uuidString)
        try value.data().write(to:temp,options:.withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:temp.path)
        try FileManager.default.moveItem(at:temp,to:url)
        record=url
    }
    public func remove() {if let record {try? FileManager.default.removeItem(at:record);self.record=nil}}
    deinit {remove()}
}
