import AppKit
import Darwin

/// Workspace presentation only; task, conversation and delivered-result records
/// keep their existing writers. This file never authorizes filesystem operations.
struct WorkspaceSession: Codable {
    var schemaVersion = 1
    var panels: [Panel]
    var layouts: [String: WorkspaceLayoutState] = [:]
    var gridZooms: [String: Double]? = nil
    struct Panel: Codable {
        var descriptor: WorkspacePanel
        var screenID: String?
        var note: String?
    }
    func validated() throws -> Self {
        guard schemaVersion == 1, panels.count <= 1024, Set(panels.map { $0.descriptor.id }).count == panels.count,
              layouts.count <= 32 else { throw WorkspaceSessionError.invalid }
        if let gridZooms {
            guard gridZooms.count <= 32, gridZooms.values.allSatisfy({ $0.isFinite && (0...1).contains($0) }) else { throw WorkspaceSessionError.invalid }
        }
        for row in panels {
            let p = row.descriptor
            guard !p.id.isEmpty, p.id.utf8.count <= 256, p.title.utf8.count <= 2000,
                  p.kind != .agentCoreTest, (p.initialBrowserAddress?.utf8.count ?? 0) <= 8192,
                  (row.note?.utf8.count ?? 0) <= 4 * 1024 * 1024,
                  (row.screenID?.utf8.count ?? 0) <= 256 else { throw WorkspaceSessionError.invalid }
            if !p.kind.allowsMultipleInstances {
                guard panels.filter({ $0.descriptor.kind == p.kind }).count == 1 else { throw WorkspaceSessionError.invalid }
            }
            if p.kind == .agentIdentity, p.id != "agent-identity" { throw WorkspaceSessionError.invalid }
            if p.kind == .conversationHistory, p.id != "chat" { throw WorkspaceSessionError.invalid }
            if p.id == "agent-identity", p.kind != .agentIdentity { throw WorkspaceSessionError.invalid }
            if p.id == "chat", p.kind != .conversationHistory { throw WorkspaceSessionError.invalid }
        }
        for (id, layout) in layouts {
            guard id.utf8.count <= 256, layout.panelIDs.count <= 1024, layout.selectedIDs.count <= 1024,
                  (0...10000).contains(layout.identityPosition.row), (0...10000).contains(layout.identityPosition.column) else { throw WorkspaceSessionError.invalid }
            if let positions = layout.panelPositions {
                guard positions.count <= 1024, positions.values.allSatisfy({ (0...10000).contains($0.row) && (0...10000).contains($0.column) }) else { throw WorkspaceSessionError.invalid }
            }
        }
        var normalized = self
        for panel in WorkspacePanel.required.reversed() where !normalized.panels.contains(where: { $0.descriptor.kind == panel.kind }) {
            normalized.panels.insert(.init(descriptor: panel), at: 0)
        }
        return normalized
    }
}

enum WorkspaceSessionError: Error, LocalizedError {
    case invalid
    var errorDescription: String? { "工作區紀錄無法讀取或保存；原紀錄已保留。" }
}

final class WorkspaceSessionStore {
    let url: URL
    init(url: URL) { self.url = url }
    func load() throws -> WorkspaceSession? {
        let fd = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        if fd < 0 { if errno == ENOENT { return nil }; throw WorkspaceSessionError.invalid }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(),
              info.st_mode & 0o077 == 0, info.st_nlink == 1, info.st_size <= 64 * 1024 * 1024 else { throw WorkspaceSessionError.invalid }
        return try JSONDecoder().decode(WorkspaceSession.self, from: handle.readToEnd() ?? Data()).validated()
    }
    func save(_ session: WorkspaceSession) throws {
        let validated = try session.validated()
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(validated)
        guard data.count <= 64 * 1024 * 1024 else { throw WorkspaceSessionError.invalid }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        if FileManager.default.fileExists(atPath: url.path) {
            _ = try load() // Preserve an unreadable/corrupt existing file.
            if (try? Data(contentsOf: url)) == data { return }
        }
        let temporary = url.deletingLastPathComponent().appendingPathComponent(".workspace-\(UUID()).tmp")
        let fd = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw WorkspaceSessionError.invalid }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close(); try? FileManager.default.removeItem(at: temporary) }
        try handle.write(contentsOf: data); try handle.synchronize(); try handle.close()
        guard Darwin.rename(temporary.path, url.path) == 0 else { throw WorkspaceSessionError.invalid }
    }
}

extension WorkspaceWindowManager {
    func applyInitialLayout() {
        for root in roots.values { root.applyInitialGrid() }
    }
    func restoreSession(_ session: WorkspaceSession?, store: WorkspaceSessionStore) {
        for row in session?.panels ?? [] { if let id = row.screenID { assignmentsForSession(row.descriptor.id, screenID: id) } }
        synchronize()
        if session == nil { applyInitialLayout() }
        for row in session?.panels ?? [] {
            if let note = row.note { panels[row.descriptor.id]?.sampleContentModel?.note = note }
        }
        for (screenID, state) in session?.layouts ?? [:] {
            guard let root = roots[screenID] else { continue }
            var next = state
            next.reconcile(catalog.filter { assignments[$0.id] == screenID }.map(\.id))
            if next.mode != .grid, catalog.first(where: { $0.id == next.primaryID })?.supportsFocusedMode == false { next.mode = .grid }
            root.state = next; root.arrange(animated: false)
            if let zoom = session?.gridZooms?[screenID] { root.setGlobalZoom(CGFloat(zoom)) }
        }
        sessionStore = store
        saveSessionIfEnabled()
    }
    func saveSessionIfEnabled() {
        guard let sessionStore, !isAgentInteractionTestRunning else { return }
        let rows = catalog.filter { $0.kind != .agentCoreTest }.map { panel in
            var descriptor = panel
            if let address = panels[panel.id]?.browserModel?.currentURL?.absoluteString {
                descriptor = .init(id: panel.id, title: panel.title, kind: panel.kind, initialBrowserAddress: address)
            }
            return WorkspaceSession.Panel(descriptor: descriptor, screenID: assignments[panel.id], note: panels[panel.id]?.sampleContentModel?.note)
        }
        let snapshot = WorkspaceSession(panels: rows, layouts: roots.mapValues(\.state), gridZooms: roots.mapValues(\.savedGridZoom))
        do { try sessionStore.save(snapshot) }
        catch { workMonitor.append(engine: "Maltose", text: "工作區尚未保存，重新啟動時可能無法恢復本次面板變更。", failed: true) }
    }
}
