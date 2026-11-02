import AppKit
import SwiftUI
import XCTest
@testable import MaltoseApp

@MainActor final class ConversationAutoScrollTests: XCTestCase {
    func testReadingProtectionExpiresFromLastManualMovementAndBottomRestoresImmediately() {
        let state = ConversationAutoScrollState()
        XCTAssertTrue(state.shouldFollow(at: 100))
        state.manuallyScrolled(to: .init(x: 0, y: 300), atBottom: false, at: 100)
        XCTAssertFalse(state.shouldFollow(at: 129.999))
        state.manuallyScrolled(to: .init(x: 0, y: 450), atBottom: false, at: 125)
        XCTAssertFalse(state.shouldFollow(at: 154.999))
        XCTAssertTrue(state.shouldFollow(at: 155))
        state.manuallyScrolled(to: .init(x: 0, y: 600), atBottom: false, at: 156)
        state.manuallyScrolled(to: .init(x: 0, y: 900), atBottom: true, at: 157)
        XCTAssertTrue(state.shouldFollow(at: 157))
        XCTAssertNil(state.readingOrigin)
    }

    func testReadingIntentIsPerSessionAndSurvivesAllWorkspaceModes() {
        let model = ConversationHistoryModel()
        let first = model.scrollState(for: "first")
        first.manuallyScrolled(to: .init(x: 0, y: 50), atBottom: false)
        for mode: WorkspaceMode in [.grid, .focused, .sidebar] {
            model.configure(mode: mode)
            XCTAssertTrue(model.scrollState(for: "first") === first)
            XCTAssertFalse(model.scrollState(for: "first").shouldFollow())
            XCTAssertTrue(model.scrollState(for: "second").shouldFollow())
        }
    }
}

@MainActor final class ConversationAutoScrollDesktopTests: XCTestCase {
    private var sequence = 0

    private func send(_ model: ConversationHistoryModel, type: String = "assistant_message", text: String, messageID: String? = nil) throws {
        sequence += 1
        var payload = ["content": text]
        if let messageID { payload["message_id"] = messageID }
        let data = try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "sessionID": "scroll-test", "sequence": sequence,
            "event": ["type": type, "payload": payload, "timestamp": "2026-11-01T08:00:00Z"]])
        try model.applyRuntimeEvent(data)
    }

    private func fixture() throws -> (ConversationHistoryModel, NSWindow) {
        guard ProcessInfo.processInfo.environment["MALTOSE_GUI_TESTS"] == "1" else { throw XCTSkip("Requires desktop chat layout") }
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires WindowServer") }
        let model = ConversationHistoryModel(sessions: [])
        for index in 0..<12 {
            try send(model, text: "Message \(index)\n" + String(repeating: "A long conversation line for scrolling.\n\n", count: 5))
        }
        let window = NSWindow(contentRect: .init(x: 50, y: 50, width: 900, height: 650),
                              styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: ConversationHistoryPanelView(model: model))
        window.orderFront(nil)
        return (model, window)
    }

    private func observation(in view: NSView) -> ConversationScrollObservationView? {
        if let match = view as? ConversationScrollObservationView { return match }
        return view.subviews.lazy.compactMap { self.observation(in: $0) }.first
    }
    private func settle(_ window: NSWindow) async throws {
        window.contentView?.layoutSubtreeIfNeeded(); window.displayIfNeeded()
        try await Task.sleep(for: .milliseconds(250))
        window.contentView?.layoutSubtreeIfNeeded(); window.displayIfNeeded()
    }
    private func scroll(in window: NSWindow) throws -> NSScrollView {
        try XCTUnwrap(observation(in: try XCTUnwrap(window.contentView))?.enclosingScrollView,
                      "Native input observer must attach inside the transcript, including in compact modes")
    }
    private func distanceFromBottom(_ scroll: NSScrollView) throws -> CGFloat {
        let document = try XCTUnwrap(scroll.documentView)
        let visible = scroll.contentView.documentVisibleRect
        return document.isFlipped ? document.bounds.maxY - visible.maxY : visible.minY - document.bounds.minY
    }
    private func manuallyMove(_ scroll: NSScrollView, to point: CGPoint) {
        NotificationCenter.default.post(name: NSScrollView.willStartLiveScrollNotification, object: scroll)
        scroll.contentView.scroll(to: point); scroll.reflectScrolledClipView(scroll.contentView)
        NotificationCenter.default.post(name: NSScrollView.didLiveScrollNotification, object: scroll)
        NotificationCenter.default.post(name: NSScrollView.didEndLiveScrollNotification, object: scroll)
    }

    func testUserMessagesRepliesAndGrowingStreamFollowInEveryMode() async throws {
        let (model, window) = try fixture()
        defer { window.close() }
        for mode: WorkspaceMode in [.grid, .focused, .sidebar] {
            model.configure(mode: mode)
            try await settle(window)
            try send(model, type: "user_message", text: "A new outgoing message in \(mode).")
            try await settle(window)
            XCTAssertLessThanOrEqual(try distanceFromBottom(scroll(in: window)), 8, "Outgoing message in \(mode)")
            let messageID = "stream-\(mode)"
            try send(model, type: "assistant_start", text: "", messageID: messageID)
            try send(model, type: "assistant_delta", text: String(repeating: "Streaming response grows.\n\n", count: 30), messageID: messageID)
            try await settle(window)
            XCTAssertLessThanOrEqual(try distanceFromBottom(scroll(in: window)), 8, "Growing reply in \(mode)")
            try send(model, type: "assistant_end", text: String(repeating: "Final response.\n\n", count: 35), messageID: messageID)
            try await settle(window)
            XCTAssertLessThanOrEqual(try distanceFromBottom(scroll(in: window)), 8, "Final reply in \(mode)")
            XCTAssertTrue(model.scrollState(for: "scroll-test").shouldFollow(), "Automatic layout must not suspend following")
        }
    }

    func testManualReadingSurvivesMessagesAndModeChangesThenResumesOnNextMessage() async throws {
        let (model, window) = try fixture()
        defer { window.close() }
        try await settle(window)
        var transcript = try scroll(in: window)
        manuallyMove(transcript, to: .init(x: 0, y: 100))
        let state = model.scrollState(for: "scroll-test")
        XCTAssertFalse(state.shouldFollow())
        for mode: WorkspaceMode in [.focused, .sidebar, .grid] {
            model.configure(mode: mode)
            try send(model, text: "Received while reading history in \(mode).")
            try await settle(window)
            transcript = try scroll(in: window)
            XCTAssertGreaterThan(try distanceFromBottom(transcript), 100, "Mode changes must preserve the reading pause")
            XCTAssertFalse(state.shouldFollow())
        }
        state.manuallyScrolled(to: transcript.contentView.bounds.origin, atBottom: false,
                               at: ProcessInfo.processInfo.systemUptime - 31)
        try send(model, text: "New message after the 30-second reading protection.")
        try await settle(window)
        XCTAssertLessThanOrEqual(try distanceFromBottom(scroll(in: window)), 8)
    }

    func testLayoutMovementDoesNotCountAsManualAndReturningToBottomRestoresFollowing() async throws {
        let (model, window) = try fixture()
        defer { window.close() }
        try await settle(window)
        let transcript = try scroll(in: window)
        let state = model.scrollState(for: "scroll-test")
        transcript.contentView.scroll(to: .init(x: 0, y: 100))
        transcript.reflectScrolledClipView(transcript.contentView)
        XCTAssertTrue(state.shouldFollow(), "Bounds notifications alone cannot establish human intent")
        try send(model, text: "Follow after programmatic layout movement.")
        try await settle(window)
        XCTAssertLessThanOrEqual(try distanceFromBottom(transcript), 8)
        let bottom = transcript.contentView.bounds.origin
        manuallyMove(transcript, to: .init(x: 0, y: 100))
        XCTAssertFalse(state.shouldFollow())
        manuallyMove(transcript, to: bottom)
        XCTAssertTrue(state.shouldFollow())
        try send(model, text: "Following resumes immediately when the user reaches the bottom.")
        try await settle(window)
        XCTAssertLessThanOrEqual(try distanceFromBottom(transcript), 8)
    }
}
