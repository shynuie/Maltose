import Foundation
public struct ToolkitArtifact:Sendable {
    let manifest:JSON
    let signature:String
    let wheel:Data
    public init(directory:URL) throws {
        manifest=try JSON.decode(Data(contentsOf:directory.appendingPathComponent("manifest.json")))
        signature=try String(contentsOf:directory.appendingPathComponent("manifest.sig"),encoding:.utf8).trimmingCharacters(in:.whitespacesAndNewlines)
        guard let filename=manifest["filename"].string,filename == URL(fileURLWithPath:filename).lastPathComponent else {throw MUPError("toolkit","Invalid toolkit filename")}
        wheel=try Data(contentsOf:directory.appendingPathComponent(filename))
        guard wheel.count<600_000 else {throw MUPError("toolkit","Toolkit size limit exceeded")}
    }
    public var offer:JSON {.object(["manifest":manifest,"signature":.s(signature)])}
    public var download:JSON {.object(["manifest":manifest,"signature":.s(signature),"wheel_base64":.s(wheel.base64EncodedString())])}
}
