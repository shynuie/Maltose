import Foundation
import CryptoKit

/// Bounded structured observations; missing values stay missing, never zero-filled.
struct ResultChart: Codable, Equatable {
    let title: String
    let caption: String
    let xTitle: String
    let series: [String]
    let rows: [Row]
    struct Row: Codable, Equatable {
        let x: String
        let values: [Double?]
        let note: String
    }
    func validate() throws {
        func text(_ value: String, _ limit: Int) -> Bool {
            !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.utf8.count <= limit && value.rangeOfCharacter(from: .controlCharacters) == nil
        }
        guard text(title, 200), text(caption, 2000), text(xTitle, 100),
              (1...8).contains(series.count), Set(series).count == series.count, series.allSatisfy({ text($0, 200) }),
              (2...366).contains(rows.count), rows.allSatisfy({ text($0.x, 100) && text($0.note, 2000) && $0.values.count == series.count && $0.values.allSatisfy({ $0?.isFinite ?? true }) }),
              rows.flatMap({ $0.values }).compactMap({ $0 }).count >= 2,
              try JSONEncoder().encode(self).count <= 128 * 1024 else {
            throw RuntimeLaunchError.unavailable("圖表需要有效數值、來源備註及符合大小限制的資料。")
        }
    }
}

/// A saved publication intent, independent of task completion and audio playback.
struct ResultDeliveryRecord: Codable, Equatable {
    let publicationID: String
    let conversationID: String
    let messageID: String
    let title: String
    let markdown: String
    let createDocument: Bool
    var panelApplied = false
    var closed = false
    var chart: ResultChart? = nil
    // Optional for compatibility with journals saved before structured charts.
    var chartApplied: Bool? = nil
    var chartClosed: Bool? = nil

    var chartPanelID: String? {
        chart == nil ? nil : "result-chart-" + SHA256.hash(data: Data(publicationID.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    var panelID: String? {
        createDocument ? "result-" + SHA256.hash(data: Data(publicationID.utf8)).map { String(format: "%02x", $0) }.joined() : nil
    }
    func validate() throws {
        try chart?.validate()
        guard chart != nil || (chartApplied != true && chartClosed != true) else { throw RuntimeLaunchError.unavailable("圖表回執缺少原始資料。") }
        guard publicationID.range(of: "^[A-Za-z0-9._:-]{1,128}$", options: .regularExpression) != nil,
              messageID.range(of: "^[A-Za-z0-9._:-]{1,128}$", options: .regularExpression) != nil,
              !conversationID.isEmpty, conversationID.utf8.count <= 128,
              conversationID.rangeOfCharacter(from: .controlCharacters) == nil,
              !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, title.utf8.count <= 200,
              title.rangeOfCharacter(from: .controlCharacters) == nil,
              !markdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, markdown.utf8.count <= 256 * 1024,
              createDocument || (!panelApplied && !closed) else {
            throw RuntimeLaunchError.unavailable("成果發表的內容、識別碼或大小不正確。")
        }
    }
    func matches(_ other: Self) -> Bool {
        var first = self, second = other
        first.chartApplied = nil; first.chartClosed = nil
        second.chartApplied = nil; second.chartClosed = nil
        first.panelApplied = false; first.closed = false
        second.panelApplied = false; second.closed = false
        return first == second
    }
}
