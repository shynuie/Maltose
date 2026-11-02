import Foundation
import CryptoKit

/// Proof of a static response page or an entire extracted source table, not
/// verification of the publisher's claims or of unread document pages.
enum PublicWebSourceReceipt {
    static func valid(arguments: [String: UserViewValue], result: UserViewValue) -> Bool {
        func integer(_ key: String) -> Int? {
            guard case let .number(value)? = result[key], value.isFinite, value.rounded()==value, value>=0, value<=2*1024*1024 else {return nil}
            return Int(value)
        }
        func hash(_ text: String) -> String {SHA256.hash(data:Data(text.utf8)).map {String(format:"%02x",$0)}.joined()}
        func webURL(_ text: String?) -> Bool {
            guard let text,let url=URL(string:text),["http","https"].contains(url.scheme?.lowercased() ?? ""),url.host != nil,url.user==nil,url.password==nil else {return false}
            return true
        }
        guard result["ok"] == .boolean(true),result["schemaVersion"] == .number(1),result["fetchedComplete"] == .boolean(true),
              let identity=result["sourceID"]?.stringValue,identity.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil,
              webURL(result["url"]?.stringValue),webURL(result["requestedURL"]?.stringValue),
              ["contentSHA256","textSHA256","pageSHA256"].allSatisfy({result[$0]?.stringValue?.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil}),
              let page=integer("pageIndex"),let count=integer("pageCount"),count>0,page<count,
              let offset=integer("pageOffset"),let bytes=integer("pageBytes"),let total=integer("textBytes"),integer("bytes") != nil,integer("tableCount") != nil,
              let text=result["text"]?.stringValue,bytes==text.utf8.count,offset+bytes<=total,result["pageSHA256"] == .string(hash(text)),
              result["tableSelection"] == (arguments["tableID"] ?? .null),arguments["page", default:.number(0)] == .number(Double(page)) else {return false}
        if let url=arguments["url"] {guard result["requestedURL"]==url else {return false}}
        else {guard arguments["sourceID"] == .string(identity) else {return false}}
        if result["textComplete"] == .boolean(true) {
            guard page==0,count==1,offset==0,bytes==total,result["textSHA256"] == .string(hash(text)),result["textIncluded"] == .boolean(true) else {return false}
        }
        guard let tables=result["tables"]?.arrayValue else {return false}
        var seen=Set<String>()
        for table in tables {
            guard let id=table["id"]?.stringValue,seen.insert(id).inserted,table["complete"] == .boolean(true),
                  let csv=table["text"]?.stringValue,table["bytes"] == .number(Double(csv.utf8.count)),table["sha256"] == .string(hash(csv)),
                  let rowCount=table["rows"]?.numberValue,let columns=table["columns"]?.numberValue else {return false}
            let rows=CSVLineChartParser.records(from:csv)
            guard rows.count>=3,rows.count<=367,rowCount==Double(rows.count-1),columns>=2,columns<=16,
                  rows.allSatisfy({Double($0.count)==columns}) else {return false}
        }
        return true
    }
}

extension UserViewValue {
    var numberValue: Double? {if case let .number(value)=self {value} else {nil}}
}
