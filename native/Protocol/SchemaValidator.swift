import Foundation
/// Deliberately implements only the vocabulary used by our checked-in 2020-12 schemas.
/// CI rejects unsupported schema keywords instead of silently ignoring them.
public struct SchemaValidator: Sendable {
    public let root: JSON
    public init(name: String) throws {
        let resources=Bundle.main.resourceURL.flatMap { Bundle(url:$0.appendingPathComponent("MaltoseUIHost_MaltoseCore.bundle")) } ?? Bundle.module
        guard let url = resources.url(forResource: name + ".schema", withExtension: "json", subdirectory: "Schemas") else { throw MUPError("internal", "Missing protocol schema") }
        root = try JSON.decode(Data(contentsOf: url))
    }
    public func validate(_ value: JSON) throws { try check(value, root, depth: 0) }
    public static func command(_ data: Data) throws -> JSON {
        guard data.count <= 1_048_576 else { throw MUPError("message_too_large", "Maximum message is 1 MiB") }
        let value: JSON
        do { value = try JSON.decode(data) } catch { throw MUPError("invalid_message", "Malformed JSON") }
        guard value["protocol"].string == MUP.version else { throw MUPError("unsupported_protocol", "Expected mup/0.3") }
        try SchemaValidator(name: "command").validate(value)
        return value
    }
    private func check(_ v: JSON, _ s: JSON, depth: Int) throws {
        guard depth < 96 else { throw MUPError("invalid_message", "Maximum nesting exceeded") }
        func fail() throws -> Never { throw MUPError("invalid_message", "Message does not conform to MUP schema") }
        if let ref = s["$ref"].string {
            guard ref.hasPrefix("#/$defs/"), let target = root["$defs"].object?[String(ref.dropFirst(8))] else { throw MUPError("internal", "Unsupported schema reference") }
            try check(v, target, depth: depth + 1)
        }
        if let type = s["type"].string {
            let matches: Bool
            switch type { case "object": matches = v.object != nil; case "array": matches = v.array != nil; case "string": matches = v.string != nil; case "number": matches = v.number != nil; case "integer": matches = v.number.map { $0.rounded() == $0 } ?? false; case "boolean": matches = v.bool != nil; case "null": matches = v == .null; default: throw MUPError("internal", "Unsupported schema type") }
            if !matches { try fail() }
        }
        if let c = s.object?["const"], v != c { try fail() }
        if let e = s["enum"].array, !e.contains(v) { try fail() }
        if let str = v.string {
            if let m = s["minLength"].int, str.count < m { try fail() }
            if let m = s["maxLength"].int, str.count > m { try fail() }
            if let p = s["pattern"].string, str.range(of: p, options: .regularExpression) == nil { try fail() }
            if s["format"].string == "uuid", UUID(uuidString: str) == nil { try fail() }
            if s["format"].string == "date-time", ISO8601DateFormatter().date(from: str) == nil { try fail() }
        }
        if let n = v.number {
            if let min = s["minimum"].number, n < min { try fail() }
            if let max = s["maximum"].number, n > max { try fail() }
        }
        if let o = v.object {
            for key in s["required"].array ?? [] { if o[key.string ?? ""] == nil { try fail() } }
            let props = s["properties"].object ?? [:]
            if s["additionalProperties"].bool == false, !Set(o.keys).isSubset(of: Set(props.keys)) { try fail() }
            for (key, val) in o { if let schema = props[key] { try check(val, schema, depth: depth + 1) } }
        }
        if let a = v.array {
            if let min = s["minItems"].int, a.count < min { try fail() }
            if let max = s["maxItems"].int, a.count > max { try fail() }
            if let items = s.object?["items"] { for item in a { try check(item, items, depth: depth + 1) } }
        }
        for item in s["allOf"].array ?? [] { try check(v, item, depth: depth + 1) }
        if let any = s["anyOf"].array, !any.contains(where: { (try? check(v, $0, depth: depth + 1)) != nil }) { try fail() }
        if let one = s["oneOf"].array, one.filter({ (try? check(v, $0, depth: depth + 1)) != nil }).count != 1 { try fail() }
        if let not = s.object?["not"], (try? check(v, not, depth: depth + 1)) != nil { try fail() }
        if let condition = s.object?["if"], (try? check(v, condition, depth: depth + 1)) != nil, let then = s.object?["then"] { try check(v, then, depth: depth + 1) }
    }
}
