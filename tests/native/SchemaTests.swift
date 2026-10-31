import Foundation
import XCTest
@testable import MaltoseCore
final class SchemaTests: XCTestCase {
    func testSharedFixtures() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        for (file, valid) in [("valid",true),("invalid",false)] {
            let fixtures = try JSON.decode(Data(contentsOf: root.appendingPathComponent("packages/mup-protocol/fixtures/\(file).json"))).array!
            for fixture in fixtures {
                if valid { XCTAssertNoThrow(try SchemaValidator.command(fixture.data())) }
                else { XCTAssertThrowsError(try SchemaValidator.command(fixture.data())) }
            }
        }
    }
    func testSizeAndMalformed() {
        XCTAssertThrowsError(try SchemaValidator.command(Data(repeating: 0, count: 1_048_577)))
        XCTAssertThrowsError(try SchemaValidator.command(Data("{".utf8)))
    }
}
