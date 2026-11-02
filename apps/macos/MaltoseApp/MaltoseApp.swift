import SwiftUI
import Darwin

@main struct MaltoseApp: App {
    @NSApplicationDelegateAdaptor(WorkspaceAppDelegate.self) var appDelegate
    var body: some Scene {
        Settings { EmptyView() }
            .commands {
                CommandGroup(replacing: .appSettings) {}
                CommandGroup(replacing: .newItem) {}
                CommandMenu("工作空間") {
                    Button("等大排列") { appDelegate.workspace?.showGrid() }
                        .keyboardShortcut("1", modifiers: .command)
                    Button("切換原生全螢幕") { appDelegate.workspace?.enterFullscreenForActiveWindow() }
                        .keyboardShortcut("f", modifiers: [.control, .command])
                    Button("重新啟動主 Agent") {
                        appDelegate.runtime.stop { appDelegate.runtime.startApplication() }
                    }
                    Button("顯示所有窗口") { appDelegate.workspace?.showWindows() }
                }
                CommandMenu("Codex") {
                    Button("登入 Codex…") { appDelegate.session?.login() }
                    Button("選擇 Codex 模型…") { appDelegate.chooseCodexModel() }
                    Button("重試協作連線") { appDelegate.session?.retry() }
                    Button("選擇開發專案並交接…") { appDelegate.chooseDevelopmentRepository() }
                    Divider()
                    Button("開始新的開發任務") { appDelegate.session?.newTask() }
                    Button("選擇開發任務…") { appDelegate.chooseCodexTask() }
                    Button("待確認訊息…") { appDelegate.reviewPendingInput() }
                    Button("允許 Codex 匯出面板至檔案…") { appDelegate.chooseCodexPanelAccess() }
                    Divider()
                    Button("停止目前 Codex 工作") { appDelegate.session?.stopTask() }
                    Button("交回麥芽糖") { _ = appDelegate.session?.submit("@maltose") }
                }
                CommandMenu("面板") {
                    Button("工作日誌") { appDelegate.workspace?.showWorkPanel(.agentActivity) }
                    Button("任務進度") { appDelegate.workspace?.showWorkPanel(.taskProgress) }
                    Divider()
                    Button("核心動畫測試…") { appDelegate.workspace?.showCoreAnimationTest() }
                        .keyboardShortcut("0", modifiers: [.command, .option])
                    Button("UI 感知測試…") { appDelegate.workspace?.showUserViewTest() }
                        .keyboardShortcut("v", modifiers: [.command, .option])
                }
            }
    }
}

@MainActor final class WorkspaceAppDelegate: NSObject, NSApplicationDelegate {
    var workspace: WorkspaceWindowManager?
    let runtime = RuntimeSupervisor()
    let approvals = RuntimeApprovalCoordinator()
    let codexInteractions = CodexInteractionCoordinator()
    var session: AgentSessionCoordinator?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let previewCount = CommandLine.arguments.first(where: { $0.hasPrefix("--panel-count=") })
            .flatMap { Int($0.dropFirst("--panel-count=".count)) }
        let uiOnly = CommandLine.arguments.contains("--ui-only")
        var workspaceStore: WorkspaceSessionStore?
        var savedWorkspace: WorkspaceSession?
        var workspaceLoadFailed = false
        if !uiOnly {
            do {
                let store = WorkspaceSessionStore(url: try RuntimeLaunchConfiguration.supportDirectory().appendingPathComponent("workspace/session.json"))
                savedWorkspace = try store.load()
                workspaceStore = store
            } catch { workspaceLoadFailed = true }
        }
        let samples = previewCount.map(WorkspacePanel.previewSamples(count:)) ?? savedWorkspace?.panels.map(\.descriptor) ?? WorkspacePanel.initial
        workspace = WorkspaceWindowManager(catalog: samples, automaticallyFullscreen: !CommandLine.arguments.contains("--windowed"))
        workspace?.restoresOpenPanelsOnly = !uiOnly
        workspace?.synchronize()
        if savedWorkspace == nil, previewCount == nil { workspace?.applyInitialLayout() }
        exportWorkspaceTestSnapshotIfRequested()
        runtime.onStateChange = { [weak self] state in
            for root in self?.workspace?.roots.values ?? [:].values { root.setRuntimeStatus(state.title) }
            if state != .ready { self?.approvals.reset() }
            if state == .ready { self?.session?.runtimeReady() }
            self?.session?.refreshPresentation()
        }
        approvals.send = { [weak self] action, value, completion in
            self?.runtime.submitUIAction(action, value: value, completion: completion) ?? false
        }
        approvals.onIssue = { [weak self] message in
            for root in self?.workspace?.roots.values ?? [:].values { root.setRuntimeStatus(message) }
        }
        if !CommandLine.arguments.contains("--ui-only") {
            do {
                let journal = try RuntimeLaunchConfiguration.supportDirectory().appendingPathComponent("conversations/runtime.jsonl")
                try workspace?.prepareLiveConversation(at: journal)
                let store = CodexTaskStore(url: try RuntimeLaunchConfiguration.supportDirectory().appendingPathComponent("collaboration/tasks.json"))
                let adapter = try CodexAdapter(connection: CodexConnection(), store: store)
                let coordinator = try AgentSessionCoordinator(runtime: runtime, codex: adapter)
                coordinator.emit = { [weak self] in try self?.workspace?.receiveRuntimeEvent($0) }
                coordinator.onPresentation = { [weak self] recipient, status in
                    self?.workspace?.setAgentPresentation(recipient: recipient, status: status)
                    if self?.session?.conversation.phase != .maltoseActive { self?.approvals.reset() }
                }
                coordinator.openLoginURL = { NSWorkspace.shared.open($0) }
                coordinator.onInteraction = { [weak self] _, request in self?.codexInteractions.receive(request) }
                coordinator.onInteractionResolved = { [weak self] id in self?.codexInteractions.resolved(id) }
                codexInteractions.send = { [weak coordinator] request, result in coordinator?.respond(to: request, result: result) ?? false }
                codexInteractions.onIssue = { [weak self] message in self?.workspace?.setAgentPresentation(recipient: self?.session?.recipientLabel ?? "Maltose", status: message) }
                session = coordinator
                if let workspace {
                    // The collaboration writer lock must be acquired before saving workspace state.
                    if let workspaceStore { workspace.restoreSession(savedWorkspace, store: workspaceStore) }
                    if workspaceLoadFailed {
                        workspace.workMonitor.append(engine: "Maltose", text: "上次的工作區紀錄無法讀取，已保留原紀錄，先開啟形象、聊天與工作日誌。", failed: true)
                    }
                    coordinator.installWorkMonitoring(workspace.workMonitor)
                    workspace.workMonitor.onSelectTask = { [weak workspace] _ in
                        guard let workspace else { return }
                        workspace.showWorkPanel(.taskProgress)
                    }
                }
                if let interface = workspace?.agentInterface { coordinator.installPanelPolicy(interface.panelPolicy) }
                coordinator.readResultPublication = { [weak self] id in self?.workspace?.liveConversationModel?.resultDeliveries[id] }
                workspace?.validateResultPublication = { [weak coordinator] record in
                    guard let coordinator else { throw CodexTaskStoreError.conflict }
                    try coordinator.validateContinuationPublication(record)
                }
            }
            catch {
                for root in workspace?.roots.values ?? [:].values { root.setRuntimeStatus("無法開啟對話與協作紀錄：\(error.localizedDescription)") }
                return
            }
            workspace?.onSubmitText = { [weak self] text in
                self?.session?.submit(text) ?? false
            }
            runtime.onPanelCommand = { [weak self] request, fileTransfer in
                guard let workspace = self?.workspace else {
                    return WorkspaceAgentResponse(requestID: request.requestID, ok: false, error: .init(code: "unavailable", message: "工作區已關閉。"))
                }
                return await workspace.agentInterface.handleAgent(request, fileTransfer: fileTransfer)
            }
            runtime.onEvent = { [weak self] data in
                do {
                    try self?.session?.receiveRuntime(data)
                    if self?.session?.conversation.phase == .maltoseActive,
                       self?.runtime.autonomy?.state != .paused, self?.runtime.autonomy?.state != .pausing { self?.approvals.receive(data) }
                }
                catch { self?.session?.eventFailed(error.localizedDescription) }
            }
            runtime.startApplication()
        }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        workspace?.showWindows()
        return true
    }

    /// A UI-only fixture exercises the real SwiftUI/AppKit application lifecycle.
    /// It never opens the user's runtime, conversations, credentials or databases.
    private func exportWorkspaceTestSnapshotIfRequested() {
        guard CommandLine.arguments.contains("--ui-only"),
              let argument = CommandLine.arguments.first(where: { $0.hasPrefix("--workspace-test-snapshot=") }),
              let nonceArgument = CommandLine.arguments.first(where: { $0.hasPrefix("--workspace-test-nonce=") }) else { return }
        let path = String(argument.dropFirst("--workspace-test-snapshot=".count))
        let nonce = String(nonceArgument.dropFirst("--workspace-test-nonce=".count))
        guard path.hasPrefix("/"), UUID(uuidString: nonce) != nil else { return }
        Task { @MainActor [weak self] in
            guard let self, let workspace = self.workspace else { return }
            let deadline = Date().addingTimeInterval(25)
            while workspace.transitioningScreenID != nil || workspace.fullscreenAwaitingActivation != nil, Date() < deadline {
                try? await Task.sleep(for: .milliseconds(100))
            }
            let screens = NSScreen.screensHaveSeparateSpaces ? NSScreen.screens : Array(NSScreen.screens.prefix(1))
            let windows: [[String: Any]] = workspace.windows.map { id, window in
                ["screenID": id, "nativeFullscreen": window.styleMask.contains(.fullScreen),
                 "rootNativeFullscreen": workspace.roots[id]?.nativeFullscreen == true, "opaque": window.isOpaque]
            }
            let result: [String: Any] = ["schemaVersion": 1, "nonce": nonce,
                "eligibleScreens": screens.map(WorkspaceWindowManager.screenID), "windows": windows,
                "panels": workspace.catalog.map { ["id": $0.id, "kind": $0.kind.rawValue] },
                "failures": Array(workspace.fullscreenFailures), "transitioning": workspace.transitioningScreenID != nil || workspace.fullscreenAwaitingActivation != nil,
                "diagnostics": workspace.fullscreenDiagnostics,
                "applicationRunning": NSApp.isRunning, "applicationActive": NSApp.isActive]
            if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]) {
                let fd = Darwin.open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
                if fd >= 0 {
                    let file = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
                    try? file.write(contentsOf: data); try? file.synchronize(); try? file.close()
                }
            }
            NSApp.terminate(nil)
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if runtime.processID == nil && session?.codex.connection.processID == nil { return .terminateNow }
        if let session { session.shutdown { [weak self] in self?.runtime.stop { sender.reply(toApplicationShouldTerminate: true) } } }
        else { runtime.stop { sender.reply(toApplicationShouldTerminate: true) } }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) { approvals.reset(); codexInteractions.reset(); workspace?.stop(); session?.store.close() }

    func chooseCodexTask() {
        guard let session else { return }
        let tasks = session.taskChoices
        guard !tasks.isEmpty else { return }
        let alert = NSAlert(); alert.messageText = "選擇 Codex 開發任務"
        let picker = NSPopUpButton(frame: .init(x: 0, y: 0, width: 460, height: 28))
        for task in tasks { picker.addItem(withTitle: "\(task.delegation.objective.prefix(50)) · \(task.id.uuidString.prefix(8))") }
        alert.accessoryView = picker; alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "選取")
        guard let window = workspace?.activeRoot?.window else { return }
        alert.beginSheetModal(for: window) { response in
            if response == .alertSecondButtonReturn, tasks.indices.contains(picker.indexOfSelectedItem) { session.selectTask(tasks[picker.indexOfSelectedItem].id) }
        }
    }

    func chooseCodexModel() {
        guard let session else { return }
        Task { @MainActor [weak self] in
            do {
                let models = try await session.modelChoices(forceRefresh: true)
                guard !models.isEmpty, let window = self?.workspace?.activeRoot?.window else { return }
                let alert = NSAlert(); alert.messageText = "選擇 Codex 模型"
                alert.informativeText = "套用至新的開發任務。現有任務保留原模型；清單是否可實際使用，仍以服務回覆為準。"
                let picker = NSPopUpButton(frame: .init(x: 0, y: 0, width: 460, height: 28))
                for model in models { picker.addItem(withTitle: model.displayName + (model.isDefault ? "（建議預設）" : "")) }
                if let index = models.firstIndex(where: { $0.model == session.store.preferredModel }) { picker.selectItem(at: index) }
                alert.accessoryView = picker; alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "選取")
                alert.beginSheetModal(for: window) { [weak self] response in
                    guard response == .alertSecondButtonReturn, models.indices.contains(picker.indexOfSelectedItem) else { return }
                    do { try session.selectModel(models[picker.indexOfSelectedItem].model) }
                    catch { self?.workspace?.setAgentPresentation(recipient: session.recipientLabel, status: error.localizedDescription) }
                }
            } catch { self?.workspace?.setAgentPresentation(recipient: session.recipientLabel, status: error.localizedDescription) }
        }
    }

    func chooseCodexPanelAccess() {
        guard let session, let id = session.conversation.activeTaskID,
              let task = session.store.task(id), let runtimeID = runtime.sessionID,
              let leaseID = runtime.autonomy?.leaseID, runtime.autonomy?.state == .paused,
              let window = workspace?.activeRoot?.window else { return }
        let alert = NSAlert(); alert.messageText = "允許 Codex 匯出面板至檔案？"
        alert.informativeText = "目前任務：\(task.delegation.objective.prefix(200))\n\n授權適用於這次交接中的目前任務；交回麥芽糖或重新啟動後失效。個人記憶與檔案權限仍使用原有規則。"
        alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "允許匯出"); alert.addButton(withTitle: "撤回匯出授權")
        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertSecondButtonReturn || response == .alertThirdButtonReturn else { return }
            do { try session.setPanelContextConsent(for: id, runtimeSessionID: runtimeID, leaseID: leaseID, allowed: response == .alertSecondButtonReturn) }
            catch { self?.workspace?.setAgentPresentation(recipient: session.recipientLabel, status: error.localizedDescription) }
        }
    }

    func chooseDevelopmentRepository() {
        let picker = NSOpenPanel(); picker.canChooseFiles = false; picker.canChooseDirectories = true; picker.allowsMultipleSelection = false
        picker.message = "選擇 Git 專案根目錄。確認後麥芽糖會暫停自主工作，後續開發交給 Codex；原有修改會保留在獨立工作目錄。"
        picker.prompt = "選取並交接"
        guard let window = workspace?.activeRoot?.window else { return }
        picker.beginSheetModal(for: window) { [weak self] response in
            if response == .OK, let url = picker.url { self?.session?.selectRepository(url) }
        }
    }

    func reviewPendingInput() {
        guard let session else { return }
        let inputs = session.deferredInputs
        guard !inputs.isEmpty else { return }
        let alert = NSAlert(); alert.messageText = "選擇待確認訊息"
        let picker = NSPopUpButton(frame: .init(x: 0, y: 0, width: 460, height: 28))
        for (index, input) in inputs.enumerated() { picker.addItem(withTitle: "\(index + 1). \(input.text.prefix(50))") }
        alert.accessoryView = picker; alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "檢視")
        guard let window = workspace?.activeRoot?.window else { return }
        alert.beginSheetModal(for: window) { [weak self] response in
            if response == .alertSecondButtonReturn, inputs.indices.contains(picker.indexOfSelectedItem) { self?.reviewInput(inputs[picker.indexOfSelectedItem]) }
        }
    }

    private func reviewInput(_ input: AgentInputRecord) {
        let alert = NSAlert(); alert.messageText = "待確認訊息"
        alert.informativeText = (input.delivery == .uncertain ? "這則訊息可能已送出，請先核對任務狀態，避免重複執行。\n\n" : "這則訊息尚未送出。\n\n") + input.text
        alert.addButton(withTitle: "保留"); alert.addButton(withTitle: "放入輸入欄編輯"); alert.addButton(withTitle: "略過此訊息")
        guard let window = workspace?.activeRoot?.window else { return }
        alert.beginSheetModal(for: window) { [weak self] response in
            if response == .alertSecondButtonReturn {
                self?.workspace?.activeRoot?.restoreUnconfirmedDraft((input.recipient == .codex ? "@codex " : "@maltose ") + input.text)
                self?.session?.markInputReviewed(input.id, disposition: .movedToDraft)
            } else if response == .alertThirdButtonReturn { self?.session?.markInputReviewed(input.id, disposition: .dismissed) }
        }
    }
}
