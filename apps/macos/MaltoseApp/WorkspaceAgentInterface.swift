import AppKit
import CryptoKit

/// Transport-independent v1 contract. Codable enums use {"case_name": {"argument": value}}.
/// All calls run on the same MainActor and model instances as native UI actions.
struct WorkspaceAgentRequest: Codable {
    var schemaVersion = 1
    var requestID: String?
    var command: WorkspaceAgentCommand
    var source: NativePanelSource?
}

enum WorkspaceAgentCommand: Codable {
    case get_user_view
    case list_capabilities
    case read_panel(panelID: String)
    case create_panel(kind: WorkspacePanel.Kind, screenID: String?)
    // Runtime-only final-result publication; not a model-facing mutable document tool.
    case publish_document(publicationID: String, title: String, markdown: String)
    case deliver_result(publicationID: String, title: String, markdown: String, createDocument: Bool, conversationID: String, messageID: String, chart: ResultChart? = nil)
    case workflow(request: ProductWorkflowRequest)
    case acknowledge_panel_operations(receipts: [NativePanelOperationReceipt])
    case close_panel(panelID: String, discardChanges: Bool)
    case select_panel(panelID: String, extending: Bool)
    case focus_panel(panelID: String)
    case toggle_panel(panelID: String)
    case set_mode(screenID: String, mode: WorkspaceMode)
    case move_panels(panelIDs: [String], screenID: String, row: Int?, column: Int?)
    case grid_viewport(screenID: String, zoom: Double, scrollOffset: Double)
    case conversation_select_session(panelID: String, sessionID: String)
    case notes_set_text(panelID: String, text: String)
    case chart_load_csv(panelID: String, csv: String, sourceName: String)
    case chart_open_csv(panelID: String, path: String)
    case chart_set_series(panelID: String, names: [String])
    case chart_set_bands(panelID: String, bands: [CSVLineChartBandRequest])
    case chart_viewport(panelID: String, zoom: Double, pan: Double)
    case image_add_url(panelID: String, url: String)
    case image_add_file(panelID: String, path: String)
    case image_select(panelID: String, index: Int)
    case image_expand(panelID: String, index: Int)
    case image_collapse(panelID: String)
    case image_viewport(panelID: String, zoom: Double, panX: Double, panY: Double)
    case browser_navigate(panelID: String, address: String)
    case browser_control(panelID: String, action: BrowserAction)
    case flowchart_add_node(panelID: String, type: FlowchartNodeType, x: Double, y: Double)
    case flowchart_update_node(panelID: String, nodeID: String, text: String, x: Double, y: Double)
    case flowchart_select_node(panelID: String, nodeID: String, extending: Bool)
    case flowchart_connect(panelID: String, from: String, to: String, label: String?)
    case flowchart_delete_selection(panelID: String)
    case flowchart_viewport(panelID: String, zoom: Double, panX: Double, panY: Double)
    case flowchart_new(panelID: String, discardChanges: Bool)
    case flowchart_open(panelID: String, path: String, discardChanges: Bool)
    case flowchart_save(panelID: String, path: String)
    case identity_set_state(panelID: String, state: EntityPreset)

    enum BrowserAction: String, Codable, CaseIterable { case back, forward, reload, stop, offlineTestPage }

    var name: String {
        switch self {
        case .get_user_view: "get_user_view"
        case .list_capabilities: "list_capabilities"
        case .read_panel: "read_panel"
        case .create_panel: "create_panel"
        case .publish_document: "publish_document"
        case .deliver_result: "deliver_result"
        case .workflow: "workflow"
        case .acknowledge_panel_operations: "acknowledge_panel_operations"
        case .close_panel: "close_panel"
        case .select_panel: "select_panel"
        case .focus_panel: "focus_panel"
        case .toggle_panel: "toggle_panel"
        case .set_mode: "set_mode"
        case .move_panels: "move_panels"
        case .grid_viewport: "grid_viewport"
        case .conversation_select_session: "conversation_select_session"
        case .notes_set_text: "notes_set_text"
        case .chart_load_csv: "chart_load_csv"
        case .chart_open_csv: "chart_open_csv"
        case .chart_set_series: "chart_set_series"
        case .chart_set_bands: "chart_set_bands"
        case .chart_viewport: "chart_viewport"
        case .image_add_url: "image_add_url"
        case .image_add_file: "image_add_file"
        case .image_select: "image_select"
        case .image_expand: "image_expand"
        case .image_collapse: "image_collapse"
        case .image_viewport: "image_viewport"
        case .browser_navigate: "browser_navigate"
        case .browser_control: "browser_control"
        case .flowchart_add_node: "flowchart_add_node"
        case .flowchart_update_node: "flowchart_update_node"
        case .flowchart_select_node: "flowchart_select_node"
        case .flowchart_connect: "flowchart_connect"
        case .flowchart_delete_selection: "flowchart_delete_selection"
        case .flowchart_viewport: "flowchart_viewport"
        case .flowchart_new: "flowchart_new"
        case .flowchart_open: "flowchart_open"
        case .flowchart_save: "flowchart_save"
        case .identity_set_state: "identity_set_state"
        }
    }

    var displayName: String {
        if case let .create_panel(kind, _) = self { return "\(name)（\(kind.defaultInstanceTitle)）" }
        return name
    }

}

struct WorkspaceAgentCapability: Codable {
    var name: String
    var panelID: String?
    var example: WorkspaceAgentRequest
}

struct WorkspaceAgentResponse: Codable {
    var schemaVersion = 1
    var requestID: String?
    var ok: Bool
    var error: WorkspaceAgentFailure?
    var result: [String: UserViewValue] = [:]
    var view: UserViewSnapshot?
    var capabilities: [WorkspaceAgentCapability]?
    var operationReceipts: [NativePanelOperationReceipt]?
}

struct WorkspaceAgentFailure: Error, Codable, LocalizedError {
    var code: String
    var message: String
    var operationID: String?
    var errorDescription: String? { message }
}

/// Private runtime transport payload; never exposed as an Agent-selectable tool.
/// FileService authorizes and performs I/O. Native models consume/export bytes only.
struct NativePanelFileTransfer: Codable {
    enum Mode: String, Codable { case load, export, saved }
    var mode: Mode
    var data: String?
    var documentID: String?
    var fingerprint: String?
    var fileSHA256: String?
}

@MainActor final class WorkspaceAgentInterface {
    private unowned let manager: WorkspaceWindowManager
    private var publications: [String: (digest: String, panelID: String)] = [:]
    lazy var panelPolicy = NativePanelPolicy(manager: manager)
    init(manager: WorkspaceWindowManager) { self.manager = manager }

    func handleAgent(_ request: WorkspaceAgentRequest, fileTransfer: NativePanelFileTransfer? = nil) async -> WorkspaceAgentResponse {
        await panelPolicy.perform(request) { preserve in
            await self.handle(request, fileTransfer: fileTransfer, requiresFileTransfer: true, preservingAgentView: preserve)
        }
    }

    func handleJSON(_ json: String) async -> String {
        let response: WorkspaceAgentResponse
        do {
            let request = try JSONDecoder().decode(WorkspaceAgentRequest.self, from: Data(json.utf8))
            response = await handle(request)
        } catch {
            response = WorkspaceAgentResponse(ok: false, error: failure("invalid_request", "指令 JSON 或參數型別不正確：\(error.localizedDescription)"))
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        do { return String(decoding: try encoder.encode(response), as: UTF8.self) }
        catch { return #"{"schemaVersion":1,"ok":false,"error":{"code":"encoding_failed","message":"無法編碼回應"}}"# }
    }

    func handle(_ request: WorkspaceAgentRequest, fileTransfer: NativePanelFileTransfer? = nil, requiresFileTransfer: Bool = false, preservingAgentView: Bool = false) async -> WorkspaceAgentResponse {
        do {
            guard request.schemaVersion == 1 else { throw failure("unsupported_version", "不支援的指令版本。") }
            let restoreView = preservingAgentView ? retainedView(for: request.command) : nil
            var didMutate = false
            defer { if didMutate { restoreView?() } }
            var response = WorkspaceAgentResponse(requestID: request.requestID, ok: true)
            if let fileTransfer {
                response.result = try transferFile(request.command, transfer: fileTransfer)
                didMutate = true
                return response
            }
            if requiresFileTransfer {
                switch request.command {
                case .chart_open_csv, .image_add_file, .flowchart_open, .flowchart_save:
                    throw failure("file_transfer_required", "Agent 檔案操作必須先通過 runtime 檔案權限檢查。")
                default: break
                }
            }
            switch request.command {
            case .get_user_view: response.view = try await manager.getUserView()
            case .list_capabilities: response.capabilities = capabilities()
            case let .read_panel(id): response.result = try await manager.readPanel(id)
            default:
                response.result = try execute(request.command)
                didMutate = true
            }
            return response
        } catch {
            return WorkspaceAgentResponse(requestID: request.requestID, ok: false,
                error: (error as? WorkspaceAgentFailure) ?? failure(error is CSVLineChartParser.ParseError && request.source != nil ? "invalid_csv" : "operation_failed", error.localizedDescription))
        }
    }

    private func retainedView(for command: WorkspaceAgentCommand) -> (() -> Void)? {
        switch command {
        case let .chart_load_csv(id, _, _), let .chart_open_csv(id, _):
            guard let model = manager.panels[id]?.chartModel else { return nil }
            let zoom = model.xZoom, pan = model.xPan
            let visible = model.visibleSeries.compactMap { model.data.seriesNames.indices.contains($0) ? model.data.seriesNames[$0] : nil }
            let bands = model.filledBands.compactMap { band, opacity -> CSVLineChartBandRequest? in
                guard model.data.seriesNames.indices.contains(band.firstSeries), model.data.seriesNames.indices.contains(band.secondSeries) else { return nil }
                return .init(firstSeriesName: model.data.seriesNames[band.firstSeries], secondSeriesName: model.data.seriesNames[band.secondSeries], opacity: opacity)
            }
            return {
                let remaining = visible.filter(model.data.seriesNames.contains)
                if !remaining.isEmpty || visible.isEmpty { model.configureAgentVisibleSeries(remaining) }
                model.configureAgentBands(bands.filter { model.data.seriesNames.contains($0.firstSeriesName) && model.data.seriesNames.contains($0.secondSeriesName) })
                model.setXAxisViewport(zoom: zoom, pan: pan)
            }
        case let .flowchart_open(id, _, _), let .flowchart_new(id, _):
            guard let model = manager.panels[id]?.flowchartModel else { return nil }
            let zoom = model.zoom, pan = model.panOffset
            return { model.setZoom(zoom); model.setPanOffset(pan) }
        default: return nil
        }
    }

    private func transferFile(_ command: WorkspaceAgentCommand, transfer: NativePanelFileTransfer) throws -> [String: UserViewValue] {
        guard transfer.mode == .export || (manager.draggingID == nil && !manager.isAgentInteractionTestRunning) else {
            throw failure("busy", "使用者正在操作面板，請稍後核對狀態。")
        }
        func contents() throws -> Data {
            guard let encoded = transfer.data, encoded.utf8.count <= 3_000_000,
                  let bytes = Data(base64Encoded: encoded), bytes.count <= 2 * 1024 * 1024 else {
                throw failure("invalid_argument", "檔案傳輸內容無效或超出大小限制。")
            }
            return bytes
        }
        switch (command, transfer.mode) {
        case let (.chart_open_csv(id, path), .load):
            let model = try panel(id, kind: .chart).chartModel!
            guard let csv = String(data: try contents(), encoding: .utf8) else { throw failure("invalid_argument", "CSV 必須使用 UTF-8。") }
            try model.loadCSV(contents: csv, sourceName: localURL(path).lastPathComponent)
        case let (.image_add_file(id, path), .load):
            try panel(id, kind: .imageGallery).imageGalleryModel!.importImageData(try contents(), title: try localURL(path).lastPathComponent)
        case let (.flowchart_open(id, path, discard), .load):
            let model = try panel(id, kind: .canvas).flowchartModel!
            try checkDirty(model, discard: discard)
            try model.loadFileData(contents(), sourceURL: flowchartURL(path))
        case let (.flowchart_save(id, path), .export):
            let model = try panel(id, kind: .canvas).flowchartModel!
            let url = try flowchartURL(path)
            let bytes = try model.encodedFile(for: url)
            guard bytes.count <= 2 * 1024 * 1024 else { throw failure("invalid_argument", "流程圖超出傳輸大小限制。") }
            var result: [String: UserViewValue] = ["data": .string(bytes.base64EncodedString()),
                "documentID": .string(model.documentIdentity), "fingerprint": .string(try model.documentFingerprint())]
            if model.fileURL?.standardizedFileURL == url.standardizedFileURL, let hash = model.lastSavedSHA256 {
                result["knownFileSHA256"] = .string(hash)
            }
            return result
        case let (.flowchart_save(id, path), .saved):
            let model = try panel(id, kind: .canvas).flowchartModel!
            guard let documentID = transfer.documentID, let fingerprint = transfer.fingerprint, let hash = transfer.fileSHA256 else {
                throw failure("invalid_argument", "儲存確認缺少文件識別資訊。")
            }
            let reflected = try model.acknowledgeSave(to: flowchartURL(path), documentID: documentID, fingerprint: fingerprint, fileSHA256: hash)
            return ["saved": .boolean(true), "panelReflectsSavedDocument": .boolean(reflected), "hasUnsavedChanges": .boolean(model.isDirty)]
        default: throw failure("invalid_argument", "此指令不支援指定的檔案傳輸方式。")
        }
        return [:]
    }

    /// Examples are executable requests for the local simulator and future Agent adapters.
    /// Read-only panels intentionally have no content mutation capabilities.
    func capabilities() -> [WorkspaceAgentCapability] {
        let screenID = manager.activeRoot?.screenID ?? "screen-id"
        let firstID = manager.catalog.first?.id ?? "panel-id"
        var result: [WorkspaceAgentCapability] = []
        func add(_ command: WorkspaceAgentCommand, panelID: String? = nil) {
            result.append(.init(name: command.name, panelID: panelID,
                                example: .init(command: command)))
        }
        add(.get_user_view); add(.list_capabilities)
        for kind in WorkspacePanel.Kind.allCases where kind != .agentCoreTest {
            add(.create_panel(kind: kind, screenID: screenID))
        }
        add(.set_mode(screenID: screenID, mode: .grid))
        add(.move_panels(panelIDs: [firstID], screenID: screenID, row: 1, column: 0))
        add(.grid_viewport(screenID: screenID, zoom: 0.3, scrollOffset: 0))
        for panel in manager.catalog {
            let id = panel.id
            func panelAdd(_ command: WorkspaceAgentCommand) { add(command, panelID: id) }
            panelAdd(.read_panel(panelID: id))
            if panel.kind.canClose { panelAdd(.close_panel(panelID: id, discardChanges: false)) }
            panelAdd(.select_panel(panelID: id, extending: false))
            if panel.supportsFocusedMode {
                panelAdd(.focus_panel(panelID: id)); panelAdd(.toggle_panel(panelID: id))
            }
            switch panel.kind {
            case .conversationHistory:
                panelAdd(.conversation_select_session(panelID: id, sessionID: manager.panels[id]?.conversationHistoryModel?.sessions.first?.id ?? "session-id"))
            case .notes: panelAdd(.notes_set_text(panelID: id, text: "Agent 測試筆記"))
            case .chart:
                panelAdd(.chart_load_csv(panelID: id, csv: "X,A,B,note\n1,2,3,test\n2,3,4,", sourceName: "Agent CSV"))
                panelAdd(.chart_open_csv(panelID: id, path: "/tmp/agent-test.csv"))
                let names = manager.panels[id]?.chartModel?.data.seriesNames ?? []
                panelAdd(.chart_set_series(panelID: id, names: names))
                panelAdd(.chart_set_bands(panelID: id, bands: names.count < 2 ? [] : [.init(firstSeriesName: names[0], secondSeriesName: names[1], opacity: 0.2)]))
                panelAdd(.chart_viewport(panelID: id, zoom: 2, pan: 0))
            case .imageGallery:
                panelAdd(.image_add_url(panelID: id, url: "https://example.com/image.png"))
                panelAdd(.image_add_file(panelID: id, path: "/tmp/agent-test.png"))
                panelAdd(.image_select(panelID: id, index: 0)); panelAdd(.image_expand(panelID: id, index: 0))
                panelAdd(.image_collapse(panelID: id)); panelAdd(.image_viewport(panelID: id, zoom: 2, panX: 20, panY: 10))
            case .browser:
                panelAdd(.browser_navigate(panelID: id, address: "https://example.com"))
                panelAdd(.browser_control(panelID: id, action: .offlineTestPage))
            case .canvas:
                let nodes = manager.panels[id]?.flowchartModel?.nodes ?? []
                let nodeID = nodes.first?.id ?? "node-id"
                panelAdd(.flowchart_add_node(panelID: id, type: .process, x: 0, y: 120))
                panelAdd(.flowchart_update_node(panelID: id, nodeID: nodeID, text: "測試步驟", x: 20, y: 120))
                panelAdd(.flowchart_select_node(panelID: id, nodeID: nodeID, extending: false))
                panelAdd(.flowchart_connect(panelID: id, from: nodeID, to: nodes.dropFirst().first?.id ?? "target-id", label: nil))
                panelAdd(.flowchart_delete_selection(panelID: id))
                panelAdd(.flowchart_viewport(panelID: id, zoom: 1, panX: 0, panY: 0))
                panelAdd(.flowchart_new(panelID: id, discardChanges: false))
                panelAdd(.flowchart_open(panelID: id, path: "/tmp/agent-test.maltoseflow.json", discardChanges: false))
                panelAdd(.flowchart_save(panelID: id, path: "/tmp/agent-test.maltoseflow.json"))
            case .agentIdentity: panelAdd(.identity_set_state(panelID: id, state: .thinking))
            case .document, .table, .agentCoreTest, .agentActivity, .taskProgress: break
            }
        }
        return result
    }

    private func execute(_ command: WorkspaceAgentCommand) throws -> [String: UserViewValue] {
        guard manager.draggingID == nil, !manager.isAgentInteractionTestRunning else { throw failure("busy", "使用者正在拖曳面板或播放互動示範，請稍後重試。") }
        switch command {
        case .get_user_view, .list_capabilities, .read_panel: break // handled by async entry point
        case .workflow, .acknowledge_panel_operations: throw failure("access_denied", "任務與操作回執只接受原生協調層的私有執行來源。")
        case let .deliver_result(id, title, markdown, createDocument, conversationID, messageID, chart):
            return try manager.deliverResult(.init(publicationID: id, conversationID: conversationID,
                messageID: messageID, title: title, markdown: markdown, createDocument: createDocument, chart: chart))
        case let .create_panel(kind, screenID):
            let target = try root(screenID ?? manager.activeRoot?.screenID ?? "")
            guard let panel = manager.addPanel(kind: kind, to: target.screenID) else {
                throw failure("panel_limit", "此面板為單例或無法在工作區建立。")
            }
            return ["panelID": .string(panel.id)]
        case let .publish_document(publicationID, title, markdown):
            guard publicationID.range(of: "^[A-Za-z0-9._:-]{1,128}$", options: .regularExpression) != nil,
                  !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, title.utf8.count <= 200,
                  title.rangeOfCharacter(from: .controlCharacters) == nil,
                  !markdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, markdown.utf8.count <= 256 * 1024 else {
                throw failure("invalid_argument", "結果識別、標題或內容大小不正確。")
            }
            let encoded = try JSONEncoder().encode([title, markdown])
            let digest = SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined()
            if let previous = publications[publicationID] {
                guard previous.digest == digest else { throw failure("invalid_request", "同一發表識別不可改寫已發表內容。") }
                guard manager.panels[previous.panelID] != nil else { throw failure("not_found", "結果面板已關閉，不自動重新開啟。") }
                return ["panelID": .string(previous.panelID), "replayed": .boolean(true)]
            }
            guard publications.count < 512 else { throw failure("panel_limit", "本次工作區的結果發表數量已達上限。") }
            let target = try root(manager.activeRoot?.screenID ?? "")
            guard let created = manager.addPanel(kind: .document, to: target.screenID, title: title),
                  let model = manager.panels[created.id]?.markdownDocumentModel else {
                throw failure("panel_limit", "無法建立結果文檔面板。")
            }
            model.loadResult(title: title, markdown: markdown)
            publications[publicationID] = (digest, created.id)
            return ["panelID": .string(created.id), "replayed": .boolean(false)]
        case let .close_panel(id, discard):
            let panel = try panel(id)
            guard manager.catalog.first(where: { $0.id == id })?.kind.canClose == true else { throw failure("protected_panel", "形象與聊天是固定面板，不能關閉。") }
            try checkDirty(panel.flowchartModel, discard: discard)
            guard manager.closePanel(id) else { throw failure("operation_failed", "面板尚未關閉，無法保存關閉紀錄。") }
        case let .select_panel(id, extending):
            _ = try panel(id)
            if manager.catalog.first(where: { $0.id == id })?.supportsFocusedMode == false,
               let screenID = manager.assignments[id], manager.roots[screenID]?.state.mode != .grid {
                throw failure("unsupported_operation", "請先切換至全局排列以選取形象面板。")
            }
            manager.highlightPanel(id, extending: extending)
        case let .focus_panel(id):
            try checkFocusable(id); manager.selectPanel(id)
        case let .toggle_panel(id):
            try checkFocusable(id); manager.togglePanel(id)
        case let .set_mode(screenID, mode):
            let root = try root(screenID)
            if mode != .grid {
                guard let id = root.state.primaryID else { throw failure("invalid_state", "空工作區無法放大面板。") }
                try checkFocusable(id)
            }
            manager.setWorkspaceMode(mode, on: screenID)
        case let .move_panels(ids, screenID, row, column):
            let root = try root(screenID)
            guard !ids.isEmpty, Set(ids).count == ids.count else { throw failure("invalid_argument", "面板清單不可為空或重複。") }
            for id in ids { _ = try panel(id) }
            guard (row == nil) == (column == nil), (row ?? 0) >= 0, (row ?? 0) <= 1000,
                  (column ?? 0) >= 0, (column ?? 0) < root.globalGridGeometry.columns,
                  row == nil || !ids.contains("agent-identity") || ids.count == 1 else {
                throw failure("invalid_argument", "排列位置超出範圍或形象需單獨排列。")
            }
            guard Set(ids.compactMap { manager.assignments[$0] }).count == 1 else {
                throw failure("invalid_argument", "一次移動的面板必須來自同一窗口。")
            }
            guard manager.movePanels(ids, to: screenID, position: row.map { .init(row: $0, column: column!) }) else {
                throw failure("invalid_state", "目前無法移動面板。")
            }
        case let .grid_viewport(screenID, zoom, offset):
            try finite(zoom, offset)
            let root = try root(screenID)
            guard root.state.mode == .grid else { throw failure("invalid_state", "請先切換至全局排列。") }
            root.setGlobalZoom(zoom)
            root.scrollGlobalGrid(by: offset - root.globalScrollOffset)
        case let .conversation_select_session(id, sessionID):
            let model = try panel(id, kind: .conversationHistory).conversationHistoryModel!
            guard model.allowsSessionSelection else { throw failure("invalid_state", "請先放大聊天面板以切換 session。") }
            guard let session = model.sessions.first(where: { $0.id == sessionID }) else { throw failure("not_found", "找不到 session。") }
            model.selectSession(session)
        case let .notes_set_text(id, text): try panel(id, kind: .notes).sampleContentModel!.note = text
        case let .chart_load_csv(id, csv, sourceName):
            try panel(id, kind: .chart).chartModel!.loadCSV(contents: csv, sourceName: sourceName)
        case let .chart_open_csv(id, path):
            let model = try panel(id, kind: .chart).chartModel!
            try model.importCSV(localURL(path))
        case let .chart_set_series(id, names):
            let model = try panel(id, kind: .chart).chartModel!
            guard names.allSatisfy(model.data.seriesNames.contains) else { throw failure("invalid_argument", "線條名稱不存在。") }
            model.configureAgentVisibleSeries(names)
        case let .chart_set_bands(id, bands):
            let model = try panel(id, kind: .chart).chartModel!
            guard bands.allSatisfy({ $0.opacity.isFinite && $0.firstSeriesName != $0.secondSeriesName && model.data.seriesNames.contains($0.firstSeriesName) && model.data.seriesNames.contains($0.secondSeriesName) }) else {
                throw failure("invalid_argument", "填色線對或透明度不正確。")
            }
            model.configureAgentBands(bands)
        case let .chart_viewport(id, zoom, pan):
            try finite(zoom, pan); try panel(id, kind: .chart).chartModel!.setXAxisViewport(zoom: zoom, pan: pan)
        case let .image_add_url(id, url):
            guard try panel(id, kind: .imageGallery).imageGalleryModel!.addRemoteImage(url) else { throw failure("invalid_argument", "僅支援 HTTP(S) 圖片網址。") }
        case let .image_add_file(id, path):
            let model = try panel(id, kind: .imageGallery).imageGalleryModel!
            try model.importLocalImage(localURL(path))
        case let .image_select(id, index), let .image_expand(id, index):
            let model = try panel(id, kind: .imageGallery).imageGalleryModel!
            guard model.images.indices.contains(index) else { throw failure("invalid_argument", "圖片索引超出範圍。") }
            if case .image_expand = command {
                guard model.showsCarousel else { throw failure("invalid_state", "請先放大圖片面板。") }
                model.expandImage(at: index)
            } else { model.selectImage(at: index) }
        case let .image_collapse(id): try panel(id, kind: .imageGallery).imageGalleryModel!.collapse()
        case let .image_viewport(id, zoom, x, y):
            try finite(zoom, x, y)
            let galleryPanel = try panel(id, kind: .imageGallery)
            let model = galleryPanel.imageGalleryModel!
            guard model.expandedIndex != nil else { throw failure("invalid_state", "請先展開圖片。") }
            model.beginMagnification(); model.updateMagnification(zoom / model.zoomScale)
            model.beginPan(); model.updatePan(.init(width: x - model.panOffset.width, height: y - model.panOffset.height))
            model.constrainPan(to: galleryPanel.contentBounds.size)
        case let .browser_navigate(id, address):
            let model = try panel(id, kind: .browser).browserModel!
            guard BrowserPanelModel.destination(for: address) != nil else { throw failure("invalid_argument", "不支援的網址。") }
            model.addressDraft = address; model.loadAddress()
        case let .browser_control(id, action):
            let model = try panel(id, kind: .browser).browserModel!
            switch action {
            case .back:
                guard model.canGoBack else { throw failure("invalid_state", "沒有上一頁。") }; model.goBack()
            case .forward:
                guard model.canGoForward else { throw failure("invalid_state", "沒有下一頁。") }; model.goForward()
            case .reload: model.reload()
            case .stop: model.stopLoading()
            case .offlineTestPage: model.simulateTestPage()
            }
        case let .flowchart_add_node(id, type, x, y):
            try finite(x, y)
            let nodeID = try panel(id, kind: .canvas).flowchartModel!.addNode(type, at: .init(x: x, y: y))
            return ["nodeID": .string(nodeID)]
        case let .flowchart_update_node(id, nodeID, text, x, y):
            try finite(x, y)
            let model = try flowchart(id, nodeID: nodeID)
            model.updateText(text, for: nodeID); model.setPosition(.init(x: x, y: y), for: nodeID)
        case let .flowchart_select_node(id, nodeID, extending):
            try flowchart(id, nodeID: nodeID).selectNode(nodeID, extending: extending)
        case let .flowchart_connect(id, from, to, label):
            let model = try flowchart(id, nodeID: from)
            _ = try flowchart(id, nodeID: to)
            guard model.connect(from: from, to: to, label: label) else { throw failure("invalid_argument", "無法建立自連或重複連線。") }
        case let .flowchart_delete_selection(id): try panel(id, kind: .canvas).flowchartModel!.deleteSelection()
        case let .flowchart_viewport(id, zoom, x, y):
            try finite(zoom, x, y)
            let model = try panel(id, kind: .canvas).flowchartModel!
            model.setZoom(zoom); model.setPanOffset(.init(width: x, height: y))
        case let .flowchart_new(id, discard):
            let model = try panel(id, kind: .canvas).flowchartModel!
            try checkDirty(model, discard: discard); model.newDocument()
        case let .flowchart_open(id, path, discard):
            let model = try panel(id, kind: .canvas).flowchartModel!
            try checkDirty(model, discard: discard); try model.load(from: flowchartURL(path))
        case let .flowchart_save(id, path):
            let model = try panel(id, kind: .canvas).flowchartModel!
            try model.save(to: flowchartURL(path))
        case let .identity_set_state(id, state):
            _ = try panel(id, kind: .agentIdentity); AgentIdentityAnimationModel.shared.setState(state)
        }
        return [:]
    }

    private func failure(_ code: String, _ message: String) -> WorkspaceAgentFailure { .init(code: code, message: message) }
    private func root(_ id: String) throws -> WorkspaceRootView {
        guard let root = manager.roots[id] else { throw failure("not_found", "找不到工作區窗口：\(id)") }; return root
    }
    private func panel(_ id: String, kind: WorkspacePanel.Kind? = nil) throws -> GlassPanelView {
        guard let entry = manager.catalog.first(where: { $0.id == id }), let panel = manager.panels[id] else { throw failure("not_found", "找不到面板：\(id)") }
        guard kind == nil || kind == entry.kind else { throw failure("unsupported_operation", "面板不支援此操作。") }
        return panel
    }
    private func checkFocusable(_ id: String) throws {
        _ = try panel(id)
        guard manager.catalog.first(where: { $0.id == id })?.supportsFocusedMode == true else { throw failure("unsupported_operation", "此面板不支援放大。") }
    }
    private func flowchart(_ id: String, nodeID: String) throws -> FlowchartCanvasModel {
        let model = try panel(id, kind: .canvas).flowchartModel!
        guard model.nodes.contains(where: { $0.id == nodeID }) else { throw failure("not_found", "找不到流程節點。") }; return model
    }
    private func finite(_ values: Double...) throws {
        guard values.allSatisfy({ $0.isFinite && abs($0) <= 1_000_000 }) else { throw failure("invalid_argument", "數值必須有限且介於 ±1000000。") }
    }
    private func checkDirty(_ model: FlowchartCanvasModel?, discard: Bool) throws {
        if model?.isDirty == true && !discard { throw failure("unsaved_changes", "流程圖尚未儲存；請先儲存或明確指定 discardChanges。") }
    }
    private func localURL(_ path: String) throws -> URL {
        guard path.hasPrefix("/") else { throw failure("invalid_argument", "請指定本機檔案的絕對路徑。") }
        return URL(fileURLWithPath: path)
    }
    private func flowchartURL(_ path: String) throws -> URL {
        guard path.hasPrefix("/"), path.hasSuffix(".maltoseflow.json") else { throw failure("invalid_argument", "請指定 .maltoseflow.json 的絕對路徑。") }
        return URL(fileURLWithPath: path)
    }
}
