import AppKit
import SwiftUI

/// Kept by the chat model, so changing workspace modes does not reset reading intent.
@MainActor final class ConversationAutoScrollState {
    static let readingInterval: TimeInterval = 30
    private(set) var lastManualScroll: TimeInterval?
    private(set) var readingOrigin: CGPoint?

    func shouldFollow(at time: TimeInterval = ProcessInfo.processInfo.systemUptime) -> Bool {
        guard let lastManualScroll else { return true }
        return time - lastManualScroll >= Self.readingInterval
    }

    func manuallyScrolled(to origin: CGPoint, atBottom: Bool,
                          at time: TimeInterval = ProcessInfo.processInfo.systemUptime) {
        lastManualScroll = atBottom ? nil : time
        readingOrigin = atBottom ? nil : origin
    }
}

/// Observe the transcript's own NSScrollView, never the surrounding workspace grid
/// or session sidebar. Only real input/live scrolling can suspend following.
struct ConversationScrollObserver: NSViewRepresentable {
    let state: ConversationAutoScrollState

    func makeNSView(context: Context) -> ConversationScrollObservationView {
        let view = ConversationScrollObservationView()
        view.configure(state: state)
        return view
    }
    func updateNSView(_ view: ConversationScrollObservationView, context: Context) {
        view.configure(state: state)
    }
    static func dismantleNSView(_ view: ConversationScrollObservationView, coordinator: ()) { view.dispose() }
}

@MainActor final class ConversationScrollObservationView: NSView {
    private var state: ConversationAutoScrollState?
    private weak var observedScroll: NSScrollView?
    private var eventMonitor: Any?
    private var liveScrolling = false
    private var manualEventPending = false
    private var manualStartOrigin: CGPoint?
    private var attachmentScheduled = false

    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window == nil { dispose() } else { scheduleAttachment() }
    }
    override func viewDidMoveToSuperview() { super.viewDidMoveToSuperview(); scheduleAttachment() }

    func configure(state: ConversationAutoScrollState) {
        if self.state !== state { dispose(); self.state = state }
        scheduleAttachment()
    }

    private func scheduleAttachment() {
        guard !attachmentScheduled else { return }
        attachmentScheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.attachmentScheduled = false
            guard self.window != nil, let scroll = self.enclosingScrollView else { return }
            self.attach(to: scroll)
        }
    }

    func attach(to scroll: NSScrollView) {
        guard observedScroll !== scroll else { return }
        dispose()
        observedScroll = scroll
        let center = NotificationCenter.default
        scroll.contentView.postsBoundsChangedNotifications = true
        center.addObserver(self, selector: #selector(boundsChanged), name: NSView.boundsDidChangeNotification, object: scroll.contentView)
        center.addObserver(self, selector: #selector(liveScrollBegan), name: NSScrollView.willStartLiveScrollNotification, object: scroll)
        center.addObserver(self, selector: #selector(liveScrollChanged), name: NSScrollView.didLiveScrollNotification, object: scroll)
        center.addObserver(self, selector: #selector(liveScrollEnded), name: NSScrollView.didEndLiveScrollNotification, object: scroll)
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.scrollWheel, .keyDown]) { [weak self] event in
            self?.observeInput(event)
            return event
        }
        // A mode change can rebuild the SwiftUI scroll view. Respect the same
        // session's recent manual position instead of treating it as a new chat.
        if let state, !state.shouldFollow(), let origin = state.readingOrigin {
            scroll.contentView.scroll(to: scroll.contentView.constrainBoundsRect(CGRect(origin: origin, size: scroll.contentView.bounds.size)).origin)
            scroll.reflectScrolledClipView(scroll.contentView)
        }
    }

    private func observeInput(_ event: NSEvent) {
        guard let scroll = observedScroll, event.window === scroll.window, !scroll.isHiddenOrHasHiddenAncestor else { return }
        if event.type == .scrollWheel {
            guard !event.modifierFlags.contains(.control), abs(event.scrollingDeltaY) > 0,
                  scroll.visibleRect.contains(scroll.convert(event.locationInWindow, from: nil)) else { return }
        } else {
            guard [49, 115, 116, 119, 121, 125, 126].contains(event.keyCode),
                  let responder = scroll.window?.firstResponder as? NSView,
                  responder === scroll || responder.isDescendant(of: scroll) else { return }
        }
        manualStartOrigin = scroll.contentView.bounds.origin
        manualEventPending = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.recordManualPosition()
            self.manualEventPending = false
            self.manualStartOrigin = nil
        }
    }

    @objc private func liveScrollBegan() {
        liveScrolling = true
        manualStartOrigin = observedScroll?.contentView.bounds.origin
    }
    @objc private func liveScrollChanged() { recordManualPosition() }
    @objc private func liveScrollEnded() {
        recordManualPosition()
        liveScrolling = false
        if !manualEventPending { manualStartOrigin = nil }
    }
    @objc private func boundsChanged() {
        if liveScrolling || manualEventPending { recordManualPosition() }
    }

    private func recordManualPosition() {
        guard let scroll = observedScroll, let document = scroll.documentView,
              let previous = manualStartOrigin else { return }
        let origin = scroll.contentView.bounds.origin
        guard abs(origin.y - previous.y) > 0.5 else { return }
        let visible = scroll.contentView.documentVisibleRect
        let distance = document.isFlipped ? document.bounds.maxY - visible.maxY : visible.minY - document.bounds.minY
        state?.manuallyScrolled(to: origin, atBottom: distance <= 8)
        manualStartOrigin = origin
    }

    func dispose() {
        NotificationCenter.default.removeObserver(self)
        if let eventMonitor { NSEvent.removeMonitor(eventMonitor) }
        eventMonitor = nil; observedScroll = nil
        liveScrolling = false; manualEventPending = false; manualStartOrigin = nil
    }
}
