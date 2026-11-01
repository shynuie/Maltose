import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct CSVLineChartRow: Identifiable {
    let id: Int
    let xLabel: String
    let xValue: Double
    let values: [Double?]
    let note: String
}

struct CSVLineChartData {
    let xTitle: String
    let seriesNames: [String]
    let rows: [CSVLineChartRow]
}

struct CSVLineChartPointContext: Equatable {
    let xLabel: String
    let seriesName: String
    let value: Double
    let note: String
}

struct CSVLineChartBand: Hashable, Identifiable {
    let firstSeries: Int
    let secondSeries: Int
    var id: String { "\(firstSeries)-\(secondSeries)" }
}

/// Agent-facing chart generation option: fill the area between two named series.
struct CSVLineChartBandRequest: Hashable, Codable {
    let firstSeriesName: String
    let secondSeriesName: String
    var opacity: Double = 0.16
}

enum CSVLineChartParser {
    enum ParseError: LocalizedError {
        case missingColumns
        case noDataRows
        case noNumericSeries

        var errorDescription: String? {
            switch self {
            case .missingColumns: "CSV 至少需要 X 軸與一個數值欄位。"
            case .noDataRows: "CSV 沒有可繪製的資料列。"
            case .noNumericSeries: "找不到包含數值的線條欄位。"
            }
        }
    }

    static func parse(_ source: String) throws -> CSVLineChartData {
        let records = records(from: source)
        guard let rawHeader = records.first else { throw ParseError.missingColumns }
        let header = rawHeader.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        guard header.count >= 2 else { throw ParseError.missingColumns }

        let hasNoteColumn = header.last.map(isNoteHeader) ?? false
        let seriesEnd = hasNoteColumn ? header.count - 1 : header.count
        guard seriesEnd >= 2 else { throw ParseError.noNumericSeries }
        let seriesNames = (1..<seriesEnd).map { index in
            header[index].isEmpty ? "線條 \(index)" : header[index]
        }
        let dataRecords = records.dropFirst().filter { row in
            row.contains { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        }
        guard !dataRecords.isEmpty else { throw ParseError.noDataRows }

        let normalizedRows = dataRecords.map { row -> [String] in
            if row.count >= header.count { return Array(row.prefix(header.count)) }
            return row + Array(repeating: "", count: header.count - row.count)
        }
        let xValues = normalizedRows.map { xAxisValue($0[0]) }
        let canUseXValues = xValues.allSatisfy { $0 != nil }
        var rows: [CSVLineChartRow] = []
        for (rowIndex, record) in normalizedRows.enumerated() {
            let values = (1..<seriesEnd).map { Double(record[$0].trimmingCharacters(in: .whitespacesAndNewlines)) }
            guard values.contains(where: { $0 != nil }) else { continue }
            let note = hasNoteColumn ? record[header.count - 1].trimmingCharacters(in: .whitespacesAndNewlines) : ""
            rows.append(CSVLineChartRow(id: rowIndex, xLabel: record[0].trimmingCharacters(in: .whitespacesAndNewlines),
                                        xValue: canUseXValues ? (xValues[rowIndex] ?? Double(rowIndex)) : Double(rowIndex),
                                        values: values, note: note))
        }
        guard !rows.isEmpty else { throw ParseError.noNumericSeries }
        let xTitle = header[0].isEmpty ? "X" : header[0]
        return CSVLineChartData(xTitle: xTitle, seriesNames: seriesNames, rows: rows)
    }

    private static func isNoteHeader(_ value: String) -> Bool {
        ["note", "notes", "備註", "註記", "註釋"].contains(value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
    }

    private static func xAxisValue(_ value: String) -> Double? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if let number = Double(trimmed) { return number }
        let iso = ISO8601DateFormatter()
        if let date = iso.date(from: trimmed) { return date.timeIntervalSince1970 }
        for format in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd", "HH:mm:ss", "HH:mm"] {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone(secondsFromGMT: 0)
            formatter.dateFormat = format
            if let date = formatter.date(from: trimmed) { return date.timeIntervalSince1970 }
        }
        return nil
    }

    private static func records(from source: String) -> [[String]] {
        let characters = Array(source.hasPrefix("\u{feff}") ? source.dropFirst() : source[...])
        var records: [[String]] = []
        var record: [String] = []
        var field = ""
        var quoted = false
        var index = 0

        while index < characters.count {
            let character = characters[index]
            if quoted {
                if character == "\"" {
                    if index + 1 < characters.count, characters[index + 1] == "\"" {
                        field.append("\"")
                        index += 1
                    } else {
                        quoted = false
                    }
                } else {
                    field.append(character)
                }
            } else {
                switch character {
                case "\"" where field.isEmpty:
                    quoted = true
                case ",":
                    record.append(field)
                    field = ""
                case "\n":
                    record.append(field)
                    if !(record.count == 1 && record[0].isEmpty) { records.append(record) }
                    record = []
                    field = ""
                case "\r":
                    if index + 1 < characters.count, characters[index + 1] == "\n" { break }
                    record.append(field)
                    if !(record.count == 1 && record[0].isEmpty) { records.append(record) }
                    record = []
                    field = ""
                default:
                    field.append(character)
                }
            }
            index += 1
        }
        if !field.isEmpty || !record.isEmpty {
            record.append(field)
            records.append(record)
        }
        return records
    }
}

@MainActor final class CSVLineChartModel: ObservableObject {
    @Published private(set) var data: CSVLineChartData
    @Published private(set) var sourceName = "內建範例"
    @Published private(set) var errorMessage: String?
    @Published private(set) var visibleSeries: Set<Int>
    @Published private(set) var filledBands: [CSVLineChartBand: Double] = [:]
    @Published private(set) var xZoom: CGFloat = 1
    @Published private(set) var xPan: Double = 0
    @Published private(set) var hoveredPoint: CSVLineChartPointContext?

    init() {
        let sample = """
        時間,工作量,完成率,note
        09:00,24,18,開始整理資料
        10:00,38,32,"匯入 CSV，欄位包含逗號, 需要保留"
        11:00,34,48,完成第一輪分析
        12:00,59,53,
        13:00,72,68,檢查異常高點
        14:00,65,82,分享給團隊
        15:00,88,91,今日最高點
        """
        let parsed = (try? CSVLineChartParser.parse(sample)) ?? CSVLineChartData(xTitle: "X", seriesNames: [], rows: [])
        self.data = parsed
        self.visibleSeries = Set(parsed.seriesNames.indices)
    }

    func toggleSeries(_ index: Int) {
        if visibleSeries.contains(index) {
            visibleSeries.remove(index)
            if data.seriesNames.indices.contains(index), hoveredPoint?.seriesName == data.seriesNames[index] {
                hoveredPoint = nil
            }
        }
        else { visibleSeries.insert(index) }
    }

    func configureAgentVisibleSeries(_ names: [String]) {
        visibleSeries = Set(data.seriesNames.indices.filter { names.contains(data.seriesNames[$0]) })
    }

    func setXAxisViewport(zoom: CGFloat, pan: Double) {
        xZoom = min(8, max(1, zoom))
        xPan = pan.isFinite ? pan : 0
    }

    func setHoveredPoint(rowIndex: Int?, seriesIndex: Int?) {
        guard let rowIndex, let seriesIndex,
              data.rows.indices.contains(rowIndex),
              data.seriesNames.indices.contains(seriesIndex),
              data.rows[rowIndex].values.indices.contains(seriesIndex),
              let value = data.rows[rowIndex].values[seriesIndex] else {
            hoveredPoint = nil
            return
        }
        let row = data.rows[rowIndex]
        hoveredPoint = CSVLineChartPointContext(xLabel: row.xLabel,
                                                seriesName: data.seriesNames[seriesIndex],
                                                value: value,
                                                note: row.note)
    }

    /// Called by the future agent adapter when it creates or updates a chart.
    /// Unknown or identical series names are ignored; opacity is clamped to 0...1.
    func configureAgentBands(_ requests: [CSVLineChartBandRequest]) {
        var configured: [CSVLineChartBand: Double] = [:]
        for request in requests {
            guard let first = data.seriesNames.firstIndex(of: request.firstSeriesName),
                  let second = data.seriesNames.firstIndex(of: request.secondSeriesName),
                  first != second else { continue }
            let band = CSVLineChartBand(firstSeries: min(first, second), secondSeries: max(first, second))
            configured[band] = min(1, max(0, request.opacity))
        }
        filledBands = configured
    }

    func chooseCSV() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.prompt = "開啟 CSV"
        if panel.runModal() == .OK, let url = panel.url { loadCSV(url) }
    }

    func loadCSV(_ url: URL) {
        do { try importCSV(url) }
        catch { errorMessage = error.localizedDescription }
    }

    /// Shared by the file picker, drag/drop and Agent calls.
    func importCSV(_ url: URL) throws {
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }
        try loadCSV(contents: String(contentsOf: url, encoding: .utf8), sourceName: url.lastPathComponent)
    }

    func loadCSV(contents: String, sourceName: String = "Agent CSV") throws {
        data = try CSVLineChartParser.parse(contents)
        self.sourceName = sourceName
        visibleSeries = Set(data.seriesNames.indices)
        filledBands = [:]
        setXAxisViewport(zoom: 1, pan: 0)
        errorMessage = nil
    }
}

private struct ChartHover: Equatable {
    let rowIndex: Int
    let seriesIndex: Int
    let location: CGPoint
}

struct CSVLineChartPanelView: View {
    @ObservedObject var model: CSVLineChartModel
    @State private var hover: ChartHover?
    @State private var isDropTargeted = false
    @State private var zoomGestureStart: CGFloat?
    @State private var panGestureStart: Double?

    private var xZoom: CGFloat { model.xZoom }
    private var xPan: Double { model.xPan }

    private let colors: [Color] = [
        Color(red: 0.28, green: 0.73, blue: 0.89),
        Color(red: 0.42, green: 0.81, blue: 0.63),
        Color(red: 0.93, green: 0.66, blue: 0.34),
        Color(red: 0.75, green: 0.57, blue: 0.91),
        Color(red: 0.91, green: 0.47, blue: 0.56)
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("圖表").font(.system(size: 21, weight: .medium))
                    Text(model.sourceName).font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.white.opacity(0.42)).lineLimit(1)
                }
                Spacer()
                Button("載入 CSV", systemImage: "doc.badge.plus") { model.chooseCSV() }
                    .buttonStyle(.bordered).controlSize(.small)
            }

            ScrollView(.horizontal) {
                HStack(spacing: 14) {
                    ForEach(model.data.seriesNames.indices, id: \.self) { index in
                        Button { model.toggleSeries(index) } label: {
                            HStack(spacing: 6) {
                                Capsule().fill(colors[index % colors.count]).frame(width: 16, height: 3)
                                Text(model.data.seriesNames[index]).lineLimit(1)
                            }
                            .font(.system(size: 12, weight: model.visibleSeries.contains(index) ? .medium : .regular))
                            .foregroundStyle(.white.opacity(model.visibleSeries.contains(index) ? 0.84 : 0.32))
                        }
                        .buttonStyle(.plain)
                    }
                    Spacer(minLength: 0)
                }
            }
            .scrollIndicators(.hidden)

            HStack(spacing: 10) {
                Text("拖曳平移 · 捏合縮放")
                    .font(.system(size: 10)).foregroundStyle(.white.opacity(0.36))
                Spacer()
                Button { setZoom(xZoom / 1.25) } label: { Image(systemName: "minus.magnifyingglass") }
                    .buttonStyle(.plain).disabled(xZoom <= 1.01)
                    .accessibilityLabel("縮小 X 軸")
                Text("X \(String(format: "%.1f", xZoom))×")
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.48))
                    .frame(minWidth: 44)
                Button { setZoom(xZoom * 1.25) } label: { Image(systemName: "plus.magnifyingglass") }
                    .buttonStyle(.plain).disabled(xZoom >= 7.99)
                    .accessibilityLabel("放大 X 軸")
                Button("重設") { model.setXAxisViewport(zoom: 1, pan: 0) }
                    .buttonStyle(.plain).font(.system(size: 10)).disabled(xZoom <= 1.01 && abs(xPan) < 0.001)
            }
            .font(.system(size: 11))
            .foregroundStyle(.white.opacity(0.65))

            GeometryReader { geometry in
                chart(in: geometry.size)
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location):
                            hover = closestPoint(to: location, in: geometry.size)
                            model.setHoveredPoint(rowIndex: hover?.rowIndex, seriesIndex: hover?.seriesIndex)
                        case .ended:
                            hover = nil
                            model.setHoveredPoint(rowIndex: nil, seriesIndex: nil)
                        }
                    }
            }
            .frame(minHeight: 120)
            .onChange(of: model.sourceName) { _, _ in
                hover = nil
                model.setHoveredPoint(rowIndex: nil, seriesIndex: nil)
            }

            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.system(size: 12)).foregroundStyle(.orange.opacity(0.9))
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .foregroundStyle(Color(white: 0.88))
        .background(Color.clear)
        .overlay {
            if isDropTargeted {
                RoundedRectangle(cornerRadius: 16).stroke(.cyan.opacity(0.8), style: StrokeStyle(lineWidth: 2, dash: [8, 5]))
                    .padding(8)
            }
        }
        .onDrop(of: [UTType.fileURL.identifier], isTargeted: $isDropTargeted, perform: acceptDrop)
        .accessibilityIdentifier("csv-line-chart-panel")
    }

    @ViewBuilder private func chart(in size: CGSize) -> some View {
        let plot = plotRect(in: size)
        let domains = yDomain
        let horizontalDomain = visibleXDomain
        ZStack(alignment: .topLeading) {
            Canvas { context, canvasSize in
                let chartRect = plotRect(in: canvasSize)
                for tick in 0...4 {
                    let y = chartRect.minY + chartRect.height * CGFloat(tick) / 4
                    var grid = Path()
                    grid.move(to: CGPoint(x: chartRect.minX, y: y))
                    grid.addLine(to: CGPoint(x: chartRect.maxX, y: y))
                    context.stroke(grid, with: .color(.white.opacity(0.09)), lineWidth: 1)
                }
                var yAxis = Path()
                yAxis.move(to: CGPoint(x: chartRect.minX, y: chartRect.minY))
                yAxis.addLine(to: CGPoint(x: chartRect.minX, y: chartRect.maxY))
                context.stroke(yAxis, with: .color(.white.opacity(0.16)), lineWidth: 1)
                context.clip(to: Path(chartRect))

                for (band, opacity) in model.filledBands where model.visibleSeries.contains(band.firstSeries)
                    && model.visibleSeries.contains(band.secondSeries) {
                    for rowIndex in 0..<max(0, model.data.rows.count - 1) {
                        let firstRow = model.data.rows[rowIndex]
                        let secondRow = model.data.rows[rowIndex + 1]
                        guard firstRow.values.indices.contains(band.firstSeries),
                              firstRow.values.indices.contains(band.secondSeries),
                              secondRow.values.indices.contains(band.firstSeries),
                              secondRow.values.indices.contains(band.secondSeries),
                              let firstA = firstRow.values[band.firstSeries],
                              let firstB = firstRow.values[band.secondSeries],
                              let secondA = secondRow.values[band.firstSeries],
                              let secondB = secondRow.values[band.secondSeries],
                              let a1 = chartPoint(rowIndex: rowIndex, seriesIndex: band.firstSeries, value: firstA,
                                                  in: canvasSize, yDomain: domains),
                              let b1 = chartPoint(rowIndex: rowIndex, seriesIndex: band.secondSeries, value: firstB,
                                                  in: canvasSize, yDomain: domains),
                              let a2 = chartPoint(rowIndex: rowIndex + 1, seriesIndex: band.firstSeries, value: secondA,
                                                  in: canvasSize, yDomain: domains),
                              let b2 = chartPoint(rowIndex: rowIndex + 1, seriesIndex: band.secondSeries, value: secondB,
                                                  in: canvasSize, yDomain: domains) else { continue }
                        var area = Path()
                        area.move(to: a1); area.addLine(to: a2); area.addLine(to: b2); area.addLine(to: b1); area.closeSubpath()
                        context.fill(area, with: .color(colors[band.firstSeries % colors.count].opacity(opacity)))
                    }
                }

                for seriesIndex in model.data.seriesNames.indices where model.visibleSeries.contains(seriesIndex) {
                    var path = Path()
                    var hasSegment = false
                    for (rowIndex, row) in model.data.rows.enumerated() {
                        guard seriesIndex < row.values.count, let value = row.values[seriesIndex],
                              let point = chartPoint(rowIndex: rowIndex, seriesIndex: seriesIndex,
                                                     value: value, in: canvasSize, yDomain: domains) else {
                            hasSegment = false
                            continue
                        }
                        if hasSegment { path.addLine(to: point) }
                        else { path.move(to: point); hasSegment = true }
                    }
                    context.stroke(path, with: .color(colors[seriesIndex % colors.count]),
                                   style: StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))
                    for (rowIndex, row) in model.data.rows.enumerated() {
                        guard seriesIndex < row.values.count, let value = row.values[seriesIndex],
                              let point = chartPoint(rowIndex: rowIndex, seriesIndex: seriesIndex,
                                                     value: value, in: canvasSize, yDomain: domains) else { continue }
                        let dot = CGRect(x: point.x - 3.5, y: point.y - 3.5, width: 7, height: 7)
                        context.fill(Path(ellipseIn: dot), with: .color(colors[seriesIndex % colors.count]))
                    }
                }

                if let hover, let point = chartPoint(for: hover, in: canvasSize, yDomain: domains) {
                    var guide = Path()
                    guide.move(to: CGPoint(x: point.x, y: chartRect.minY))
                    guide.addLine(to: CGPoint(x: point.x, y: chartRect.maxY))
                    context.stroke(guide, with: .color(.white.opacity(0.48)), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
                    let dot = CGRect(x: point.x - 5, y: point.y - 5, width: 10, height: 10)
                    context.fill(Path(ellipseIn: dot), with: .color(colors[hover.seriesIndex % colors.count]))
                }
            }

            ForEach(0...4, id: \.self) { tick in
                let value = domains.minimum + (domains.maximum - domains.minimum) * Double(4 - tick) / 4
                Text(value.formatted(.number.precision(.fractionLength(0))))
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.42))
                    .position(x: 24, y: plot.minY + plot.height * CGFloat(tick) / 4)
            }
            HStack {
                Text(model.data.rows.first(where: { $0.xValue >= horizontalDomain.minimum })?.xLabel ?? "")
                Spacer()
                Text(model.data.rows.last(where: { $0.xValue <= horizontalDomain.maximum })?.xLabel ?? "")
            }
            .font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.42))
            .position(x: size.width / 2, y: size.height - 8)
            if let hover, model.data.rows.indices.contains(hover.rowIndex),
               model.data.seriesNames.indices.contains(hover.seriesIndex),
               let value = model.data.rows[hover.rowIndex].values[hover.seriesIndex] {
                tooltip(row: model.data.rows[hover.rowIndex], seriesIndex: hover.seriesIndex, value: value)
                    .fixedSize()
                    .position(tooltipPosition(for: hover.location, in: size))
            }
        }
        .simultaneousGesture(MagnificationGesture()
            .onChanged { magnification in
                if zoomGestureStart == nil { zoomGestureStart = xZoom }
                setZoom((zoomGestureStart ?? xZoom) * magnification)
            }
            .onEnded { _ in zoomGestureStart = nil })
        .simultaneousGesture(DragGesture(minimumDistance: 14)
            .onChanged { value in
                if panGestureStart == nil { panGestureStart = xPan }
                let span = max(0.000001, fullXDomain.maximum - fullXDomain.minimum) / Double(xZoom)
                model.setXAxisViewport(zoom: xZoom,
                                       pan: (panGestureStart ?? xPan) - Double(value.translation.width / max(1, plot.width)) * span)
            }
            .onEnded { _ in panGestureStart = nil })
    }

    private func tooltip(row: CSVLineChartRow, seriesIndex: Int, value: Double) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(row.xLabel).font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.52))
            HStack(spacing: 6) {
                Circle().fill(colors[seriesIndex % colors.count]).frame(width: 7, height: 7)
                Text(model.data.seriesNames[seriesIndex]).font(.system(size: 11, weight: .medium))
                Spacer(minLength: 10)
                Text(value.formatted(.number.precision(.fractionLength(0...3))))
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
            }
            if !row.note.isEmpty {
                Rectangle().fill(.white.opacity(0.12)).frame(height: 1)
                Text(row.note).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 240, alignment: .leading)
            }
        }
        .padding(11)
        .background(.black.opacity(0.88), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(.white.opacity(0.12), lineWidth: 1))
        .shadow(color: .black.opacity(0.28), radius: 8, y: 3)
    }

    private var yDomain: (minimum: Double, maximum: Double) {
        let values = model.data.rows.flatMap { row in
            guard row.xValue >= visibleXDomain.minimum && row.xValue <= visibleXDomain.maximum else { return [Double]() }
            return model.visibleSeries.compactMap { index in index < row.values.count ? row.values[index] : nil }
        }
        guard let minimum = values.min(), let maximum = values.max() else { return (0, 1) }
        if minimum == maximum { return (minimum - 1, maximum + 1) }
        let padding = (maximum - minimum) * 0.08
        return (minimum - padding, maximum + padding)
    }

    private var fullXDomain: (minimum: Double, maximum: Double) {
        guard let minimum = model.data.rows.map(\.xValue).min(), let maximum = model.data.rows.map(\.xValue).max() else { return (0, 1) }
        if minimum == maximum { return (minimum - 0.5, maximum + 0.5) }
        return (minimum, maximum)
    }

    private var visibleXDomain: (minimum: Double, maximum: Double) {
        let full = fullXDomain
        let span = max(0.000001, full.maximum - full.minimum) / Double(xZoom)
        let halfSpan = span / 2
        let minCenter = full.minimum + halfSpan
        let maxCenter = full.maximum - halfSpan
        let center = min(max((full.minimum + full.maximum) / 2 + xPan, minCenter), maxCenter)
        return (center - halfSpan, center + halfSpan)
    }

    private func plotRect(in size: CGSize) -> CGRect {
        CGRect(x: 50, y: 14, width: max(1, size.width - 64), height: max(1, size.height - 48))
    }

    private func chartPoint(rowIndex: Int, seriesIndex: Int, value: Double, in size: CGSize,
                            yDomain: (minimum: Double, maximum: Double)) -> CGPoint? {
        guard model.data.rows.indices.contains(rowIndex), model.data.rows.count > 0 else { return nil }
        let plot = plotRect(in: size)
        let horizontalDomain = visibleXDomain
        let xFraction = (model.data.rows[rowIndex].xValue - horizontalDomain.minimum)
            / max(0.000001, horizontalDomain.maximum - horizontalDomain.minimum)
        let ySpan = max(0.000001, yDomain.maximum - yDomain.minimum)
        let yFraction = (value - yDomain.minimum) / ySpan
        return CGPoint(x: plot.minX + plot.width * xFraction,
                       y: plot.maxY - plot.height * yFraction)
    }

    private func chartPoint(for hover: ChartHover, in size: CGSize,
                            yDomain: (minimum: Double, maximum: Double)) -> CGPoint? {
        guard model.data.rows.indices.contains(hover.rowIndex),
              model.data.rows[hover.rowIndex].values.indices.contains(hover.seriesIndex),
              let value = model.data.rows[hover.rowIndex].values[hover.seriesIndex] else { return nil }
        return chartPoint(rowIndex: hover.rowIndex, seriesIndex: hover.seriesIndex, value: value,
                          in: size, yDomain: yDomain)
    }

    private func closestPoint(to location: CGPoint, in size: CGSize) -> ChartHover? {
        let domain = yDomain
        var closest: (hover: ChartHover, distance: CGFloat)?
        for (rowIndex, row) in model.data.rows.enumerated() {
            guard row.xValue >= visibleXDomain.minimum && row.xValue <= visibleXDomain.maximum else { continue }
            for seriesIndex in model.visibleSeries where row.values.indices.contains(seriesIndex) {
                guard let value = row.values[seriesIndex],
                      let point = chartPoint(rowIndex: rowIndex, seriesIndex: seriesIndex, value: value,
                                             in: size, yDomain: domain) else { continue }
                let distance = hypot(point.x - location.x, point.y - location.y)
                if closest == nil || distance < closest!.distance {
                    closest = (ChartHover(rowIndex: rowIndex, seriesIndex: seriesIndex, location: location), distance)
                }
            }
        }
        guard let closest, closest.distance <= 24 else { return nil }
        return closest.hover
    }

    private func tooltipPosition(for point: CGPoint, in size: CGSize) -> CGPoint {
        CGPoint(x: min(max(120, point.x + 115), max(120, size.width - 120)),
                y: max(60, point.y - 55))
    }

    private func setZoom(_ zoom: CGFloat) {
        model.setXAxisViewport(zoom: zoom, pan: xPan)
    }

    private func acceptDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) }) else { return false }
        provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
            guard let data, let url = URL(dataRepresentation: data, relativeTo: nil), url.pathExtension.lowercased() == "csv" else { return }
            Task { @MainActor in model.loadCSV(url) }
        }
        return true
    }
}
