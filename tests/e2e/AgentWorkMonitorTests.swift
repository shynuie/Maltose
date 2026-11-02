import AppKit
import SwiftUI
import XCTest
@testable import MaltoseApp

@MainActor final class AgentWorkMonitorTests: XCTestCase {
    private func fixture() throws -> (CodexTaskStore, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-work-monitor-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = CodexTaskStore(url: directory.appendingPathComponent("tasks.json")); try store.open()
        _ = try store.ensureConversation("conversation")
        return (store, directory)
    }
    private func create(_ store: CodexTaskStore, name: String = "研究半年民調並製作報告", parentID: UUID? = nil) throws -> ProductTask {
        let input = AgentInputRecord(id: UUID().uuidString, text: name, author: .user, origin: .native, speakerID: nil,
            speakerStatus: nil, runtimeSessionID: nil, recipient: .maltose, delivery: .accepted)
        try store.enqueue(input, conversationID: "conversation")
        return try store.beginProductTask(conversationID: "conversation", inputID: input.id,
            plan: .init(sourceInputID: input.id, criteria: ["交付已核對的報告"], steps: [
                .init(id: "sources", title: "收集與比較來源"),
                .init(id: "report", title: "製作報告"),
                .init(id: "chart", title: "建立圖表", parentID: "report"),
                .init(id: "conclusion", title: "整理結論", parentID: "report")]), parentID: parentID, forceNew: true)
    }
    private func start(_ store: CodexTaskStore, task: ProductTask) throws {
        try store.recordProductExecution(task.id, .init(id: "main:\(task.id)", engine: .main, externalID: "runtime",
            inputID: task.requirements[0].inputID, requirementsRevision: 1, planVersion: 1, state: .running))
    }
    private func complete(_ store: CodexTaskStore, task: ProductTask) throws {
        let execution = ProductExecution(id: "main:\(task.id)", engine: .main, externalID: "runtime", inputID: task.requirements[0].inputID,
            requirementsRevision: 1, planVersion: 1, state: .succeeded)
        try store.recordProductReport(task.id, execution: execution,
            evidence: [.init(id: "evidence", executionID: execution.id, kind: .artifact, source: .observed, verdict: .passed, detail: "測試成果")],
            outcome: .init(id: "result", executionID: execution.id, requirementsRevision: 1, planVersion: 1,
                reportedState: .partial, summary: "已產生報告", remaining: []))
        _ = try store.assessProductOutcome(task.id, outcomeID: "result", assessment: .init(status: "completed", summary: "符合需求",
            checks: task.completionCriteria.map { .init(criterion: $0, evidenceIDs: ["evidence"]) }, remaining: [], resolvedFailures: [:], explanation: "已核對測試成果"),
            expectedRequirementsRevision: 1, expectedPlanVersion: 1)
    }

    func testProgressOpensForUnfinishedTasksAndStateChangesWithoutRepeatedlyStealingFocus() throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native panels") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        let manager = WorkspaceWindowManager(catalog: WorkspacePanel.initial, automaticallyFullscreen: false)
        manager.synchronize(); defer { manager.stop() }
        manager.selectPanel("chat")
        let screen = try XCTUnwrap(manager.assignments["chat"])
        XCTAssertNil(manager.catalog.first { $0.kind == .taskProgress })
        manager.workMonitor.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertEqual(manager.catalog.filter { $0.kind == .taskProgress }.count, 1)
        XCTAssertEqual(manager.roots[screen]?.state.primaryID, "chat")
        XCTAssertTrue(manager.closePanel("task-progress"))
        manager.workMonitor.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertNil(manager.panels["task-progress"], "An unchanged snapshot must respect a manual close")
        try start(store, task: task)
        manager.workMonitor.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertNotNil(manager.panels["task-progress"])
        XCTAssertEqual(manager.catalog.first { $0.kind == .taskProgress }?.title, "任務進度")
        try complete(store, task: task)
        manager.workMonitor.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertTrue(manager.closePanel("task-progress"))
        let restarted = AgentWorkMonitor()
        var requests = 0; restarted.onProgressNeeded = { requests += 1 }
        restarted.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertEqual(requests, 0, "Completed tasks do not open a progress panel on restart")
        let unfinished = try create(store, name: "尚未完成的任務")
        try store.setProductHeld(unfinished.id, held: true)
        restarted.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertEqual(requests, 1, "Paused unfinished tasks remain discoverable on restart")
    }

    func testMultipleTasksAndNestedStepsUseStableIDsAndActualCompletion() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let parent = try create(store), child = try create(store, name: "比較調查方法", parentID: parent.id)
        _ = try create(store, name: "改善圖表功能")
        try start(store, task: parent)
        let model = AgentWorkMonitor(); model.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertEqual(model.roots.count, 2)
        XCTAssertTrue(model.rows.contains { $0.depth == 2 && $0.node.title == "建立圖表" })
        XCTAssertTrue(model.rows.contains { $0.node.taskID == child.id && $0.depth == 1 })
        let root = try XCTUnwrap(model.roots.first { $0.taskID == parent.id }); XCTAssertNil(root.fraction)
        try store.recordStepProgress(parent.id, stepID: "sources", state: .completed, detail: "3 個來源已比較")
        model.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertGreaterThan(try XCTUnwrap(model.roots.first { $0.taskID == parent.id }?.fraction), 0)
        XCTAssertNotEqual(model.roots.first { $0.taskID == parent.id }?.state, .completed)
        XCTAssertTrue(model.entries.contains { $0.text.contains("收集與比較來源") })
        model.toggle(root.id); XCTAssertFalse(model.rows.contains { $0.node.id == "step:\(parent.id):sources" })
        model.selectTask(parent.id); XCTAssertTrue(model.rows.contains { $0.node.id == "step:\(parent.id):sources" })
    }

    func testTaskProgressScrollsIndependentlyInGridFocusedAndSidebarModes() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native panels") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        for n in 0..<15 { let task = try create(store, name: "測試任務 \(n)"); try start(store, task: task) }
        let manager = WorkspaceWindowManager(catalog: WorkspacePanel.initial, automaticallyFullscreen: false)
        manager.synchronize(); defer { manager.stop() }
        manager.workMonitor.update(tasks: store.productTasks, codexTasks: [])
        let panel = try XCTUnwrap(manager.panels["task-progress"])
        let screen = try XCTUnwrap(manager.assignments[panel.surfaceID])
        let root = try XCTUnwrap(manager.roots[screen])
        func findScroll(_ view: NSView) -> NSScrollView? {
            if let scroll = view as? NSScrollView { return scroll }
            return view.subviews.lazy.compactMap { findScroll($0) }.first
        }
        for mode in [WorkspaceMode.grid, .focused, .sidebar] {
            manager.selectPanel(panel.surfaceID); manager.setWorkspaceMode(mode, on: screen)
            try await Task.sleep(for: .milliseconds(150))
            root.layoutSubtreeIfNeeded(); manager.windows[screen]?.displayIfNeeded()
            let scroll = try XCTUnwrap(findScroll(panel.contentView))
            let document = try XCTUnwrap(scroll.documentView)
            XCTAssertGreaterThan(document.bounds.height, scroll.contentView.bounds.height)
            let gridOffset = root.globalScrollOffset
            document.scroll(.zero); scroll.reflectScrolledClipView(scroll.contentView)
            document.scroll(CGPoint(x: 0, y: 160)); scroll.reflectScrolledClipView(scroll.contentView)
            XCTAssertGreaterThan(scroll.contentView.bounds.minY, 0)
            XCTAssertEqual(root.globalScrollOffset, gridOffset)
            XCTAssertEqual(WorkspaceScrollAction.route(mode: mode, isInsideGrid: true, isCovered: false,
                isInsideScrollablePanel: WorkspacePanel.Kind.taskProgress.scrollsContentInGrid, controlPressed: false, deltaY: -20), .passThrough)
        }
        XCTAssertEqual(WorkspaceScrollAction.route(mode: .grid, isInsideGrid: true, isCovered: false,
            isInsideScrollablePanel: WorkspacePanel.Kind.taskProgress.scrollsContentInGrid, controlPressed: true, deltaY: 20), .zoom(20))
    }

    func testFullCircleAndCheckOnlyFollowCanonicalCompletionAndPausedRingsStop() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try start(store, task: task)
        for step in task.plan.steps { try store.recordStepProgress(task.id, stepID: step.id, state: .completed, detail: "步驟已完成") }
        let model = AgentWorkMonitor(); model.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertNotEqual(model.roots.first?.state, .completed)
        XCTAssertLessThan(try XCTUnwrap(model.roots.first?.fraction), 1)
        try store.setProductHeld(task.id, held: true); model.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertEqual(model.roots.first?.state, .paused)
        XCTAssertFalse(model.rows.contains { $0.node.state.animated })
        try store.setProductHeld(task.id, held: false); try complete(store, task: task)
        model.update(tasks: store.productTasks, codexTasks: [])
        XCTAssertEqual(model.roots.first?.state, .completed); XCTAssertEqual(model.roots.first?.fraction, 1)
        XCTAssertEqual(model.rows.count, 1, "Completed tasks collapse, keeping their name and checkmark")
    }

    func testProgressSurvivesRestartButNeverClosesTaskAndNewPlanResetsIt() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        try store.recordStepProgress(task.id, stepID: "chart", state: .running, detail: "整理資料")
        XCTAssertThrowsError(try store.recordStepProgress(task.id, stepID: "forged", state: .completed, detail: ""))
        XCTAssertThrowsError(try store.recordStepProgress(task.id, stepID: "chart", state: .completed, detail: String(repeating: "x", count: 1001)))
        store.close(); try store.open()
        XCTAssertEqual(store.productTask(task.id)?.stepProgress?.first?.state, .running)
        XCTAssertNotEqual(store.productTask(task.id)?.state, .completed)
        var plan = task.plan; plan = .init(sourceInputID: plan.sourceInputID, criteria: plan.criteria, steps: [.init(id: "new", title: "新步驟")])
        _ = try store.beginProductTask(conversationID: "conversation", inputID: task.requirements[0].inputID, plan: plan)
        XCTAssertNil(store.productTask(task.id)?.stepProgress)
    }

    func testPlanTreeRejectsMissingParentsAndCyclesWithoutCorruptingStore() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        for steps: [ProductPlanStep] in [[.init(id: "one", title: "錯誤", parentID: "missing")],
            [.init(id: "one", title: "一", parentID: "two"), .init(id: "two", title: "二", parentID: "one")]] {
            XCTAssertThrowsError(try store.beginProductTask(conversationID: "conversation", inputID: task.requirements[0].inputID,
                plan: .init(sourceInputID: task.requirements[0].inputID, criteria: task.plan.criteria, steps: steps)))
        }
        XCTAssertEqual(store.productTask(task.id)?.planVersion, 1)
    }

    func testActivityIsBoundedAndShowsSummariesWithoutToolArgumentsOrRawOutput() throws {
        let model = AgentWorkMonitor()
        let envelope = ConversationHistoryModel.RuntimeEnvelope(schemaVersion: 1, sessionID: "runtime", conversationID: nil, sequence: 1,
            event: .init(type: "tool_started", payload: ["tool": .string("web_search"), "arguments": .string("private-secret"), "stdout": .string("private-output")], timestamp: ""))
        model.receive(envelope); model.receive(envelope)
        XCTAssertEqual(model.entries.count, 1); XCTAssertEqual(model.entries.first?.repetitions, 2)
        XCTAssertEqual(model.entries.first?.text, "搜尋資料 · 開始")
        XCTAssertFalse(model.details(kind: .agentActivity).description.contains("private-"))
        for n in 0..<520 { model.append(engine: "麥芽糖", text: "動作 \(n)") }
        XCTAssertEqual(model.entries.count, 500)
        model.scrollState.manuallyScrolled(to: .zero, atBottom: false, at: 1)
        XCTAssertFalse(model.scrollState.shouldFollow(at: 30)); XCTAssertTrue(model.scrollState.shouldFollow(at: 31))
    }

    func testCodexPlanUsesOnlyCurrentTurnAndKeepsItsTaskAssociation() throws {
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store)
        var codex = CodexTaskRecord(conversationID: "conversation", repositoryPath: "/tmp", worktreePath: "/tmp",
            delegation: .init(objective: "改善圖表功能", constraints: [], acceptanceCriteria: []))
        codex.productTaskID = task.id; codex.activeTurnID = "current"
        try store.recordProductExecution(task.id, .init(id:"codex-execution",engine:.codex,externalID:codex.id.uuidString,
            inputID:task.requirements[0].inputID,requirementsRevision:1,planVersion:1,state:.running))
        let model = AgentWorkMonitor()
        let plan: UserViewValue = .object(["turnId": .string("old"), "plan": .array([.object(["step": .string("失效步驟"), "status": .string("inProgress")])])])
        model.receiveCodex(task: codex, method: "turn/plan/updated", value: plan)
        model.update(tasks: store.productTasks, codexTasks: [codex])
        XCTAssertFalse(model.rows.contains { $0.node.title == "失效步驟" })
        model.receiveCodex(task: codex, method: "turn/plan/updated", value: .object(["turnId": .string("current"), "plan": .array([
            .object(["step": .string("修改圖表"), "status": .string("completed")]), .object(["step": .string("執行測試"), "status": .string("inProgress")])])]))
        model.update(tasks: store.productTasks, codexTasks: [codex])
        XCTAssertTrue(model.rows.contains { $0.node.title == "執行測試" && $0.node.state == .running && $0.node.taskID == task.id })
    }

    func testSharedPanelsReadMoveCloseAndReopenWithoutClearingTheirModels() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires WindowServer") }
        _ = NSApplication.shared
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false); manager.synchronize(); defer { manager.stop() }
        manager.workMonitor.append(engine: "麥芽糖", text: "開始搜尋資料")
        XCTAssertNil(manager.addPanel(kind: .agentActivity), "Activity is a singleton")
        let read = try await manager.readPanel("agent-activity")
        XCTAssertEqual(read["kind"], .string("agentActivity"))
        XCTAssertTrue(read["details"]?["recentEntries"]?.arrayValue?.contains(.string("麥芽糖：開始搜尋資料")) == true)
        XCTAssertTrue(manager.closePanel("agent-activity"))
        manager.showWorkPanel(.agentActivity)
        manager.showWorkPanel(.agentActivity)
        XCTAssertEqual(manager.catalog.filter { $0.kind == .agentActivity }.count, 1)
        XCTAssertEqual(manager.workMonitor.entries.count, 1)
        XCTAssertNotNil(manager.panels["agent-activity"])
        XCTAssertNotNil(manager.panels["task-progress"])
    }

    func testRenderActualTransparentPanelsAndCompletionState() async throws {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires WindowServer") }
        _ = NSApplication.shared
        let (store, directory) = try fixture(); defer { store.close(); try? FileManager.default.removeItem(at: directory) }
        let task = try create(store); try start(store, task: task)
        try store.recordStepProgress(task.id, stepID: "sources", state: .completed, detail: "已取得 3 個來源")
        try store.recordStepProgress(task.id, stepID: "chart", state: .completed, detail: "數值與來源已核對")
        try store.recordStepProgress(task.id, stepID: "conclusion", state: .running, detail: "整理方法差異與結論")
        _ = try create(store, name: "改善圖表功能")
        let model = AgentWorkMonitor(); model.update(tasks: store.productTasks, codexTasks: [])
        model.append(engine: "麥芽糖", text: "已取得半年民調資料，正在比較調查方法", taskID: task.id)
        model.append(engine: "麥芽糖", text: "建立圖表 · 完成", taskID: task.id)
        model.append(engine: "Codex", text: "執行專案指令與檢查")
        let output = URL(fileURLWithPath: ProcessInfo.processInfo.environment["MALTOSE_WORK_PANELS_PREVIEW_DIRECTORY"] ?? "/tmp/maltose-work-panel-previews")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let view = NSHostingView(rootView: HStack(spacing: 40) {
            AgentActivityPanelView(model: model).frame(width: 520)
            TaskProgressPanelView(model: model).frame(width: 650)
        }.padding(30).frame(width: 1270, height: 940).background(Color(white: 0.09)).environment(\.colorScheme, .dark))
        let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 1270, height: 940), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = view
        defer { window.orderOut(nil) }
        view.frame = .init(x: 0, y: 0, width: 1270, height: 940)
        try await Task.sleep(for: .milliseconds(300))
        func capture(_ name: String) throws {
            view.layoutSubtreeIfNeeded()
            let bitmap = try XCTUnwrap(view.bitmapImageRepForCachingDisplay(in: view.bounds))
            view.cacheDisplay(in: view.bounds, to: bitmap)
            try XCTUnwrap(bitmap.representation(using: .png, properties: [:])).write(to: output.appendingPathComponent(name))
        }
        try capture("running.png")
        try complete(store, task: task); model.update(tasks: store.productTasks, codexTasks: [])
        try await Task.sleep(for: .milliseconds(400)); try capture("completed.png")
    }
}
