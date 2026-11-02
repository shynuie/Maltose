import CryptoKit
import Foundation
import XCTest
@testable import MaltoseApp

@MainActor final class PublicWebSourceTests: XCTestCase {
    func fixture() throws -> [String:UserViewValue] {
        func hash(_ text:String)->String {SHA256.hash(data:Data(text.utf8)).map {String(format:"%02x",$0)}.joined()}
        let text="日期,比例%\n2026-01,40\n2026-02,42\n"
        let value:[String:Any] = ["ok":true,"schemaVersion":1,"sourceID":String(repeating:"a",count:32),"requestedURL":"https://example.org/survey","url":"https://example.org/survey",
            "fetchedComplete":true,"contentSHA256":hash(text),"textSHA256":hash(text),"pageSHA256":hash(text),"pageIndex":0,"pageCount":1,"pageOffset":0,"pageBytes":text.utf8.count,
            "textBytes":text.utf8.count,"bytes":text.utf8.count,"tableCount":1,"text":text,"textComplete":true,"textIncluded":true,"tableSelection":NSNull(),
            "tables":[["id":"table-1","text":text,"bytes":text.utf8.count,"sha256":hash(text),"rows":2,"columns":2,"complete":true]]]
        return try JSONDecoder().decode([String:UserViewValue].self,from:JSONSerialization.data(withJSONObject:value))
    }
    func testActualSourceReceiptCanProveReadButNotUnrelatedSourceOrDocumentCompleteness() throws {
        let result=try fixture();let args:[String:UserViewValue] = ["url":.string("https://example.org/survey")]
        let observation=ProductToolObservation(id:String(repeating:"b",count:32),tool:"read_web_page",arguments:args,result:.object(result),truncated:false)
        let evidence=try observation.evidence(executionID:"main")
        XCTAssertEqual(evidence.kind,.sourceRead);XCTAssertEqual(evidence.verdict,.passed)
        for key in ["contentSHA256","pageSHA256","sourceID"] {
            var bad=result;bad[key] = .string("not-a-proof")
            XCTAssertFalse(PublicWebSourceReceipt.valid(arguments:args,result:.object(bad)))
        }
        XCTAssertFalse(PublicWebSourceReceipt.valid(arguments:["url":.string("https://other.example/")],result:.object(result)))
        var bad=result;bad["pageCount"] = .number(2)
        XCTAssertFalse(PublicWebSourceReceipt.valid(arguments:args,result:.object(bad)))
        bad["textComplete"] = .boolean(false)
        XCTAssertTrue(PublicWebSourceReceipt.valid(arguments:args,result:.object(bad)),"An actual partial text page remains a source read, not proof of the whole document")
        XCTAssertFalse(PublicWebSourceReceipt.valid(arguments:["url":args["url"]!,"page":.number(1e300)],result:.object(result)))
    }
    func testChangedTableRowsAndCorruptedPayloadCannotBecomePassingReadEvidence() throws {
        let original=try fixture();let args:[String:UserViewValue] = ["url":.string("https://example.org/survey")]
        for value in [UserViewValue.number(3),.number(1),.boolean(true)] {
            var result=original;var tables=try XCTUnwrap(result["tables"]?.arrayValue);var table=try XCTUnwrap(tables[0].objectValue)
            table["rows"]=value;tables[0] = .object(table);result["tables"] = .array(tables)
            let evidence=try ProductToolObservation(id:String(repeating:"b",count:32),tool:"read_web_page",arguments:args,result:.object(result),truncated:false).evidence(executionID:"main")
            XCTAssertNotEqual(evidence.verdict,.passed)
        }
        let evidence=try ProductToolObservation(id:String(repeating:"b",count:32),tool:"read_web_page",arguments:args,result:.object(original),truncated:true).evidence(executionID:"main")
        XCTAssertNotEqual(evidence.verdict,.passed)
    }
}
