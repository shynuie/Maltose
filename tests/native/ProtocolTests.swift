import XCTest
@testable import MaltoseCore
final class ProtocolTests: XCTestCase {
    func testProtocolVersion() { XCTAssertEqual(MUP.version, "mup/0.3") }
}
