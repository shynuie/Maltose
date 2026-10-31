import Foundation

enum WorkspaceMode: String { case grid, focused, sidebar }

struct WorkspaceGridPosition: Equatable, Hashable {
    var row: Int
    var column: Int
}

/// Presentation belongs to a screen-sized window, independently of document/selection state.
struct WorkspaceLayoutState {
    var panelIDs: [String] = []
    var primaryID: String?
    var selectedIDs: Set<String> = []
    var mode: WorkspaceMode = .grid
    var identityPosition = WorkspaceGridPosition(row: 0, column: 0)

    mutating func reconcile(_ ids: [String]) {
        panelIDs = panelIDs.filter { ids.contains($0) } + ids.filter { !panelIDs.contains($0) }
        if !panelIDs.contains(primaryID ?? "") { primaryID = panelIDs.first }
        selectedIDs.formIntersection(panelIDs)
        if selectedIDs.isEmpty, let primaryID { selectedIDs.insert(primaryID) }
        if panelIDs.isEmpty { mode = .grid }
    }

    mutating func toggle(_ id: String) {
        guard panelIDs.contains(id) else { return }
        if mode != .grid && primaryID == id { mode = .grid }
        else { primaryID = id; mode = .focused }
        selectedIDs = [id]
    }

    mutating func select(_ id: String) {
        guard panelIDs.contains(id) else { return }
        primaryID = id
        selectedIDs = [id]
        if mode == .grid { mode = .focused }
    }

    mutating func highlight(_ id: String, extending: Bool) {
        guard panelIDs.contains(id) else { return }
        primaryID = id
        if extending {
            if selectedIDs.contains(id) {
                selectedIDs.remove(id)
                if primaryID == id { primaryID = panelIDs.first { selectedIDs.contains($0) } }
            } else { selectedIDs.insert(id) }
        } else {
            selectedIDs = [id]
        }
    }

    mutating func clearSelection() {
        selectedIDs.removeAll()
    }

    @discardableResult mutating func repositionPanels(_ ids: [String], to position: WorkspaceGridPosition,
                                                       columns: Int, identityID: String = "agent-identity") -> Bool {
        guard columns > 0, !ids.isEmpty, ids.allSatisfy(panelIDs.contains) else { return false }
        if ids.contains(identityID) {
            guard ids.count == 1 else { return false }
            let next = WorkspaceGridPosition(row: max(0, position.row),
                                             column: min(columns - 1, max(0, position.column)))
            guard identityPosition != next else { return false }
            identityPosition = next
            return true
        }

        let moving = panelIDs.filter(ids.contains)
        let identityIndex = panelIDs.firstIndex(of: identityID)
        var remaining = panelIDs.filter { $0 != identityID && !ids.contains($0) }
        let requestedCell = max(0, position.row) * columns + min(columns - 1, max(0, position.column))
        let identityCell = identityPosition.row * columns + min(columns - 1, identityPosition.column)
        let blockedCells: Set<Int> = [identityCell, identityCell + columns]
        let searchLimit = max(requestedCell + columns * 2, remaining.count + moving.count + columns * 2)
        let availableCells = (0...searchLimit).filter { !blockedCells.contains($0) }
        let insertionIndex = availableCells.firstIndex(where: { $0 >= requestedCell }) ?? availableCells.count
        let boundedIndex = min(remaining.count, insertionIndex)
        remaining.insert(contentsOf: moving, at: boundedIndex)
        if let identityIndex { remaining.insert(identityID, at: min(identityIndex, remaining.count)) }
        guard remaining != panelIDs else { return false }
        panelIDs = remaining
        return true
    }
}

enum WorkspaceGeometry {
    static let normalGlassInset: CGFloat = 36
    static let primaryGlassInset: CGFloat = 24
    static let previewGlassInset: CGFloat = 12
    static let margin: CGFloat = 16
    static let gap: CGFloat = 16
    static let triggerWidth: CGFloat = 20
    static let panelAspect: CGFloat = 16.0 / 9.0

    struct GlobalGrid {
        let frames: [CGRect]
        let columns: Int
        let rows: Int
        let panelSize: CGSize
        let documentSize: CGSize
        let minimumWidth: CGFloat
        let maximumWidth: CGFloat
    }

    /// Zoom is a normalized width between the two-column and ten-column limits.
    static func globalGrid(count: Int, viewport: CGSize, zoom: CGFloat, rowSpans: [Int] = [],
                           pinnedPositions: [Int: WorkspaceGridPosition] = [:],
                           margin requestedMargin: CGFloat = 16, gap requestedGap: CGFloat = 16) -> GlobalGrid {
        let width = max(1, viewport.width)
        let height = max(1, viewport.height)
        let margin = min(max(0, requestedMargin), max(0, (width - 2) / 4))
        let gap = min(max(0, requestedGap), max(0, (width - 2 * margin - 2) / 12))
        let available = max(2, width - 2 * margin)
        let maxWidth = max(1, (available - gap) / 2)
        let minWidth = max(1, (available - gap * 9) / 10)
        let normalizedZoom = min(max(zoom, 0), 1)
        let panelWidth = min(maxWidth, max(minWidth, minWidth + (maxWidth - minWidth) * normalizedZoom))
        // A small epsilon makes column selection stable at fractional-point boundaries.
        let columns = min(10, max(2, Int(floor((available + gap + 0.001) / (panelWidth + gap)))))
        let safeCount = max(0, count)
        let panelHeight = panelWidth / panelAspect
        let gridWidth = CGFloat(columns) * panelWidth + CGFloat(max(0, columns - 1)) * gap
        let gridStartX = (width - gridWidth) / 2
        var occupiedRows: [[Bool]] = []
        var placements = Array<(column: Int, row: Int, span: Int)?>(repeating: nil, count: safeCount)
        func canPlace(row: Int, column: Int, span: Int) -> Bool {
            guard column >= 0, column < columns else { return false }
            return (row..<(row + span)).allSatisfy { occupiedRow in
                !occupiedRows.indices.contains(occupiedRow) || !occupiedRows[occupiedRow][column]
            }
        }
        func occupy(row: Int, column: Int, span: Int) {
            while occupiedRows.count < row + span { occupiedRows.append(Array(repeating: false, count: columns)) }
            for occupiedRow in row..<(row + span) { occupiedRows[occupiedRow][column] = true }
        }
        func firstAvailable(span: Int) -> (row: Int, column: Int) {
            var row = 0
            search: while true {
                for candidate in 0..<columns {
                    if canPlace(row: row, column: candidate, span: span) { break search }
                }
                row += 1
            }
            return (row, (0..<columns).first(where: { canPlace(row: row, column: $0, span: span) }) ?? 0)
        }

        for index in pinnedPositions.keys.sorted() where index >= 0 && index < safeCount {
            let span = min(2, max(1, rowSpans.indices.contains(index) ? rowSpans[index] : 1))
            let requested = pinnedPositions[index]!
            let row = max(0, requested.row)
            let column = min(columns - 1, max(0, requested.column))
            let cell = canPlace(row: row, column: column, span: span)
                ? (row: row, column: column)
                : firstAvailable(span: span)
            occupy(row: cell.row, column: cell.column, span: span)
            placements[index] = (cell.column, cell.row, span)
        }
        for index in 0..<safeCount where placements[index] == nil {
            let span = min(2, max(1, rowSpans.indices.contains(index) ? rowSpans[index] : 1))
            let cell = firstAvailable(span: span)
            occupy(row: cell.row, column: cell.column, span: span)
            placements[index] = (cell.column, cell.row, span)
        }
        let rows = occupiedRows.count
        let gridHeight = 2 * margin + CGFloat(rows) * panelHeight + CGFloat(max(0, rows - 1)) * gap
        let documentHeight = max(height, gridHeight)
        let frames = placements.map { optionalPlacement -> CGRect in
            let placement = optionalPlacement!
            return CGRect(x: gridStartX + CGFloat(placement.column) * (panelWidth + gap),
                          y: margin + CGFloat(placement.row) * (panelHeight + gap),
                          width: panelWidth,
                          height: CGFloat(placement.span) * panelHeight + CGFloat(placement.span - 1) * gap)
        }
        return GlobalGrid(frames: frames, columns: columns, rows: rows,
                          panelSize: CGSize(width: panelWidth, height: panelHeight),
                          documentSize: CGSize(width: width, height: documentHeight),
                          minimumWidth: minWidth, maximumWidth: maxWidth)
    }

    static func initialGlobalZoom(viewportWidth: CGFloat, initialColumns: Int = 4) -> CGFloat {
        let width = max(1, viewportWidth)
        let available = max(2, width - 2 * min(margin, max(0, (width - 2) / 4)))
        let safeGap = min(gap, max(0, (available - 2) / 12))
        let minWidth = max(1, (available - safeGap * 9) / 10)
        let maxWidth = max(minWidth, (available - safeGap) / 2)
        let preferred = max(1, (available - safeGap * CGFloat(max(0, initialColumns - 1))) / CGFloat(max(1, initialColumns)))
        return maxWidth == minWidth ? 0.5 : min(1, max(0, (preferred - minWidth) / (maxWidth - minWidth)))
    }

    static func defaultGlobalColumns(forWindowAspectRatio aspectRatio: CGFloat) -> Int {
        aspectRatio >= 1 ? 4 : 2
    }

    static func zoomed(_ zoom: CGFloat, deltaY: CGFloat) -> CGFloat {
        min(1, max(0, zoom + deltaY * 0.0025))
    }

    static func normalizedWheelDelta(_ deltaY: CGFloat, precise: Bool) -> CGFloat {
        min(80, max(-80, precise ? deltaY : deltaY * 12))
    }

    static func globalGlassInset(for panelSize: CGSize) -> CGFloat {
        min(36, max(0.5, min(panelSize.width, panelSize.height) * 0.07))
    }

    static func clampedScrollOffset(_ offset: CGFloat, grid: GlobalGrid, viewportHeight: CGFloat) -> CGFloat {
        min(max(0, offset), max(0, grid.documentSize.height - viewportHeight))
    }

    static func anchoredScrollOffset(frame: CGRect, relativeY: CGFloat, viewportY: CGFloat, grid: GlobalGrid, viewportHeight: CGFloat) -> CGFloat {
        clampedScrollOffset(frame.minY + min(1, max(0, relativeY)) * frame.height - viewportY,
                            grid: grid, viewportHeight: viewportHeight)
    }

    static func fittedPreview(content: CGSize, in bounds: CGRect) -> CGRect {
        guard content.width > 0, content.height > 0 else { return bounds }
        let scale = min(bounds.width / content.width, bounds.height / content.height)
        let size = CGSize(width: content.width * scale, height: content.height * scale)
        return CGRect(x: bounds.midX - size.width / 2, y: bounds.midY - size.height / 2, width: size.width, height: size.height)
    }

    static func sidebarWidth(in bounds: CGRect) -> CGFloat {
        min(max(bounds.width * 0.2, 220), min(340, bounds.width * 0.4))
    }

    static func legacyGrid(count: Int, in bounds: CGRect) -> [CGRect] {
        guard count > 0, bounds.width > 0, bounds.height > 0 else { return [] }
        let area = bounds.insetBy(dx: margin, dy: margin)
        let columns = (1...count).min { a, b in
            func score(_ columns: Int) -> CGFloat {
                let rows = Int(ceil(Double(count) / Double(columns)))
                let w = max(1, (area.width - gap * CGFloat(columns - 1)) / CGFloat(columns))
                let h = max(1, (area.height - gap * CGFloat(rows - 1)) / CGFloat(rows))
                return abs(log((w / h) / 1.6)) + CGFloat(rows * columns - count) * 0.06
            }
            return score(a) < score(b)
        } ?? 1
        let rows = Int(ceil(Double(count) / Double(columns)))
        let w = max(1, (area.width - gap * CGFloat(columns - 1)) / CGFloat(columns))
        let h = max(1, (area.height - gap * CGFloat(rows - 1)) / CGFloat(rows))
        return (0..<count).map { index in
            CGRect(x: area.minX + CGFloat(index % columns) * (w + gap),
                   y: area.minY + CGFloat(index / columns) * (h + gap), width: w, height: h)
        }
    }
}

enum WorkspaceScrollAction: Equatable {
    case passThrough
    case scroll(CGFloat)
    case zoom(CGFloat)

    static func route(mode: WorkspaceMode, isInsideGrid: Bool, isCovered: Bool,
                      isInsideScrollablePanel: Bool = false, controlPressed: Bool, deltaY: CGFloat) -> WorkspaceScrollAction {
        guard mode == .grid, isInsideGrid, !isCovered, deltaY != 0 else { return .passThrough }
        if isInsideScrollablePanel && !controlPressed { return .passThrough }
        return controlPressed ? .zoom(deltaY) : .scroll(deltaY)
    }
}

struct ConversationHistoryLayout {
    static let focusedFontSize: CGFloat = 16
    static let focusedCharactersPerLine: CGFloat = 40
    static let globalCharactersPerLine: CGFloat = 20
    static let minimumGlobalFontSize: CGFloat = 10
    static let maximumGlobalFontSize: CGFloat = 18

    let width: CGFloat
    let focused: Bool

    init(width: CGFloat, focused: Bool) {
        self.width = max(0, width)
        self.focused = focused
    }

    var showsText: Bool {
        focused || width >= Self.minimumGlobalFontSize * Self.globalCharactersPerLine
    }

    var fontSize: CGFloat {
        guard !focused else { return Self.focusedFontSize }
        return min(Self.maximumGlobalFontSize,
                   max(Self.minimumGlobalFontSize, width / Self.globalCharactersPerLine))
    }

    var contentWidth: CGFloat {
        guard focused else { return width }
        return min(width, Self.focusedFontSize * Self.focusedCharactersPerLine)
    }

    var verticalPadding: CGFloat { focused ? 24 : 8 }
    var rowSpacing: CGFloat { focused ? 18 : 6 }
}

struct MarkdownDocumentLayout {
    static let focusedFontSize: CGFloat = 16
    static let focusedCharactersPerLine: CGFloat = 40
    static let globalCharactersPerLine: CGFloat = 20
    static let minimumGlobalFontSize: CGFloat = 10
    static let maximumGlobalFontSize: CGFloat = 18

    let width: CGFloat
    let focused: Bool

    init(width: CGFloat, focused: Bool) {
        self.width = max(0, width)
        self.focused = focused
    }

    var showsText: Bool {
        focused || width >= Self.minimumGlobalFontSize * Self.globalCharactersPerLine
    }

    var fontSize: CGFloat {
        guard !focused else { return Self.focusedFontSize }
        return min(Self.maximumGlobalFontSize,
                   max(Self.minimumGlobalFontSize, width / Self.globalCharactersPerLine))
    }

    var textColumnWidth: CGFloat {
        guard focused else { return width }
        return min(width, Self.focusedFontSize * Self.focusedCharactersPerLine)
    }

    /// Images align to the reading column and keep shrinking when global-mode text is hidden.
    var imageWidth: CGFloat {
        focused ? min(width, Self.focusedFontSize * Self.focusedCharactersPerLine) : textColumnWidth
    }
}

struct WorkspaceWheelGesture {
    private var lockedControlModifier: Bool?

    mutating func controlModifier(currentlyPressed: Bool, began: Bool, isActive: Bool, ended: Bool) -> Bool {
        if began || (isActive && lockedControlModifier == nil) { lockedControlModifier = currentlyPressed }
        let result = isActive ? (lockedControlModifier ?? currentlyPressed) : currentlyPressed
        if ended { lockedControlModifier = nil }
        return result
    }
}

/// A stationary pointer, rather than merely time spent near the edge, opens the sidebar.
struct SidebarDwell {
    private(set) var anchor: CGPoint?
    private(set) var stationarySince: TimeInterval?
    mutating func update(point: CGPoint, eligible: Bool, now: TimeInterval) {
        guard eligible else { cancel(); return }
        if point != anchor { anchor = point; stationarySince = now }
    }
    func isReady(at now: TimeInterval) -> Bool {
        stationarySince.map { now - $0 >= 1 } ?? false
    }
    mutating func cancel() { anchor = nil; stationarySince = nil }
}
