import AppKit

extension NSPasteboard.PasteboardType {
    static let maltosePanel = NSPasteboard.PasteboardType("local.maltose.workspace.panel")
    static let maltosePanels = NSPasteboard.PasteboardType("local.maltose.workspace.panels")
}

@MainActor final class GlassPanelView: NSView, NSDraggingSource {
    private static let glassTint = NSColor(calibratedWhite: 0.82, alpha: 0.02)
    private static let selectedGlassTint = NSColor(calibratedWhite: 0.90, alpha: 0.05)
    let surfaceID: String
    let contentView: NSView
    let conversationHistoryModel: ConversationHistoryModel?
    let markdownDocumentModel: MarkdownDocumentModel?
    let chartModel: CSVLineChartModel?
    let imageGalleryModel: ImageGalleryModel?
    weak var manager: WorkspaceWindowManager?
    private let glass: NSView
    private let glassContents = NSView()
    private let content = NSView()
    private let previewHitArea = PreviewHitArea()
    private var downPoint = NSPoint.zero
    private var downEvent: NSEvent?
    private(set) var fullContentSize = NSSize(width: 800, height: 500)
    var isPreview = false
    var isPrimary = false
    var isGlobal = false
    var isSelected = false
    var title: String = "" { didSet { setAccessibilityLabel(title); toolTip = title } }
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }

    init(panel: WorkspacePanel, manager: WorkspaceWindowManager? = nil) {
        self.surfaceID = panel.id
        self.manager = manager
        let historyModel = panel.kind == .conversationHistory ? ConversationHistoryModel() : nil
        let documentModel = panel.kind == .document ? MarkdownDocumentModel() : nil
        let chartModel = panel.kind == .chart ? CSVLineChartModel() : nil
        let imageGalleryModel = panel.kind == .imageGallery ? ImageGalleryModel() : nil
        self.conversationHistoryModel = historyModel
        self.markdownDocumentModel = documentModel
        self.chartModel = chartModel
        self.imageGalleryModel = imageGalleryModel
        self.contentView = panel.makeContentView(conversationHistoryModel: historyModel,
                                                 markdownDocumentModel: documentModel,
                                                 chartModel: chartModel,
                                                 imageGalleryModel: imageGalleryModel)
        if #available(macOS 26.0, *) {
            let effect = NSGlassEffectView()
            effect.style = .clear
            effect.tintColor = Self.glassTint
            effect.contentView = glassContents
            glass = effect
        } else {
            let effect = NSVisualEffectView()
            effect.material = .hudWindow
            effect.blendingMode = .withinWindow
            effect.state = .active
            effect.isEmphasized = false
            effect.addSubview(glassContents)
            glass = effect
        }
        super.init(frame: .zero)
        wantsLayer = true
        focusRingType = .none
        glass.focusRingType = .none
        appearance = NSAppearance(named: .darkAqua)
        glass.wantsLayer = true
        glassContents.wantsLayer = true
        glassContents.autoresizingMask = [.width, .height]
        content.wantsLayer = true
        content.layer?.masksToBounds = true
        addSubview(glass)
        glassContents.addSubview(content)
        content.addSubview(contentView)
        glassContents.addSubview(previewHitArea)
        previewHitArea.panel = self
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        setAccessibilityHelp("拖曳藍色外框移動面板，雙擊外框切換放大。")
        setAccessibilityCustomActions([NSAccessibilityCustomAction(name: "切換放大", target: self, selector: #selector(accessibilityToggle))])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func configure(preview: Bool, primary: Bool, global: Bool = false, selected: Bool = false,
                   workspaceMode: WorkspaceMode = .grid) {
        isPreview = preview
        isPrimary = primary
        isGlobal = global
        isSelected = selected
        conversationHistoryModel?.configure(mode: workspaceMode)
        markdownDocumentModel?.configure(mode: workspaceMode)
        imageGalleryModel?.configure(mode: workspaceMode)
        if #available(macOS 26.0, *), let effect = glass as? NSGlassEffectView {
            effect.tintColor = selected ? Self.selectedGlassTint : Self.glassTint
        } else if let effect = glass as? NSVisualEffectView {
            effect.isEmphasized = selected
        }
        needsLayout = true
    }

    override func layout() {
        super.layout()
        let inset = glassInset
        let radius: CGFloat = isPreview ? 20 : isPrimary ? 32 : isGlobal ? min(38, max(3, inset * 1.12)) : 38
        glass.frame = bounds
        glassContents.frame = bounds
        if #available(macOS 26.0, *), let effect = glass as? NSGlassEffectView { effect.cornerRadius = radius }
        else { glass.layer?.cornerRadius = radius; glass.layer?.masksToBounds = true }
        glassContents.layer?.cornerRadius = radius
        glassContents.layer?.masksToBounds = true
        let rect = bounds.insetBy(dx: inset, dy: inset)
        if isPreview {
            content.frame = WorkspaceGeometry.fittedPreview(content: fullContentSize, in: rect)
            content.bounds = NSRect(origin: .zero, size: fullContentSize)
        } else {
            fullContentSize = rect.size
            content.frame = rect
            content.bounds = NSRect(origin: .zero, size: rect.size)
        }
        contentView.frame = content.bounds
        contentView.bounds = NSRect(origin: .zero, size: content.bounds.size)
        previewHitArea.frame = rect
        previewHitArea.isHidden = !isPreview
    }

    var glassInset: CGFloat {
        if isPreview { return WorkspaceGeometry.previewGlassInset }
        if isPrimary { return WorkspaceGeometry.primaryGlassInset }
        if isGlobal { return WorkspaceGeometry.globalGlassInset(for: bounds.size) }
        return WorkspaceGeometry.normalGlassInset
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard !isHidden, bounds.contains(convert(point, from: superview)) else { return nil }
        let local = convert(point, from: superview)
        if content.frame.contains(local) { return super.hitTest(point) }
        return self
    }

    override func mouseDown(with event: NSEvent) {
        manager?.focus(surfaceID)
        window?.makeFirstResponder(self)
        if event.clickCount == 2 {
            downEvent = nil
            manager?.togglePanel(surfaceID)
            return
        }
        downPoint = convert(event.locationInWindow, from: nil)
        downEvent = event
    }

    override func mouseUp(with event: NSEvent) {
        if isPreview, downEvent != nil { manager?.selectPanel(surfaceID) }
        downEvent = nil
    }

    @objc private func accessibilityToggle() -> Bool { manager?.togglePanel(surfaceID); return true }
    override func accessibilityPerformPress() -> Bool { manager?.selectPanel(surfaceID); return true }
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 || event.keyCode == 49 { manager?.togglePanel(surfaceID) }
        else { super.keyDown(with: event) }
    }
    override func resetCursorRects() {
        super.resetCursorRects()
        let inset = glassInset
        for rect in [NSRect(x: 0, y: 0, width: bounds.width, height: inset),
                     NSRect(x: 0, y: bounds.height - inset, width: bounds.width, height: inset),
                     NSRect(x: 0, y: inset, width: inset, height: max(0, bounds.height - inset * 2)),
                     NSRect(x: bounds.width - inset, y: inset, width: inset, height: max(0, bounds.height - inset * 2))] {
            addCursorRect(rect, cursor: .openHand)
        }
    }

    override func mouseDragged(with event: NSEvent) {
        guard let downEvent, let manager else { return }
        let point = convert(event.locationInWindow, from: nil)
        guard hypot(point.x - downPoint.x, point.y - downPoint.y) >= 5 else { return }
        self.downEvent = nil
        manager.beginDrag(surfaceID)
        let item = NSPasteboardItem()
        item.setPropertyList(manager.draggingIDs, forType: .maltosePanels)
        item.setString(surfaceID, forType: .maltosePanel)
        let draggingItem = NSDraggingItem(pasteboardWriter: item)
        let image = NSImage(size: bounds.size)
        image.lockFocus()
        NSColor(calibratedRed: 0.10, green: 0.31, blue: 0.58, alpha: 0.8).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 24, yRadius: 24).fill()
        let dragTitle = manager.draggingIDs.count > 1 ? "\(manager.draggingIDs.count) 個面板" : title
        (dragTitle as NSString).draw(at: NSPoint(x: 24, y: 24), withAttributes: [.foregroundColor: NSColor.white, .font: NSFont.systemFont(ofSize: 18)])
        image.unlockFocus()
        let dragWidth = min(360, bounds.width)
        let dragSize = NSSize(width: dragWidth, height: min(240, dragWidth * bounds.height / max(1, bounds.width)))
        draggingItem.setDraggingFrame(NSRect(origin: downPoint, size: dragSize), contents: image)
        beginDraggingSession(with: [draggingItem], event: downEvent, source: self)
    }

    func draggingSession(_ session: NSDraggingSession, sourceOperationMaskFor context: NSDraggingContext) -> NSDragOperation {
        context == .withinApplication ? .move : []
    }
    func draggingSession(_ session: NSDraggingSession, endedAt screenPoint: NSPoint, operation: NSDragOperation) {
        manager?.endDrag(committed: operation == .move)
    }
    func ignoreModifierKeys(for session: NSDraggingSession) -> Bool { true }

    func dispose() {}
}

/// Thumbnails are live previews; promote them before editing their content.
@MainActor private final class PreviewHitArea: NSView {
    weak var panel: GlassPanelView?
    override func mouseDown(with event: NSEvent) {}
    override func mouseDragged(with event: NSEvent) {}
    override func mouseUp(with event: NSEvent) {
        guard let panel else { return }
        panel.manager?.selectPanel(panel.surfaceID)
    }
}
