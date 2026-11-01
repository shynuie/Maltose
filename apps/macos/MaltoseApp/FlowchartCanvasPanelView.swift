import AppKit
import SwiftUI
import UniformTypeIdentifiers
import CryptoKit

struct FlowchartPoint: Codable, Equatable {
    var x: CGFloat
    var y: CGFloat
}

enum FlowchartNodeType: String, CaseIterable, Codable {
    case start, process, decision, end, note

    var title: String {
        switch self {
        case .start: "開始"
        case .process: "步驟"
        case .decision: "判斷"
        case .end: "結束"
        case .note: "註記"
        }
    }

    var symbol: String {
        switch self {
        case .start: "play.circle"
        case .process: "rectangle"
        case .decision: "diamond"
        case .end: "stop.circle"
        case .note: "text.alignleft"
        }
    }

    var size: CGSize {
        switch self {
        case .start, .end: CGSize(width: 142, height: 64)
        case .process: CGSize(width: 192, height: 82)
        case .decision: CGSize(width: 152, height: 112)
        case .note: CGSize(width: 190, height: 94)
        }
    }
}

struct FlowchartNode: Identifiable, Codable, Equatable {
    let id: String
    var type: FlowchartNodeType
    var text: String
    var position: FlowchartPoint
}

struct FlowchartConnection: Identifiable, Codable, Equatable {
    let id: String
    var fromNodeID: String
    var toNodeID: String
    var label: String?
}

struct FlowchartDocument: Codable, Equatable {
    var nodes: [FlowchartNode]
    var connections: [FlowchartConnection]
}

struct FlowchartFile: Codable, Equatable {
    static let currentVersion = 1
    var format = "MaltoseFlowchart"
    var version = currentVersion
    var title: String
    var document: FlowchartDocument
}

enum FlowchartFileError: LocalizedError {
    case unsupportedFormat
    case unsupportedVersion(Int)
    case invalidDocument(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedFormat: "這不是 Maltose 流程圖文件。"
        case let .unsupportedVersion(version): "此流程圖使用不支援的文件版本（\(version)）。"
        case let .invalidDocument(reason): "流程圖內容無法讀取：\(reason)"
        }
    }
}

@MainActor final class FlowchartCanvasModel: ObservableObject {
    @Published private(set) var nodes: [FlowchartNode]
    @Published private(set) var connections: [FlowchartConnection]
    @Published private(set) var selectedNodeIDs: Set<String> = []
    @Published private(set) var zoom: CGFloat = 0.72
    @Published private(set) var panOffset = CGSize.zero
    @Published private(set) var isConnecting = false
    @Published private(set) var connectionStartID: String?
    @Published private(set) var documentTitle: String
    @Published private(set) var isDirty: Bool
    private(set) var fileURL: URL?
    private(set) var documentIdentity = UUID().uuidString
    private(set) var lastSavedSHA256: String?

    var document: FlowchartDocument { FlowchartDocument(nodes: nodes, connections: connections) }

    init(document: FlowchartDocument? = nil) {
        let initial = document ?? Self.sampleDocument
        nodes = initial.nodes
        connections = initial.connections
        documentTitle = document == nil ? "需求處理流程" : "未命名流程"
        isDirty = document == nil
    }

    func addNode(_ type: FlowchartNodeType, at position: FlowchartPoint? = nil) -> String {
        let index = nodes.count
        let node = FlowchartNode(id: UUID().uuidString,
                                 type: type,
                                 text: type == .process ? "新的步驟" : type.title,
                                 position: position ?? FlowchartPoint(x: CGFloat(index % 3 - 1) * 230,
                                                                      y: CGFloat(index / 3) * 140 - 70))
        nodes.append(node)
        selectedNodeIDs = [node.id]
        isDirty = true
        return node.id
    }

    func updateText(_ text: String, for id: String) {
        guard let index = nodes.firstIndex(where: { $0.id == id }) else { return }
        guard nodes[index].text != text else { return }
        nodes[index].text = text
        isDirty = true
    }

    func setPosition(_ position: FlowchartPoint, for id: String) {
        guard let index = nodes.firstIndex(where: { $0.id == id }) else { return }
        guard nodes[index].position != position else { return }
        nodes[index].position = position
        isDirty = true
    }

    func moveNodes(_ ids: Set<String>, by delta: CGSize) {
        for index in nodes.indices where ids.contains(nodes[index].id) {
            nodes[index].position.x += delta.width
            nodes[index].position.y += delta.height
        }
        if !ids.isEmpty { isDirty = true }
    }

    func selectNode(_ id: String, extending: Bool = false) {
        guard nodes.contains(where: { $0.id == id }) else { return }
        if extending {
            if selectedNodeIDs.contains(id) { selectedNodeIDs.remove(id) }
            else { selectedNodeIDs.insert(id) }
        } else {
            selectedNodeIDs = [id]
        }
    }

    func clearSelection() { selectedNodeIDs.removeAll() }

    func toggleConnectionMode() {
        isConnecting.toggle()
        connectionStartID = nil
    }

    func chooseConnectionNode(_ id: String) {
        guard isConnecting else { selectNode(id); return }
        guard let sourceID = connectionStartID else {
            connectionStartID = id
            selectNode(id)
            return
        }
        if sourceID != id { _ = connect(from: sourceID, to: id) }
        connectionStartID = nil
    }

    @discardableResult func connect(from sourceID: String, to targetID: String, label: String? = nil) -> Bool {
        guard sourceID != targetID,
              nodes.contains(where: { $0.id == sourceID }),
              nodes.contains(where: { $0.id == targetID }),
              !connections.contains(where: { $0.fromNodeID == sourceID && $0.toNodeID == targetID }) else { return false }
        connections.append(FlowchartConnection(id: UUID().uuidString,
                                               fromNodeID: sourceID,
                                               toNodeID: targetID,
                                               label: label))
        isDirty = true
        return true
    }

    func deleteSelection() {
        let removed = selectedNodeIDs
        guard !removed.isEmpty else { return }
        nodes.removeAll { removed.contains($0.id) }
        connections.removeAll { removed.contains($0.fromNodeID) || removed.contains($0.toNodeID) }
        selectedNodeIDs.removeAll()
        isDirty = true
        if let connectionStartID, removed.contains(connectionStartID) { self.connectionStartID = nil }
    }

    func pan(by delta: CGSize) {
        panOffset = CGSize(width: panOffset.width + delta.width, height: panOffset.height + delta.height)
    }

    func setPanOffset(_ offset: CGSize) { panOffset = offset }

    func setZoom(_ value: CGFloat) { zoom = min(2.5, max(0.35, value)) }

    func resetViewport() {
        zoom = 0.72
        panOffset = .zero
    }

    func newDocument() {
        documentIdentity = UUID().uuidString
        lastSavedSHA256 = nil
        nodes = []
        connections = []
        selectedNodeIDs = []
        isConnecting = false
        connectionStartID = nil
        documentTitle = "未命名流程"
        fileURL = nil
        isDirty = false
        resetViewport()
    }

    func encodedFile(for url: URL) throws -> Data {
        let file = FlowchartFile(title: Self.displayTitle(for: url), document: document)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(file)
    }

    func documentFingerprint() throws -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        return SHA256.hash(data: try encoder.encode(document)).map { String(format: "%02x", $0) }.joined()
    }

    func save(to url: URL) throws {
        let data = try encodedFile(for: url)
        try data.write(to: url, options: .atomic)
        fileURL = url; documentTitle = Self.displayTitle(for: url); isDirty = false
        documentIdentity = UUID().uuidString
        lastSavedSHA256 = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    @discardableResult func acknowledgeSave(to url: URL, documentID: String, fingerprint: String, fileSHA256: String) throws -> Bool {
        guard documentIdentity == documentID else { return false }
        isDirty = try documentFingerprint() != fingerprint
        fileURL = url; documentTitle = Self.displayTitle(for: url); lastSavedSHA256 = fileSHA256
        return true
    }

    func load(from url: URL) throws { try loadFileData(Data(contentsOf: url), sourceURL: url) }

    func loadFileData(_ data: Data, sourceURL url: URL) throws {
        let file = try JSONDecoder().decode(FlowchartFile.self, from: data)
        guard file.format == "MaltoseFlowchart" else { throw FlowchartFileError.unsupportedFormat }
        guard file.version == FlowchartFile.currentVersion else {
            throw FlowchartFileError.unsupportedVersion(file.version)
        }
        try Self.validate(file.document)
        documentIdentity = UUID().uuidString
        lastSavedSHA256 = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        nodes = file.document.nodes
        connections = file.document.connections
        selectedNodeIDs = []
        isConnecting = false
        connectionStartID = nil
        documentTitle = file.title.isEmpty ? Self.displayTitle(for: url) : file.title
        fileURL = url
        isDirty = false
        resetViewport()
    }

    private static func validate(_ document: FlowchartDocument) throws {
        let nodeIDs = document.nodes.map(\.id)
        guard Set(nodeIDs).count == nodeIDs.count else {
            throw FlowchartFileError.invalidDocument("節點識別碼重複")
        }
        guard document.nodes.allSatisfy({ $0.position.x.isFinite && $0.position.y.isFinite }) else {
            throw FlowchartFileError.invalidDocument("節點位置不是有效數值")
        }
        let nodeIDSet = Set(nodeIDs)
        let edgeKeys = document.connections.map { "\($0.fromNodeID)→\($0.toNodeID)" }
        guard Set(edgeKeys).count == edgeKeys.count else {
            throw FlowchartFileError.invalidDocument("連線重複")
        }
        guard document.connections.allSatisfy({ nodeIDSet.contains($0.fromNodeID) && nodeIDSet.contains($0.toNodeID) && $0.fromNodeID != $0.toNodeID }) else {
            throw FlowchartFileError.invalidDocument("連線指向不存在或相同的節點")
        }
    }

    private static func displayTitle(for url: URL) -> String {
        url.deletingPathExtension().deletingPathExtension().lastPathComponent
    }

    private static let sampleDocument: FlowchartDocument = {
        let nodes = [
            FlowchartNode(id: "flow-start", type: .start, text: "開始", position: FlowchartPoint(x: -420, y: 0)),
            FlowchartNode(id: "flow-receive", type: .process, text: "接收使用者需求", position: FlowchartPoint(x: -205, y: 0)),
            FlowchartNode(id: "flow-enough", type: .decision, text: "資訊足夠？", position: FlowchartPoint(x: 40, y: 0)),
            FlowchartNode(id: "flow-clarify", type: .process, text: "詢問並補充資訊", position: FlowchartPoint(x: 290, y: 142)),
            FlowchartNode(id: "flow-action", type: .process, text: "執行並回報結果", position: FlowchartPoint(x: 290, y: -142)),
            FlowchartNode(id: "flow-end", type: .end, text: "完成", position: FlowchartPoint(x: 540, y: -142))
        ]
        let connections = [
            FlowchartConnection(id: "edge-1", fromNodeID: "flow-start", toNodeID: "flow-receive", label: nil),
            FlowchartConnection(id: "edge-2", fromNodeID: "flow-receive", toNodeID: "flow-enough", label: nil),
            FlowchartConnection(id: "edge-3", fromNodeID: "flow-enough", toNodeID: "flow-clarify", label: "否"),
            FlowchartConnection(id: "edge-4", fromNodeID: "flow-clarify", toNodeID: "flow-enough", label: nil),
            FlowchartConnection(id: "edge-5", fromNodeID: "flow-enough", toNodeID: "flow-action", label: "是"),
            FlowchartConnection(id: "edge-6", fromNodeID: "flow-action", toNodeID: "flow-end", label: nil)
        ]
        return FlowchartDocument(nodes: nodes, connections: connections)
    }()
}

struct FlowchartCanvasPanelView: View {
    @ObservedObject var model: FlowchartCanvasModel
    @State private var canvasDragStart = CGSize.zero
    @State private var nodeDragOrigins: [String: FlowchartPoint] = [:]
    @State private var previousMagnification: CGFloat = 1

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            GeometryReader { geometry in
                ZStack {
                    Canvas { context, size in
                        var dots = Path()
                        stride(from: 12.0, through: size.width, by: 30.0).forEach { x in
                            stride(from: 12.0, through: size.height, by: 30.0).forEach { y in
                                dots.addEllipse(in: CGRect(x: x, y: y, width: 1.5, height: 1.5))
                            }
                        }
                        context.fill(dots, with: .color(.white.opacity(0.15)))
                    }
                    .allowsHitTesting(false)

                    connectionLayer(in: geometry.size)
                        .allowsHitTesting(false)

                    ForEach(model.nodes) { node in
                        nodeCard(node)
                            .frame(width: node.type.size.width, height: node.type.size.height)
                            .scaleEffect(model.zoom)
                            .position(screenPosition(for: node.position, in: geometry.size))
                            .zIndex(model.selectedNodeIDs.contains(node.id) ? 2 : 1)
                            .gesture(nodeDragGesture(for: node))
                    }

                    if model.nodes.isEmpty {
                        Text("新增節點，開始整理流程")
                            .font(.system(size: 16, weight: .medium))
                            .foregroundStyle(.white.opacity(0.48))
                            .allowsHitTesting(false)
                    }

                    Rectangle().fill(.clear).contentShape(Rectangle())
                        .gesture(canvasPanGesture)
                        .simultaneousGesture(canvasMagnificationGesture)
                        .onTapGesture { model.clearSelection() }
                        .accessibilityHidden(true)
                        .zIndex(-1)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipped()
                .background(Color.clear)
            }
        }
        .foregroundStyle(.white.opacity(0.9))
        .background(Color.clear)
        .accessibilityIdentifier("flowchart-canvas-panel")
    }

    private var toolbar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 7) {
                HStack(spacing: 5) {
                    Text(model.documentTitle).lineLimit(1)
                    if model.isDirty {
                        Circle().fill(.orange).frame(width: 6, height: 6).help("有尚未儲存的變更")
                    }
                }
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.white.opacity(0.76))
                .frame(maxWidth: 150)
                fileButton("新增", systemImage: "plus", help: "建立空白流程", action: createDocument)
                fileButton("開啟", systemImage: "folder", help: "開啟流程文件", action: openDocument)
                fileButton("儲存", systemImage: "square.and.arrow.down", help: "儲存流程", action: saveDocument)
                fileButton("另存", systemImage: "doc.on.doc", help: "另存為新流程文件", action: saveDocumentAs)
                Button(action: deleteDocument) { Image(systemName: "trash") }
                    .buttonStyle(CanvasToolButtonStyle())
                    .disabled(model.fileURL == nil)
                    .help("將目前流程文件移到垃圾桶")
                Divider().frame(height: 22).overlay(.white.opacity(0.18))
                addButton(.start)
                addButton(.process)
                addButton(.decision)
                addButton(.end)
                addButton(.note)
                Divider().frame(height: 22).overlay(.white.opacity(0.18))
                Button { model.toggleConnectionMode() } label: {
                    Label(model.isConnecting ? "選擇終點" : "連線", systemImage: model.isConnecting ? "arrow.triangle.branch" : "arrow.right")
                }
                .buttonStyle(CanvasToolButtonStyle(active: model.isConnecting))
                .accessibilityLabel(model.isConnecting ? "連線模式" : "新增連線")
                Button { model.deleteSelection() } label: { Image(systemName: "trash") }
                    .buttonStyle(CanvasToolButtonStyle())
                    .disabled(model.selectedNodeIDs.isEmpty)
                    .help("刪除選取節點")
                Divider().frame(height: 22).overlay(.white.opacity(0.18))
                Button { model.setZoom(model.zoom / 1.15) } label: { Image(systemName: "minus.magnifyingglass") }
                    .buttonStyle(CanvasToolButtonStyle()).help("縮小畫布")
                Text("\(Int(model.zoom * 100))%")
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.55)).frame(minWidth: 38)
                Button { model.setZoom(model.zoom * 1.15) } label: { Image(systemName: "plus.magnifyingglass") }
                    .buttonStyle(CanvasToolButtonStyle()).help("放大畫布")
                Button { model.resetViewport() } label: { Image(systemName: "viewfinder") }
                    .buttonStyle(CanvasToolButtonStyle()).help("重設視野")
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
        }
        .background(.black.opacity(0.28))
    }

    private func addButton(_ type: FlowchartNodeType) -> some View {
        Button { _ = model.addNode(type) } label: { Label(type.title, systemImage: type.symbol) }
            .buttonStyle(CanvasToolButtonStyle())
            .accessibilityLabel("新增\(type.title)節點")
    }

    private func fileButton(_ title: String, systemImage: String, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Label(title, systemImage: systemImage) }
            .buttonStyle(CanvasToolButtonStyle())
            .help(help)
    }

    private func createDocument() {
        guard resolveUnsavedChanges() else { return }
        model.newDocument()
    }

    private func openDocument() {
        guard resolveUnsavedChanges() else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.prompt = "開啟"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try model.load(from: url)
        } catch {
            showFileError(error)
        }
    }

    private func saveDocument() {
        guard let url = model.fileURL else { saveDocumentAs(); return }
        do {
            try model.save(to: url)
        } catch {
            showFileError(error)
        }
    }

    private func saveDocumentAs() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = "\(model.documentTitle).maltoseflow.json"
        panel.isExtensionHidden = false
        panel.canCreateDirectories = true
        panel.prompt = "儲存"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try model.save(to: url)
        } catch {
            showFileError(error)
        }
    }

    private func deleteDocument() {
        guard let url = model.fileURL else { return }
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "要刪除「\(model.documentTitle)」嗎？"
        alert.informativeText = model.isDirty ? "文件會移到垃圾桶，尚未儲存的修改也會捨棄。" : "文件會移到垃圾桶。"
        alert.addButton(withTitle: "移到垃圾桶")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        do {
            try FileManager.default.trashItem(at: url, resultingItemURL: nil)
            model.newDocument()
        } catch {
            showFileError(error)
        }
    }

    private func resolveUnsavedChanges() -> Bool {
        guard model.isDirty else { return true }
        let alert = NSAlert()
        alert.messageText = "要先儲存「\(model.documentTitle)」的變更嗎？"
        alert.informativeText = "尚未儲存的節點與連線可能會遺失。"
        alert.addButton(withTitle: "儲存")
        alert.addButton(withTitle: "不儲存")
        alert.addButton(withTitle: "取消")
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            saveDocument()
            return !model.isDirty
        case .alertSecondButtonReturn:
            return true
        default:
            return false
        }
    }

    private func showFileError(_ error: Error) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "流程文件操作失敗"
        alert.informativeText = error.localizedDescription
        alert.addButton(withTitle: "好")
        alert.runModal()
    }

    private func nodeCard(_ node: FlowchartNode) -> some View {
        let selected = model.selectedNodeIDs.contains(node.id)
        let connectingFrom = model.connectionStartID == node.id
        return ZStack {
            nodeShape(node.type)
                .fill(node.type == .note ? Color(red: 0.20, green: 0.21, blue: 0.23).opacity(0.96) : Color(red: 0.08, green: 0.12, blue: 0.15).opacity(0.96))
            nodeShape(node.type)
                .stroke(selected || connectingFrom ? Color.cyan.opacity(0.9) : Color.white.opacity(0.20), lineWidth: selected || connectingFrom ? 2 : 1)
            TextField("節點文字", text: Binding(get: { node.text }, set: { model.updateText($0, for: node.id) }))
                .font(.system(size: node.type == .start || node.type == .end ? 13 : 12, weight: .medium))
                .multilineTextAlignment(.center)
                .textFieldStyle(.plain)
                .lineLimit(2)
                .padding(.horizontal, node.type == .decision ? 26 : 14)
                .padding(.vertical, 8)
                .accessibilityLabel("\(node.type.title)節點文字")
        }
        .contentShape(nodeShape(node.type))
        .onTapGesture {
            if model.isConnecting { model.chooseConnectionNode(node.id) }
            else { model.selectNode(node.id, extending: NSEvent.modifierFlags.contains(.command)) }
        }
        .help(model.isConnecting ? "選取此節點作為連線端點" : "點選選取，Command 點選可多選；拖曳移動")
    }

    private func nodeShape(_ type: FlowchartNodeType) -> AnyShape {
        switch type {
        case .start, .end: AnyShape(Capsule())
        case .process: AnyShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        case .decision: AnyShape(DiamondShape())
        case .note: AnyShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
        }
    }

    private func connectionLayer(in size: CGSize) -> some View {
        Canvas { context, _ in
            for edge in model.connections {
                guard let source = model.nodes.first(where: { $0.id == edge.fromNodeID }),
                      let target = model.nodes.first(where: { $0.id == edge.toNodeID }) else { continue }
                let sourcePoint = screenPosition(for: source.position, in: size)
                let targetPoint = screenPosition(for: target.position, in: size)
                let sourceRight = targetPoint.x >= sourcePoint.x
                let from = CGPoint(x: sourcePoint.x + (sourceRight ? source.type.size.width : -source.type.size.width) * model.zoom / 2,
                                   y: sourcePoint.y)
                let to = CGPoint(x: targetPoint.x + (sourceRight ? -target.type.size.width : target.type.size.width) * model.zoom / 2,
                                 y: targetPoint.y)
                let bend = max(36, abs(to.x - from.x) * 0.45)
                var path = Path()
                path.move(to: from)
                path.addCurve(to: to,
                              control1: CGPoint(x: from.x + (sourceRight ? bend : -bend), y: from.y),
                              control2: CGPoint(x: to.x - (sourceRight ? bend : -bend), y: to.y))
                context.stroke(path, with: .color(.cyan.opacity(0.78)), style: StrokeStyle(lineWidth: 2, lineCap: .round))

                let angle = atan2(to.y - (sourcePoint.y + targetPoint.y) / 2, to.x - (sourcePoint.x + targetPoint.x) / 2)
                let arrow = CGPoint(x: to.x - cos(angle) * 8, y: to.y - sin(angle) * 8)
                var arrowPath = Path()
                arrowPath.move(to: to)
                arrowPath.addLine(to: CGPoint(x: arrow.x - cos(angle - .pi / 5) * 9, y: arrow.y - sin(angle - .pi / 5) * 9))
                arrowPath.addLine(to: CGPoint(x: arrow.x - cos(angle + .pi / 5) * 9, y: arrow.y - sin(angle + .pi / 5) * 9))
                arrowPath.closeSubpath()
                context.fill(arrowPath, with: .color(.cyan.opacity(0.9)))

                if let label = edge.label, !label.isEmpty {
                    let text = Text(label).font(.system(size: 11, weight: .semibold)).foregroundColor(.cyan)
                    let resolved = context.resolve(text)
                    let labelPoint = CGPoint(x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 10)
                    context.draw(resolved, at: labelPoint)
                }
            }
        }
    }

    private func screenPosition(for point: FlowchartPoint, in size: CGSize) -> CGPoint {
        CGPoint(x: size.width / 2 + model.panOffset.width + point.x * model.zoom,
                y: size.height / 2 + model.panOffset.height + point.y * model.zoom)
    }

    private var canvasPanGesture: some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { value in
                model.setPanOffset(CGSize(width: canvasDragStart.width + value.translation.width,
                                          height: canvasDragStart.height + value.translation.height))
            }
            .onEnded { _ in canvasDragStart = model.panOffset }
    }

    private var canvasMagnificationGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                if previousMagnification == 1 { previousMagnification = value.magnification }
                else {
                    model.setZoom(model.zoom * value.magnification / previousMagnification)
                    previousMagnification = value.magnification
                }
            }
            .onEnded { _ in previousMagnification = 1 }
    }

    private func nodeDragGesture(for node: FlowchartNode) -> some Gesture {
        DragGesture(minimumDistance: 3)
            .onChanged { value in
                if nodeDragOrigins.isEmpty {
                    if !model.selectedNodeIDs.contains(node.id) { model.selectNode(node.id) }
                    nodeDragOrigins = Dictionary(uniqueKeysWithValues: model.nodes
                        .filter { model.selectedNodeIDs.contains($0.id) }
                        .map { ($0.id, $0.position) })
                }
                for (id, origin) in nodeDragOrigins {
                    model.setPosition(FlowchartPoint(x: origin.x + value.translation.width / model.zoom,
                                                     y: origin.y + value.translation.height / model.zoom), for: id)
                }
            }
            .onEnded { _ in nodeDragOrigins.removeAll() }
    }
}

private struct DiamondShape: Shape {
    func path(in rect: CGRect) -> Path {
        Path { path in
            path.move(to: CGPoint(x: rect.midX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            path.addLine(to: CGPoint(x: rect.midX, y: rect.maxY))
            path.addLine(to: CGPoint(x: rect.minX, y: rect.midY))
            path.closeSubpath()
        }
    }
}

private struct CanvasToolButtonStyle: ButtonStyle {
    var active = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(.white.opacity(configuration.isPressed ? 0.5 : 0.86))
            .padding(.horizontal, 9).padding(.vertical, 7)
            .background(active ? Color.cyan.opacity(0.18) : .white.opacity(0.055), in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(active ? .cyan.opacity(0.4) : .white.opacity(0.08), lineWidth: 1))
    }
}
