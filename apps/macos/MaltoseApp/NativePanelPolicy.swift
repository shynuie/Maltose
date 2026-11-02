import AppKit
import Combine
import CryptoKit

/// Private transport provenance. No model-facing tool accepts these fields.
struct NativePanelSource: Codable, Equatable {
    var runtimeSessionID: String
    var executor: AgentRecipient
    var inputID: String
    var scopeID: String
    var controlEpoch: Int?
    var product: ProductReference?
    var taskID: UUID?
    var turnID: String?
    var connectionID: UUID?
    var leaseID: String?
    var continuation: Continuation?
    struct ProductReference: Codable, Equatable {
        var taskID: UUID
        var requirementsRevision: Int
        var planVersion: Int
        var executionID: String?
    }
    struct Continuation: Codable, Equatable {
        var taskID: UUID
        var inputID: String
        var requirementsRevision: Int
        var planVersion: Int
        var continuationID: String
        var foregroundID: String?
        var resumeAfterID: String?
    }
}

struct NativePanelHumanContext: Equatable {
    var inputID: String
    var text: String
    var canReadExisting: Bool
}

struct NativePanelIntent: Codable {
    var decision: String
    var command: String
    var targetIDs: [String]
    var evidence: String
    var reason: String
    var actionEvidence: String = ""
    var targetEvidence: String = ""
    var semanticActionVerified: Bool? = nil
    var discardEvidence: String? = nil
}

/// Persisted provenance for panel actions. Autonomous in-app actions share the
/// standing UI grant; local-file exports retain their individual authorization.
struct NativePanelMutationClaim: Codable, Equatable {
    var inputID: String
    var targetID: String
    var category: String
    var source: NativePanelSource
    var operationVersion: Int? = nil
    var autonomous: Bool? = nil
}

extension WorkspaceAgentCommand {
    var allowedActionEvidence: [String] {
        let edit = ["更新", "修改", "改寫", "改成", "改為", "改爲", "變更", "替換", "重寫", "調整", "update", "edit", "change", "replace", "revise", "rewrite"]
        let add = ["加入", "加到", "添加", "新增", "增加", "補上", "補進", "建立", "畫出", "add", "append", "insert", "create", "draw"]
        let open = ["載入", "匯入", "開啟", "打開", "讀入", "load", "import", "open"]
        switch self {
        case .notes_set_text, .flowchart_update_node: return edit
        case .chart_load_csv, .chart_open_csv: return edit + open
        case .image_add_url, .image_add_file, .flowchart_add_node, .flowchart_connect: return add + ["連接", "連線", "連結", "connect", "link"]
        case .browser_navigate: return edit + open + ["前往", "導航", "瀏覽", "navigate", "visit", "browse"]
        case let .browser_control(_, action):
            switch action {
            case .back: return ["返回", "上一頁", "back", "previous"]
            case .forward: return ["下一頁", "向前", "forward", "next"]
            case .reload: return ["重新整理", "重新載入", "更新", "reload", "refresh"]
            case .stop: return ["停止", "取消載入", "stop", "cancel"]
            case .offlineTestPage: return ["測試頁", "離線測試", "test page", "offline test"]
            }
        case .flowchart_delete_selection: return ["刪除", "移除", "刪掉", "delete", "remove"]
        case .flowchart_new: return ["清空", "重設", "重畫", "新建", "clear", "reset", "new", "redraw"]
        case .flowchart_open: return edit + open
        case .flowchart_save: return ["儲存", "保存", "另存", "匯出", "save", "export"]
        case .close_panel: return ["關閉", "關掉", "移除", "close", "remove"]
        case .focus_panel, .toggle_panel: return ["放大", "顯示", "打開", "切換", "聚焦", "show", "focus", "enlarge", "expand", "switch", "toggle", "open"]
        case .select_panel, .conversation_select_session, .image_select, .flowchart_select_node:
            return ["選取", "選擇", "切換", "顯示", "select", "choose", "switch", "show", "highlight"]
        case .move_panels: return ["移動", "移到", "移至", "搬到", "排列", "重排", "move", "reorder", "arrange"]
        case .set_mode, .grid_viewport: return ["切換", "排列", "縮放", "捲動", "滾動", "放大", "縮小", "顯示", "switch", "arrange", "zoom", "scroll", "show"]
        case .chart_set_series, .chart_set_bands, .chart_viewport, .image_expand, .image_collapse, .image_viewport, .flowchart_viewport:
            return edit + ["顯示", "隱藏", "放大", "縮小", "縮放", "平移", "展開", "收起", "填色", "show", "hide", "zoom", "pan", "expand", "collapse", "fill"]
        case .identity_set_state: return edit + ["設定", "切換", "set", "switch"]
        case .get_user_view, .list_capabilities, .read_panel, .create_panel, .publish_document, .deliver_result, .workflow, .acknowledge_panel_operations: return []
        }
    }

    enum PanelEffect {
        case read, create, publication
        case mutation(category: String, targets: [String], initialFill: Bool)
    }
    var panelEffect: PanelEffect {
        switch self {
        case .get_user_view, .list_capabilities, .read_panel: return .read
        case .create_panel: return .create
        case .publish_document, .deliver_result, .workflow, .acknowledge_panel_operations: return .publication
        case let .notes_set_text(id, _), let .chart_load_csv(id, _, _), let .chart_open_csv(id, _),
             let .image_add_url(id, _), let .image_add_file(id, _), let .browser_navigate(id, _),
             let .browser_control(id, _), let .flowchart_add_node(id, _, _, _),
             let .flowchart_update_node(id, _, _, _, _), let .flowchart_connect(id, _, _, _),
             let .flowchart_delete_selection(id), let .flowchart_new(id, _), let .flowchart_open(id, _, _):
            return .mutation(category: "content", targets: [id], initialFill: true)
        case let .chart_set_series(id, _), let .chart_set_bands(id, _), let .chart_viewport(id, _, _),
             let .image_select(id, _), let .image_expand(id, _), let .image_collapse(id),
             let .image_viewport(id, _, _, _), let .flowchart_select_node(id, _, _), let .flowchart_viewport(id, _, _, _):
            return .mutation(category: "view", targets: [id], initialFill: true)
        case let .close_panel(id, _): return .mutation(category: "close", targets: [id], initialFill: false)
        case let .select_panel(id, _), let .focus_panel(id), let .toggle_panel(id), let .conversation_select_session(id, _):
            return .mutation(category: "focus", targets: [id], initialFill: false)
        case let .set_mode(screen, _), let .grid_viewport(screen, _, _):
            return .mutation(category: "layout", targets: ["screen:" + screen], initialFill: false)
        case let .move_panels(ids, screen, _, _):
            return .mutation(category: "layout", targets: ids + ["screen:" + screen], initialFill: false)
        case let .flowchart_save(id, _): return .mutation(category: "save", targets: [id], initialFill: false)
        case let .identity_set_state(id, _): return .mutation(category: "identity", targets: [id], initialFill: false)
        }
    }
}

@MainActor final class NativePanelPolicy {
    var validateSource: ((NativePanelSource) throws -> NativePanelHumanContext)?
    var assessIntent: (([String: UserViewValue], NativePanelSource) async throws -> NativePanelIntent)?
    var claimMutation: (([NativePanelMutationClaim]) throws -> Void)?
    var canRetryMutation: ((NativePanelMutationClaim, NativePanelMutationClaim) -> Bool)?
    var operationJournal: NativePanelOperationJournal?
    var operationProtocolEnabled: (() -> Bool)?
    private let instanceID = UUID().uuidString
    private unowned let manager: WorkspaceWindowManager
    private var revisions: [String: Int] = [:]
    private var observers: [String: (ObjectIdentifier, [AnyCancellable])] = [:]
    private struct InputSnapshot {
        var revisions: [String: Int]
        var catalog: [UserViewValue]
        var layout: String
        var runtimeSessionID: String?
        var activeScreenID: String?
    }
    private var inputs: [String: InputSnapshot] = [:]
    private struct Ownership {
        var source: NativePanelSource
        var revision: Int
        var initial: Bool
        var layout: String? = nil
    }
    private var owners: [String: Ownership] = [:]
    private var permissions: Set<String> = []
    private var discardPermissions: Set<String> = []
    init(manager: WorkspaceWindowManager) { self.manager = manager }

    func captureHumanInput(_ inputID: String, runtimeSessionID: String? = nil) {
        if inputs[inputID] != nil {
            if inputs[inputID]?.runtimeSessionID == nil { inputs[inputID]?.runtimeSessionID = runtimeSessionID }
            return
        }
        guard inputs.count < 2048 else { return }
        watchModels()
        inputs[inputID] = .init(revisions: revisions, catalog: panelCatalog(), layout: layoutStamp(), runtimeSessionID: runtimeSessionID,
                               activeScreenID: manager.submittingScreenID ?? manager.activeRoot?.screenID)
    }

    /// A closed guard ledger, not a comparison of visible content. Human edits,
    /// browser activity, files and other inputs are deliberately outside this proof.
    func actionBoundary(inputID: String, runtimeSessionID: String,
                        claims: [NativePanelMutationClaim], operations: [NativePanelOperation]) -> [String: UserViewValue] {
        let snapshot = inputs[inputID]
        let complete = snapshot?.runtimeSessionID == runtimeSessionID && operationProtocolEnabled?() == true
            && operationJournal != nil && validateSource != nil && claimMutation != nil
        let accepted = claims.filter { $0.inputID == inputID && $0.source.runtimeSessionID == runtimeSessionID }
        let recorded = operations.filter { $0.inputID == inputID && $0.source.runtimeSessionID == runtimeSessionID }
        let panels = (snapshot?.catalog ?? []).map { panel in
            UserViewValue.object(["id": panel["id"] ?? .null, "kind": panel["kind"] ?? .null])
        }
        return ["kind": .string("native_panel_action_boundary"), "schemaVersion": .number(1),
            "scope": .string("guarded_native_agent_panel_entrypoints"),
            "interval": .string("human_input_capture_to_main_result_prepare"),
            "inputID": .string(inputID), "runtimeSessionID": .string(runtimeSessionID), "instanceID": .string(instanceID),
            "complete": .boolean(complete), "originalPanels": .array(panels),
            "noAcceptedExistingPanelActions": .boolean(complete && accepted.isEmpty && recorded.isEmpty),
            "acceptedActions": .array(accepted.map { .object(["targetID": .string($0.targetID), "category": .string($0.category),
                "executor": .string($0.source.executor.rawValue), "scopeID": .string($0.source.scopeID)]) }),
            "operations": .array(recorded.map { .object(["id": .string($0.id), "targets": .strings($0.targets),
                "category": .string($0.category), "phase": .string($0.phase.rawValue)]) }),
            "limitation": .string("只核對此原生實例、同一人員輸入與 runtime 至成果準備時的受控 Agent 面板操作。所有非自有新面板初填的 Agent 操作都先保存 claim；沒有 claim／operation 才能證明該範圍未接納舊面板操作。成果 writer 另由 answer_delivery 核對。不能證明人員編輯、動態頁面、檔案或其他輸入／執行沒有變動；complete=false 不可據此推定沒有操作。")]
    }

    func perform(_ request: WorkspaceAgentRequest, apply: (Bool) async -> WorkspaceAgentResponse) async -> WorkspaceAgentResponse {
        do {
            let operationJournal = operationProtocolEnabled?() == false ? nil : self.operationJournal
            if case let .acknowledge_panel_operations(receipts) = request.command {
                guard request.source == nil, let operationJournal else { throw fail("access_denied", "操作回執未連接。") }
                try operationJournal.acknowledge(receipts)
                return .init(requestID: request.requestID, ok: true)
            }
            if case .publication = request.command.panelEffect {
                guard request.source == nil else { throw fail("access_denied", "模型面板工具不能呼叫私有成果／任務發表入口。") }
                return await apply(false)
            }
            guard let source = request.source, !source.scopeID.isEmpty, source.scopeID.utf8.count <= 128,
                  let validateSource else { throw fail("source_required", "面板操作缺少目前人員輸入的執行來源。") }
            let human = try validateSource(source)
            if inputs[human.inputID]?.runtimeSessionID == nil { inputs[human.inputID]?.runtimeSessionID = source.runtimeSessionID }
            watchModels()
            switch request.command.panelEffect {
            case .read:
                var response = await apply(false)
                _ = try validateSource(source)
                if response.ok { appendOperationReceipts(to: &response, command: request.command, source: source) }
                return response
            case .create:
                guard owners.count < 1024 else { throw fail("panel_limit", "本次面板操作紀錄已達上限；保留現有面板與完整文字。") }
                let previousLayout = layoutStamp()
                let response = await apply(false)
                if response.ok, let id = response.result["panelID"]?.stringValue {
                    watchModels()
                    owners[id] = .init(source: source, revision: revisions[id, default: 0], initial: true)
                    advanceOwnLayout(from: previousLayout, inputID: human.inputID, source: source)
                }
                return response
            case let .mutation(category, targets, initialFill):
                guard !targets.isEmpty, targets.count <= 64, Set(targets).count == targets.count else { throw fail("invalid_argument", "操作目標不可為空或重複。") }
                for id in targets {
                    guard exists(id) else { throw fail("not_found", "指定面板或窗口已不存在，不會改用另一個目標。") }
                }
                if category == "close", targets.contains(where: { id in manager.catalog.first(where: { $0.id == id })?.kind.canClose == false }) {
                    throw fail("protected_panel", "形象與聊天是固定面板，不能關閉。")
                }
                let owned = initialFill && targets.allSatisfy { owners[$0]?.source == source && owners[$0]?.initial == true }
                let key = try permissionKey(source, command: request.command)
                if category == "save" {
                    for id in targets {
                        guard exists(id) else { throw fail("not_found", "指定面板或窗口已不存在，不會改用另一個目標。") }
                        if let owner = owners[id], owner.source == source, owner.revision != revisions[id, default: 0] {
                            throw fail("user_changed", "面板在生成期間已被編輯或操作，保留目前內容；請以新訊息指定後續修改。")
                        }
                        if let owner = owners[id], owner.source == source, let layout = owner.layout, layout != layoutStamp() {
                            throw fail("user_changed", "工作區視圖在操作期間已改變，保留目前閱讀狀態。")
                        }
                    }
                    let needsDiscard = requiresDiscardConsent(request.command, targets: targets)
                    if !owned && (!permissions.contains(key) || (needsDiscard && !discardPermissions.contains(key))) {
                        guard human.canReadExisting else { throw fail("identity_required", "目前來源不能變更既有面板；新成果請建立新面板。") }
                        guard let baseline = inputs[human.inputID] else { throw fail("source_snapshot_expired", "原指令的面板狀態已過期；新成果請另開面板，既有內容保持不變。") }
                        guard baseline.runtimeSessionID == source.runtimeSessionID else { throw fail("source_snapshot_expired", "重啟前的面板修改許可已失效，保留現有內容。") }
                        for id in targets where owners[id]?.source != source {
                            if let owner = owners[id], !owner.initial, owner.source.inputID == source.inputID {
                                let previous = NativePanelMutationClaim(inputID: human.inputID, targetID: id, category: category, source: owner.source, operationVersion: operationJournal == nil ? nil : 1)
                                let next = NativePanelMutationClaim(inputID: human.inputID, targetID: id, category: category, source: source, operationVersion: operationJournal == nil ? nil : 1)
                                guard canRetryMutation?(previous, next) == true else { throw fail("update_scope_expired", "本次修改已由先前執行接納，不能用新的發表重用更新許可。") }
                            }
                            if id.hasPrefix("screen:") {
                                guard baseline.layout == layoutStamp() else { throw fail("user_changed", "指令送出後工作區已變更，保留目前排列。") }
                            } else {
                                guard let original = baseline.revisions[id] else { throw fail("update_not_authorized", "此面板屬於其他發表，原指令不會取得它的後續修改權；新成果請建立新面板。") }
                                guard original == revisions[id] else {
                                    throw fail("user_changed", "指令送出後面板已被修改，保留目前內容。")
                                }
                            }
                        }
                        guard let assessIntent, let claimMutation else { throw fail("update_not_authorized", "既有面板修改核對尚未連接；新成果請建立新面板。") }
                        let stamp = worldStamp(targets)
                        let intent = try await assessIntent(intentContext(request.command, human: human, targets: targets, source: source), source)
                        guard try validateSource(source) == human, stamp == worldStamp(targets) else {
                            throw fail("source_changed", "人員要求、目標或目前視圖已改變，本次舊面板操作未套用。")
                        }
                        guard intent.decision == "allow", intent.command == request.command.name,
                              Set(intent.targetIDs) == Set(targets), !intent.evidence.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                              human.text.contains(intent.evidence), !intent.actionEvidence.isEmpty,
                              intent.evidence.contains(intent.actionEvidence),
                              (intent.semanticActionVerified == true || request.command.allowedActionEvidence.contains(where: { verb in
                                  verb.allSatisfy(\.isASCII) ? intent.actionEvidence.range(of: "\\b" + NSRegularExpression.escapedPattern(for: verb) + "\\b", options: [.regularExpression, .caseInsensitive]) != nil : intent.actionEvidence.contains(verb)
                              })),
                              !intent.targetEvidence.isEmpty, intent.evidence.contains(intent.targetEvidence),
                              groundedTarget(intent.targetEvidence, targets: targets, inputID: human.inputID) else {
                            throw fail(intent.decision == "ambiguous" ? "ambiguous_target" : "update_not_authorized", intent.reason)
                        }
                        if requiresDiscardConsent(request.command, targets: targets) {
                            guard let evidence = intent.discardEvidence, !evidence.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                                  human.text.contains(evidence) else { throw fail("discard_not_authorized", "流程圖有未儲存修改，原指令沒有明確同意捨棄；保留目前內容。") }
                            discardPermissions.insert(key)
                        }
                        try claimMutation(targets.map { .init(inputID: human.inputID, targetID: $0, category: category, source: source,
                                                           operationVersion: operationJournal == nil ? nil : 1) })
                        for id in targets {
                            if owners[id]?.source != source {
                                owners[id] = .init(source: source, revision: revisions[id, default: 0], initial: false)
                            }
                        }
                        permissions.insert(key)
                    }
                } else {
                    // The user's standing panel grant covers all in-app actions.
                    // Record provenance without a second model or a permission prompt.
                    if !owned {
                        try claimMutation?(targets.map { .init(inputID: human.inputID, targetID: $0, category: category,
                            source: source, operationVersion: operationJournal == nil ? nil : 1, autonomous: true) })
                        for id in targets where owners[id]?.source != source {
                            owners[id] = .init(source: source, revision: revisions[id, default: 0], initial: false)
                        }
                    }
                }
                _ = try validateSource(source)
                let previousLayout = layoutStamp()
                var operation: NativePanelOperation?
                if !owned, category != "save", let operationJournal {
                    let prepared = NativePanelOperation(id: request.requestID ?? UUID().uuidString, inputID: human.inputID, source: source,
                        category: category, targets: targets, commandDigest: key, instanceID: instanceID,
                        beforeStamp: NativePanelOperationJournal.stamp(worldStamp(targets)), acknowledgementToken: UUID().uuidString)
                    try operationJournal.prepare(prepared); operation = prepared
                }
                var response = await apply(!owned && category == "content")
                if var saved = operation, let operationJournal {
                    saved.afterStamp = NativePanelOperationJournal.stamp(worldStamp(targets))
                    let known = ["invalid_argument", "invalid_csv", "not_found", "unsupported_operation", "invalid_state", "busy", "unsaved_changes", "file_transfer_required", "access_denied", "panel_limit", "protected_panel"]
                    let observable = category != "identity" && !targets.contains { manager.panels[$0]?.browserModel != nil }
                    saved.phase = response.ok ? .completed : observable && saved.beforeStamp == saved.afterStamp && known.contains(response.error?.code ?? "") ? .failedNoChange : .uncertain
                    do {
                        saved.responseData = try JSONEncoder().encode(response)
                        try operationJournal.finish(saved)
                    } catch {
                        throw WorkspaceAgentFailure(code: "outcome_unknown", message: "面板操作已開始，但完成回執未能保存；請先讀回面板核對，不要直接重做。", operationID: saved.id)
                    }
                    if saved.phase == .uncertain {
                        response = .init(requestID: request.requestID, ok: false,
                            error: .init(code: "outcome_unknown", message: "面板操作可能已發生；請先讀回面板與操作紀錄，不能直接重做。", operationID: saved.id))
                    } else {
                        response.operationReceipts = [.init(id: saved.id, token: saved.acknowledgementToken)]
                    }
                }
                if response.ok {
                    advanceOwnLayout(from: previousLayout, inputID: human.inputID, source: source)
                    for id in targets where owners[id]?.source == source {
                        owners[id]?.revision = revisions[id, default: 0]
                        if category == "focus" || category == "layout" { owners[id]?.layout = layoutStamp() }
                    }
                }
                return response
            case .publication: fatalError("Private publication handled before model source")
            }
        } catch {
            return .init(requestID: request.requestID, ok: false,
                         error: error as? WorkspaceAgentFailure ?? fail("access_denied", error.localizedDescription))
        }
    }

    private func permissionKey(_ source: NativePanelSource, command: WorkspaceAgentCommand) throws -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let encoded = try encoder.encode(WorkspaceAgentRequest(command: command, source: source))
        return SHA256.hash(data: encoded).map { String(format:"%02x",$0) }.joined()
    }
    private func exists(_ id: String) -> Bool {
        id.hasPrefix("screen:") ? manager.roots[String(id.dropFirst(7))] != nil : manager.panels[id] != nil
    }
    private func advanceOwnLayout(from previous: String, inputID: String, source: NativePanelSource) {
        let current = layoutStamp()
        if inputs[inputID]?.layout == previous { inputs[inputID]?.layout = current }
        for id in owners.keys where owners[id]?.source == source && owners[id]?.layout == previous { owners[id]?.layout = current }
    }
    private func worldStamp(_ targets: [String]) -> String {
        layoutStamp() + "\n" + targets.map { "\($0):\(revisions[$0, default: 0]):\(exists($0))" }.joined(separator: "\n")
    }
    private func layoutStamp() -> String {
        let layout = manager.roots.keys.sorted().map { id in
            let root = manager.roots[id]!
            return "\(id):\(root.state.mode.rawValue):\(root.state.primaryID ?? ""):\(root.state.selectedIDs.sorted()):\(root.state.panelIDs):\(root.state.identityPosition):\(root.bounds.size):\(root.agentTestGridZoom):\(root.globalScrollOffset)"
        }
        let panels = manager.catalog.map { "\($0.id):\(manager.assignments[$0.id] ?? "")" }
        return (layout + panels).joined(separator: "\n")
    }
    private func intentContext(_ command: WorkspaceAgentCommand, human: NativePanelHumanContext, targets: [String], source: NativePanelSource) -> [String: UserViewValue] {
        var details: [String: UserViewValue] = [:]
        switch command {
        case let .close_panel(_, discard), let .flowchart_new(_, discard), let .flowchart_open(_, _, discard): details["discardChanges"] = .boolean(discard)
        case let .set_mode(_, mode): details["mode"] = .string(mode.rawValue)
        case let .browser_control(_, action): details["action"] = .string(action.rawValue)
        case let .browser_navigate(_, address): details["address"] = .string(address)
        case let .identity_set_state(_, state): details["state"] = .string(state.rawValue)
        case let .chart_set_series(_, names): details["names"] = .strings(names)
        case let .chart_set_bands(_, bands):
            details["bands"] = .array(bands.map { .object(["firstSeriesName":.string($0.firstSeriesName),"secondSeriesName":.string($0.secondSeriesName),"opacity":.number($0.opacity)]) })
        case let .chart_viewport(_, zoom, pan): details["zoom"] = .number(zoom); details["pan"] = .number(pan)
        case let .image_select(_, index), let .image_expand(_, index): details["index"] = .number(Double(index))
        case let .image_viewport(_, zoom, x, y), let .flowchart_viewport(_, zoom, x, y):
            details["zoom"] = .number(zoom); details["panX"] = .number(x); details["panY"] = .number(y)
        case let .grid_viewport(_, zoom, offset): details["zoom"] = .number(zoom); details["scrollOffset"] = .number(offset)
        case let .conversation_select_session(_, sessionID): details["sessionID"] = .string(sessionID)
        case let .move_panels(_, _, row, column):
            details["row"] = row.map { .number(Double($0)) } ?? .null; details["column"] = column.map { .number(Double($0)) } ?? .null
        default: break
        }
        if case let .mutation(category, _, _) = command.panelEffect { details["category"] = .string(category) }
        let snapshot = inputs[human.inputID]
        let original = (snapshot?.catalog ?? []).compactMap(\.objectValue).filter {
            snapshot?.activeScreenID == nil || $0["screenID"] == snapshot?.activeScreenID.map(UserViewValue.string)
        }
        // These facts describe pointing, never authorization or data validity.
        let pointing = WorkspacePanel.Kind.allCases.compactMap { kind -> UserViewValue? in
            let panels = original.filter { $0["kind"] == .string(kind.rawValue) }
            guard !panels.isEmpty else { return nil }
            let selected = panels.filter { $0["selected"] == .boolean(true) }
            let focused = panels.filter { $0["focused"] == .boolean(true) }
            let targets = selected.isEmpty ? focused : selected
            return .object(["kind": .string(kind.rawValue), "targetIDs": .strings(targets.compactMap { $0["id"]?.stringValue }),
                            "method": .string(selected.isEmpty ? focused.isEmpty ? "none" : "focused" : "selected"),
                            "unique": .boolean(targets.count == 1)])
        }
        return ["humanInputID": .string(human.inputID), "humanText": .string(human.text),
                "effectCategory": details["category"] ?? .null,
                "requiresDiscardConsent": .boolean(requiresDiscardConsent(command, targets: targets)),
                "command": .string(command.name), "targetIDs": .strings(targets), "operationDetails": .object(details),
                "allowedActionEvidence": .strings(command.allowedActionEvidence),
                "operationDescription": .string(WorkspaceAgentToolDefinitions.all.first(where: { $0.command == command.name })?.description ?? command.name),
                "panelsAtHumanRequest": .array(inputs[human.inputID]?.catalog ?? []),
                "deicticTargetsAtHumanRequest": .array(pointing),
                "activeScreenIDAtHumanRequest": inputs[human.inputID]?.activeScreenID.map(UserViewValue.string) ?? .null,
                "createdThisInvocation": .strings(owners.filter { $0.value.source == source && $0.value.initial }.map(\.key)),
                "panels": .array(panelCatalog()),
                "screens": .array(manager.roots.keys.sorted().map { id in .object([
                    "id": .string("screen:" + id), "mode": .string(manager.roots[id]!.state.mode.rawValue),
                    "primaryID": .string(manager.roots[id]!.state.primaryID ?? "")]) })]
    }
    private func panelCatalog() -> [UserViewValue] {
        manager.catalog.map { panel in .object([
                    "id": .string(panel.id), "title": .string(panel.title), "kind": .string(panel.kind.rawValue),
                    "screenID": .string(manager.assignments[panel.id] ?? ""),
                    "selected": .boolean(manager.roots.values.contains { $0.state.selectedIDs.contains(panel.id) }),
                    "focused": .boolean(manager.roots.values.contains { $0.state.mode != .grid && $0.state.primaryID == panel.id })]) }
    }
    private func fail(_ code: String, _ message: String) -> WorkspaceAgentFailure { .init(code: code, message: message) }

    private func appendOperationReceipts(to response: inout WorkspaceAgentResponse, command: WorkspaceAgentCommand, source: NativePanelSource) {
        guard operationProtocolEnabled?() != false, let operationJournal else { return }
        let panelID: String?
        if case let .read_panel(id) = command { panelID = id } else if case .get_user_view = command { panelID = nil } else { return }
        let rows = operationJournal.operations.filter { row in
            (panelID == nil || row.targets.contains(panelID!)) && row.source.product?.taskID == source.product?.taskID
        }.suffix(16)
        response.operationReceipts = rows.filter { !$0.acknowledged && [.completed, .failedNoChange].contains($0.phase) }
            .map { .init(id: $0.id, token: $0.acknowledgementToken) }
        response.result["operationHistory"] = .array(rows.map { row in
            var value: [String: UserViewValue] = ["id": .string(row.id), "targets": .strings(row.targets), "phase": .string(row.phase.rawValue),
                "historical": .boolean(true), "currentStateMatches": .boolean(row.category != "identity" && !row.targets.contains { manager.panels[$0]?.browserModel != nil || manager.panels[$0]?.conversationHistoryModel != nil } && row.instanceID == instanceID && row.afterStamp == NativePanelOperationJournal.stamp(worldStamp(row.targets)))]
            if let data = row.responseData, let original = try? JSONDecoder().decode(UserViewValue.self, from: data) { value["response"] = original }
            return .object(value)
        })
    }

    private func requiresDiscardConsent(_ command: WorkspaceAgentCommand, targets: [String]) -> Bool {
        switch command {
        case let .close_panel(_, discard), let .flowchart_new(_, discard), let .flowchart_open(_, _, discard):
            return discard && targets.contains { manager.panels[$0]?.flowchartModel?.isDirty == true }
        default: return false
        }
    }

    private func groundedTarget(_ evidence: String, targets: [String], inputID: String) -> Bool {
        let text = evidence.lowercased()
        let deictic = ["這張", "這個", "這份", "這些", "這幅", "這頁", "該面板", "目前選取", "當前選取", "this ", "that ", "selected ", "current "]
        let all = ["所有面板", "全部面板", "all panels", "all charts", "所有圖表", "全部圖表"].contains(where: text.contains)
        return targets.allSatisfy { id in
            if id.hasPrefix("screen:") {
                return ["窗口", "視窗", "螢幕", "屏幕", "工作區", "全局", "排列", "screen", "window", "workspace", "grid", id.lowercased()].contains(where: text.contains)
            }
            guard let panel = manager.catalog.first(where: { $0.id == id }) else { return false }
            if deictic.contains(where: text.contains) {
                let snapshot = inputs[inputID]
                let explicitOtherWindow = ["另一個窗口", "另一個視窗", "另一個螢幕", "另一個屏幕", "other window", "other screen"].contains(where: text.contains)
                let original = (snapshot?.catalog ?? []).compactMap(\.objectValue).filter {
                    $0["kind"] == .string(panel.kind.rawValue) && (explicitOtherWindow || snapshot?.activeScreenID == nil || $0["screenID"] == snapshot?.activeScreenID.map(UserViewValue.string))
                }
                let selected = original.filter { $0["selected"] == .boolean(true) }
                let pointed = selected.isEmpty ? original.filter { $0["focused"] == .boolean(true) } : selected
                guard pointed.contains(where: { $0["id"] == .string(id) }) else { return false }
            }
            return all || text.contains(id.lowercased()) || text.contains(panel.title.lowercased())
                || references(panel.kind).contains(where: text.contains) || deictic.contains(where: text.contains)
        }
    }

    private func references(_ kind: WorkspacePanel.Kind) -> [String] {
        switch kind {
        case .chart: ["圖表", "图表", "折線圖", "折线图", "走勢圖", "走势图", "股價圖", "股价图", "chart", "graph", "plot"]
        case .notes: ["筆記", "笔记", "便條", "便条", "備忘", "备忘", "note", "memo"]
        case .canvas: ["流程圖", "流程图", "畫布", "画布", "flowchart", "diagram", "canvas"]
        case .imageGallery: ["圖片", "图片", "相簿", "圖庫", "图库", "image", "gallery", "photo"]
        case .browser: ["網頁", "网页", "瀏覽器", "浏览器", "browser", "webpage", "page"]
        case .document: ["文檔", "文档", "文件", "報告", "报告", "document", "report"]
        case .table: ["表格", "資料表", "数据表", "table"]
        case .conversationHistory: ["聊天", "對話", "对话", "chat", "conversation"]
        case .agentIdentity: ["形象", "頭像", "头像", "avatar", "identity"]
        case .agentCoreTest: ["核心動畫", "core animation"]
        case .agentActivity: ["行為紀錄", "日誌", "log", "activity"]
        case .taskProgress: ["任務進度", "進度", "progress"]
        }
    }

    private func watchModels() {
        for (id, panel) in manager.panels {
            let identity = ObjectIdentifier(panel)
            if observers[id]?.0 == identity { continue }
            var tokens: [AnyCancellable] = []
            func watch<P: Publisher>(_ publisher: P) where P.Failure == Never {
                tokens.append(publisher.dropFirst().sink { [weak self] _ in
                    MainActor.assumeIsolated { self?.revisions[id, default: 0] += 1 }
                })
            }
            if let model = panel.sampleContentModel { watch(model.$note) }
            if let model = panel.chartModel {
                watch(model.$data); watch(model.$visibleSeries); watch(model.$filledBands); watch(model.$xZoom); watch(model.$xPan)
            }
            if let model = panel.imageGalleryModel {
                watch(model.$images); watch(model.$selectedIndex); watch(model.$expandedIndex); watch(model.$zoomScale); watch(model.$panOffset)
            }
            if let model = panel.browserModel { watch(model.$addressDraft); watch(model.$currentURL) }
            if let model = panel.flowchartModel {
                watch(model.$nodes); watch(model.$connections); watch(model.$selectedNodeIDs); watch(model.$zoom); watch(model.$panOffset); watch(model.$isDirty)
            }
            if let model = panel.conversationHistoryModel { watch(model.$currentSessionID) }
            revisions[id, default: 0] += 1
            observers[id] = (identity, tokens)
        }
        for id in observers.keys where manager.panels[id] == nil {
            observers.removeValue(forKey: id); revisions[id, default: 0] += 1
        }
    }
}
