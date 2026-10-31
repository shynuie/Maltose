import XCTest
@testable import MaltoseCore

final class CanvasDocumentTests: XCTestCase {
    private func scene(_ child: JSON) -> JSON {
        .object(["root":.object(["node_id":.s("scene"),"type":.s("canvas"),"props":.object(["width":.n(640),"height":.n(480)]),"children":.array([child])])])
    }

    func testBoundedCanvasElementsAreValidAndIndexedForAwareness() throws {
        let shape:JSON = .object(["node_id":.s("house"),"type":.s("canvas.rect"),"props":.object(["x":.n(180),"y":.n(150),"width":.n(220),"height":.n(170),"color":.s("#F4B183"),"label":.s("小房子")])])
        let document=scene(shape)
        XCTAssertNoThrow(try Document.validate(document))
        XCTAssertEqual(Document.nodes(document["root"]).compactMap {$0["node_id"].string},["scene","house"])
    }

    func testCanvasRejectsUnboundedGeometryUnsafeColorAndWrongParent() throws {
        let outOfBounds:JSON = .object(["node_id":.s("house"),"type":.s("canvas.rect"),"props":.object(["x":.n(5000),"y":.n(0),"width":.n(20),"height":.n(20)])])
        XCTAssertThrowsError(try Document.validate(scene(outOfBounds)))
        let outsideCanvas:JSON = .object(["node_id":.s("house"),"type":.s("canvas.rect"),"props":.object(["x":.n(630),"y":.n(0),"width":.n(20),"height":.n(20)])])
        XCTAssertThrowsError(try Document.validate(scene(outsideCanvas)))
        let wrongColor:JSON = .object(["node_id":.s("house"),"type":.s("canvas.rect"),"props":.object(["x":.n(0),"y":.n(0),"width":.n(20),"height":.n(20),"color":.s("url(javascript:alert(1))")])])
        XCTAssertThrowsError(try Document.validate(scene(wrongColor)))
        let orphan:JSON = .object(["root":outOfBounds])
        XCTAssertThrowsError(try Document.validate(orphan))
    }
}
