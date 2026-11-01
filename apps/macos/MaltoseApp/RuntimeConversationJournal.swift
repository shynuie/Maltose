import Foundation

/// Durable UI transcript mirror. The Agent's reasoning/session state remains in its runtime.
@MainActor final class RuntimeConversationJournal {
    private let url: URL
    private var writer: FileHandle?

    init(url: URL) { self.url = url }

    func open(replay: (Data) throws -> Void) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let reader = try FileHandle(forReadingFrom: url)
        defer { try? reader.close() }
        var buffer = Data(), completeBytes: UInt64 = 0
        while let chunk = try reader.read(upToCount: 64 * 1024), !chunk.isEmpty {
            buffer.append(chunk)
            while let end = buffer.firstIndex(of: 10) {
                let line = buffer.subdata(in: buffer.startIndex..<end)
                if !line.isEmpty { try replay(line) }
                completeBytes += UInt64(buffer.distance(from: buffer.startIndex, to: end) + 1)
                buffer.removeSubrange(buffer.startIndex...end)
            }
            guard buffer.count <= 8 * 1024 * 1024 else { throw RuntimeLaunchError.unavailable("對話紀錄超出單筆大小限制。") }
        }
        if !buffer.isEmpty {
            // A crash can interrupt the final write. Preserve evidence before repairing only that tail.
            let recovery = url.appendingPathExtension("interrupted-\(UUID().uuidString)")
            try FileManager.default.copyItem(at: url, to: recovery)
            let repair = try FileHandle(forWritingTo: url)
            defer { try? repair.close() }
            try repair.truncate(atOffset: completeBytes)
        }
        writer = try FileHandle(forWritingTo: url)
        try writer?.seekToEnd()
    }

    func append(_ data: Data, durable: Bool = false) throws {
        guard let writer else { throw RuntimeLaunchError.unavailable("對話紀錄尚未開啟。") }
        var line = data; line.append(10)
        try writer.write(contentsOf: line)
        if durable { try writer.synchronize() }
    }

    func close() { try? writer?.synchronize(); try? writer?.close(); writer = nil }
}
