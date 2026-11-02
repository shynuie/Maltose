import AppKit

@MainActor final class AgentCoreTestWindowController: NSWindowController {
    init() {
        let panel = GlassPanelView(panel: .agentCoreTest)
        panel.title = WorkspacePanel.agentCoreTest.title
        panel.configure(preview: false, primary: true)

        let root = AgentCoreTestRootView(panel: panel)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 760),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Maltose · 核心動畫測試"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = .black
        window.isOpaque = true
        window.appearance = NSAppearance(named: .darkAqua)
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenAuxiliary]
        window.contentView = root
        super.init(window: window)
        window.center()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func present() {
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@MainActor private final class AgentCoreTestRootView: NSView {
    private let panel: GlassPanelView
    override var isFlipped: Bool { true }

    init(panel: GlassPanelView) {
        self.panel = panel
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
        addSubview(panel)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layout() {
        super.layout()
        panel.frame = bounds.insetBy(dx: 12, dy: 12)
    }
}
