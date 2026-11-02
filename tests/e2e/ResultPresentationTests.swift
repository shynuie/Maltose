import AppKit
import XCTest
@testable import MaltoseApp

@MainActor final class ResultPresentationTests: XCTestCase {
    private func fixture() throws -> WorkspaceWindowManager {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires native result panels") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let manager = WorkspaceWindowManager(automaticallyFullscreen: false)
        manager.synchronize()
        return manager
    }
    private func publish(_ id: String, title: String = "新結果", markdown: String = "## 結論\n\n完整內容。", in manager: WorkspaceWindowManager) async -> WorkspaceAgentResponse {
        await manager.agentInterface.handle(.init(command: .publish_document(publicationID: id, title: title, markdown: markdown)))
    }

    private var chart: ResultChart {
        .init(title: "虛構半年調查（%）", caption: "來源：使用者提供測試資料，缺月不補值。", xTitle: "月份", series: ["A — 甲 (%)", "A — 乙 (%)"], rows: [
            .init(x: "2026-01", values: [40, 35], note: "測試來源 A：https://example.com/fixture"),
            .init(x: "2026-02", values: [nil, nil], note: "沒有調查，保留空缺"),
            .init(x: "2026-03", values: [42.5, 34], note: "測試來源 A，方法相同")])
    }
    private var chartRecord: ResultDeliveryRecord {
        var value = durableRecord; value.chart = chart; return value
    }

    func testMonthlyChartKeepsCalendarGapsAndOriginalMonthLabelsWithoutInventedObservations() throws {
        let source = ResultChart(title: "月份測試", caption: "僅含一月與六月資料，中間沒有調查。", xTitle: "月份", series: ["比例%"], rows: [
            .init(x: "2026-01", values: [40], note: "日期=2026年1月；使用者提供"),
            .init(x: "2026-06", values: [45], note: "日期=2026年6月；使用者提供")])
        let model = CSVLineChartModel()
        try model.loadResult(source, publicationID: "calendar-gap")
        XCTAssertEqual(model.data.rows.map(\.xLabel), ["2026-01", "2026-06"])
        XCTAssertEqual(model.data.rows.map(\.note), source.rows.map(\.note))
        XCTAssertEqual(model.data.rows[1].xValue - model.data.rows[0].xValue, 151 * 24 * 60 * 60, accuracy: 1)
        XCTAssertEqual(model.data.rows.count, 2)
        XCTAssertNil(CSVLineChartParser.xAxisValue("2026-13"))
        XCTAssertNil(CSVLineChartParser.xAxisValue("0000-01"))
        XCTAssertEqual(CSVLineChartParser.xAxisValue("2026-01"), CSVLineChartParser.xAxisValue("2026-01-01"))
    }

    func testChartAndDocumentPublishTogetherPreserveFocusNotesGapsAndUserChangesOnReplay() throws {
        let url = try journalLocation(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let manager = try fixture(); defer { manager.stop() }
        try manager.prepareLiveConversation(at: url)
        let old = try XCTUnwrap(manager.panels["chart"]?.chartModel)
        let original = old.data.rows.map(\.xLabel)
        manager.selectPanel("notes")
        let screen = try XCTUnwrap(manager.assignments["notes"])
        let primary = manager.roots[screen]?.state.primaryID
        let response = try manager.deliverResult(chartRecord)
        let id = try XCTUnwrap(response["chartPanelID"]?.stringValue)
        let model = try XCTUnwrap(manager.panels[id]?.chartModel)
        XCTAssertNotEqual(id, "chart"); XCTAssertNotNil(manager.panels[chartRecord.panelID!]?.markdownDocumentModel)
        XCTAssertEqual(model.data.rows.count, 3)
        XCTAssertTrue(model.data.rows[1].values.allSatisfy { $0 == nil })
        model.setHoveredPoint(rowIndex: 0, seriesIndex: 0)
        XCTAssertTrue(model.hoveredPoint?.note.contains("https://example.com/fixture") == true)
        XCTAssertEqual(model.resultCaption, chart.caption)
        model.setXAxisViewport(zoom: 3, pan: 2)
        model.toggleSeries(0)
        XCTAssertEqual(try manager.deliverResult(chartRecord)["replayed"], .boolean(true))
        XCTAssertEqual(model.xZoom, 3); XCTAssertEqual(model.xPan, 2); XCTAssertEqual(model.visibleSeries, [1])
        XCTAssertEqual(old.data.rows.map(\.xLabel), original)
        XCTAssertTrue(manager.panels["chart"]?.chartModel === old)
        XCTAssertEqual(manager.roots[screen]?.state.primaryID, primary)
        XCTAssertEqual(manager.liveConversationModel?.currentSession?.messages.count, 1)
    }

    func testChartSavedBeforeCreationRestoresAndClosedChartNeverReopensIndependentlyOfDocument() throws {
        let url = try journalLocation(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let first = try fixture()
        try first.prepareLiveConversation(at: url)
        try first.liveConversationModel?.saveResult(chartRecord)
        XCTAssertNil(first.panels[chartRecord.chartPanelID!]); first.stop()
        let restored = try fixture()
        try restored.prepareLiveConversation(at: url)
        XCTAssertEqual(restored.panels[chartRecord.chartPanelID!]?.chartModel?.data.rows.count, 3)
        XCTAssertTrue(restored.closePanel(chartRecord.chartPanelID!)); restored.stop()
        let events = try String(contentsOf: url, encoding: .utf8).split(separator: "\n").map {
            try JSONDecoder().decode(ConversationHistoryModel.RuntimeEnvelope.self, from: Data($0.utf8)).event.type
        }
        XCTAssertTrue(events.contains("result_chart_closed"))
        XCTAssertFalse(events.contains("result_closed"), "Older builds must ignore a chart closure instead of closing the companion document")
        let closed = try fixture(); defer { closed.stop() }
        try closed.prepareLiveConversation(at: url)
        XCTAssertNil(closed.panels[chartRecord.chartPanelID!])
        XCTAssertNotNil(closed.panels[chartRecord.panelID!])
        XCTAssertEqual(try closed.deliverResult(chartRecord)["chartStatus"], .string("closed"))
        XCTAssertNil(closed.panels[chartRecord.chartPanelID!])
        XCTAssertEqual(closed.liveConversationModel?.currentSession?.messages.count, 1)
    }

    func testInvalidChartOrConflictingReplayCannotWriteJournalOrModifyPanels() throws {
        let url = try journalLocation(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let manager = try fixture(); defer { manager.stop() }; try manager.prepareLiveConversation(at: url)
        try manager.deliverResult(chartRecord)
        let before = try Data(contentsOf: url); let ids = Set(manager.panels.keys)
        var changed = chartRecord
        changed.chart = .init(title: chart.title, caption: chart.caption, xTitle: chart.xTitle, series: chart.series,
            rows: [.init(x: "x", values: [99, 30], note: "changed"), .init(x: "y", values: [nil, 40], note: "changed")])
        XCTAssertThrowsError(try manager.deliverResult(changed))
        var invalid = chartRecord
        invalid.chart = .init(title: chart.title, caption: chart.caption, xTitle: chart.xTitle, series: chart.series,
            rows: [.init(x: "x", values: [.infinity, 3], note: "source"), .init(x: "y", values: [1], note: "source")])
        XCTAssertThrowsError(try manager.deliverResult(invalid))
        XCTAssertEqual(try Data(contentsOf: url), before); XCTAssertEqual(Set(manager.panels.keys), ids)
    }

    func testNewResultsCreateSeparateDocumentsAndPreserveExistingContentAndFocus() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let existing = try XCTUnwrap(manager.panels["document"]?.markdownDocumentModel)
        let before = existing.blocks.count
        let screen = try XCTUnwrap(manager.assignments["notes"])
        manager.selectPanel("notes")
        let primary = manager.roots[screen]?.state.primaryID
        let first = await publish("result-one", in: manager)
        let second = await publish("result-two", in: manager)
        XCTAssertTrue(first.ok); XCTAssertTrue(second.ok)
        let firstID = try XCTUnwrap(first.result["panelID"]?.stringValue)
        let secondID = try XCTUnwrap(second.result["panelID"]?.stringValue)
        XCTAssertNotEqual(firstID, secondID)
        XCTAssertNotEqual(firstID, "document")
        XCTAssertEqual(manager.catalog.first { $0.id == firstID }?.title, "新結果")
        XCTAssertEqual(manager.panels[firstID]?.markdownDocumentModel?.resultTitle, "新結果")
        XCTAssertEqual(existing.blocks.count, before)
        XCTAssertNil(existing.resultTitle)
        XCTAssertTrue(manager.panels["document"]?.markdownDocumentModel === existing)
        XCTAssertEqual(manager.roots[screen]?.state.primaryID, primary)
    }

    func testReplayNeverOverwritesExistingResultOrReopensClosedPanel() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let first = await publish("result-once", in: manager)
        let id = try XCTUnwrap(first.result["panelID"]?.stringValue)
        let count = manager.panels.count
        let duplicate = await publish("result-once", in: manager)
        XCTAssertTrue(duplicate.ok)
        XCTAssertEqual(duplicate.result["panelID"]?.stringValue, id)
        XCTAssertEqual(duplicate.result["replayed"], .boolean(true))
        XCTAssertEqual(manager.panels.count, count)
        let conflict = await publish("result-once", markdown: "overwrite", in: manager)
        XCTAssertFalse(conflict.ok)
        XCTAssertEqual(conflict.error?.code, "invalid_request")
        _ = manager.closePanel(id)
        let closed = await publish("result-once", in: manager)
        XCTAssertFalse(closed.ok)
        XCTAssertEqual(closed.error?.code, "not_found")
        XCTAssertEqual(manager.panels.count, count - 1)
        let invalid = await publish("invalid", markdown: String(repeating: "x", count: 256 * 1024 + 1), in: manager)
        XCTAssertFalse(invalid.ok)
        XCTAssertEqual(manager.panels.count, count - 1)
        XCTAssertFalse(WorkspaceAgentToolDefinitions.all.contains { $0.command == "publish_document" },
                       "Internal publication is not an unrestricted model-facing document mutation tool")
    }

    private func journalLocation() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("maltose-result-journal-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent("conversation.jsonl")
    }

    private var durableRecord: ResultDeliveryRecord {
        .init(publicationID: "durable-result", conversationID: "result-conversation", messageID: "result-message",
              title: "背景結果", markdown: "## 完整結果\n\n保留內容與[來源](https://example.com/source)。", createDocument: true)
    }

    func testDurableResultRestoresSameDocumentAndChatThenHonorsClosedPanelAcrossRestart() throws {
        let url = try journalLocation(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let first = try fixture()
        try first.prepareLiveConversation(at: url)
        let original = first.panels["document"]?.markdownDocumentModel
        first.selectPanel("notes")
        let screen = try XCTUnwrap(first.assignments["notes"])
        let primary = first.roots[screen]?.state.primaryID
        let result = try first.deliverResult(durableRecord)
        let id = try XCTUnwrap(result["panelID"]?.stringValue)
        XCTAssertEqual(result["chatStored"], .boolean(true))
        XCTAssertEqual(first.liveConversationModel?.currentSession?.messages.count, 1)
        XCTAssertEqual(try first.deliverResult(durableRecord)["replayed"], .boolean(true))
        XCTAssertTrue(first.panels["document"]?.markdownDocumentModel === original)
        XCTAssertEqual(first.roots[screen]?.state.primaryID, primary)
        first.stop()

        let restored = try fixture()
        try restored.prepareLiveConversation(at: url)
        XCTAssertNotNil(restored.panels[id]?.markdownDocumentModel)
        XCTAssertEqual(restored.panels[id]?.markdownDocumentModel?.resultTitle, durableRecord.title)
        XCTAssertEqual(restored.liveConversationModel?.currentSession?.messages.count, 1)
        XCTAssertEqual(try restored.deliverResult(durableRecord)["panelID"], .string(id))
        XCTAssertTrue(restored.closePanel(id))
        restored.stop()

        let closed = try fixture(); defer { closed.stop() }
        try closed.prepareLiveConversation(at: url)
        XCTAssertNil(closed.panels[id])
        let replay = try closed.deliverResult(durableRecord)
        XCTAssertEqual(replay["panelStatus"], .string("closed"))
        XCTAssertNil(closed.panels[id])
        XCTAssertEqual(closed.liveConversationModel?.currentSession?.messages.count, 1)
    }

    func testSavedPublicationIntentRecoversCrashBeforePanelCreationAndRejectsConflictsWithoutWriting() throws {
        let url = try journalLocation(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let first = try fixture()
        try first.prepareLiveConversation(at: url)
        try first.liveConversationModel?.saveResult(durableRecord)
        XCTAssertNil(first.panels[durableRecord.panelID!], "Simulate a crash after chat save, before panel creation")
        first.stop()
        let restored = try fixture(); defer { restored.stop() }
        try restored.prepareLiveConversation(at: url)
        XCTAssertNotNil(restored.panels[durableRecord.panelID!])
        XCTAssertEqual(restored.liveConversationModel?.resultDeliveries[durableRecord.publicationID]?.panelApplied, true)
        let before = try Data(contentsOf: url)
        var changed = durableRecord
        changed = .init(publicationID: changed.publicationID, conversationID: changed.conversationID,
                        messageID: changed.messageID, title: changed.title, markdown: "overwrite", createDocument: true)
        XCTAssertThrowsError(try restored.deliverResult(changed))
        let alias = ResultDeliveryRecord(publicationID: "another-publication", conversationID: durableRecord.conversationID,
            messageID: durableRecord.messageID, title: "alias", markdown: "must not overwrite", createDocument: false)
        XCTAssertThrowsError(try restored.deliverResult(alias))
        XCTAssertEqual(try Data(contentsOf: url), before)
        XCTAssertEqual(restored.liveConversationModel?.currentSession?.messages.last?.text, durableRecord.markdown)
    }

    func testDurableCommandCannotClaimDeliveryWithoutJournalOrBecomeModelTool() async throws {
        let manager = try fixture(); defer { manager.stop() }
        let before = manager.panels.count
        let record = durableRecord
        let response = await manager.agentInterface.handle(.init(command: .deliver_result(publicationID: record.publicationID,
            title: record.title, markdown: record.markdown, createDocument: true,
            conversationID: record.conversationID, messageID: record.messageID)))
        XCTAssertFalse(response.ok)
        XCTAssertEqual(manager.panels.count, before)
        XCTAssertFalse(WorkspaceAgentToolDefinitions.all.contains { $0.command == "deliver_result" })
    }

    func testUnavailableJournalCannotReportSuccessfulPanelClosure() async throws {
        let url = try journalLocation(); defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let manager = try fixture(); defer { manager.stop() }
        try manager.prepareLiveConversation(at: url)
        let receipt = try manager.deliverResult(durableRecord)
        let id = try XCTUnwrap(receipt["panelID"]?.stringValue)
        manager.liveConversationModel?.closeLiveStorage()
        let response = await manager.agentInterface.handle(.init(command: .close_panel(panelID: id, discardChanges: false)))
        XCTAssertFalse(response.ok)
        XCTAssertNotNil(manager.panels[id])
        XCTAssertEqual(manager.liveConversationModel?.resultDeliveries[durableRecord.publicationID]?.closed, false)
    }
}
