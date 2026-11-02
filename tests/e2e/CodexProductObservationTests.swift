import XCTest
@testable import MaltoseApp

@MainActor final class CodexProductObservationTests: XCTestCase {
    func testLiteralSDKTestCommandsAreParsedWithoutShellEvaluationOrCompoundExitStatus() {
        XCTAssertEqual(CodexProductObservation.testArguments("/bin/zsh -lc 'python3 -m unittest test_calculator'"), ["python3", "-m", "unittest", "test_calculator"])
        XCTAssertEqual(CodexProductObservation.testArguments("/bin/bash -lc \"uv run python -m pytest -q\""), ["python", "-m", "pytest", "-q"])
        for command in ["/bin/zsh -lc 'python -m unittest; echo OK'", "python -m unittest && echo OK", "echo 'python -m unittest'",
                        "python -m unittest $(echo tests)", "pytest --version", "python -c 'print(\"OK\")'", "python -m unittest > output.txt"] {
            XCTAssertNil(CodexProductObservation.testArguments(command), command)
        }
    }

    func testSDKProofKeepsPinnedOriginAndRequiresMatchingCommandCwdAndCompleteOutput() throws {
        let command = "/bin/zsh -lc 'python3 -m unittest test_calculator'"
        let origin = CodexProductObservationOrigin(itemID: "test", itemType: "commandExecution", executionID: "old-version", requirementsRevision: 1, planVersion: 1, command: command)
        let item = UserViewValue.object(["id": .string("test"), "type": .string("commandExecution"), "command": .string(command),
            "cwd": .string("/fixture"), "status": .string("completed"), "exitCode": .number(0), "aggregatedOutput": .string("Ran 3 tests\nOK")])
        let proof = try CodexProductObservation.evidence(item: item, origin: origin, messageID: "actual-sdk-item", worktree: "/fixture", scope: "scope")
        XCTAssertEqual(proof.executionID, "old-version"); XCTAssertEqual(proof.kind, .verification)
        XCTAssertEqual(proof.verdict, .passed); XCTAssertTrue(proof.detail.contains("Ran 3 tests"))
        XCTAssertEqual(try CodexProductObservation.evidence(item: item, origin: origin, messageID: "actual-sdk-item", worktree: "/other", scope: "scope").kind, .execution)
        let wrong = CodexProductObservationOrigin(itemID: "test", itemType: "commandExecution", executionID: "old-version", requirementsRevision: 1, planVersion: 1, command: "echo ok")
        XCTAssertEqual(try CodexProductObservation.evidence(item: item, origin: wrong, messageID: "actual-sdk-item", worktree: "/fixture", scope: "scope").verdict, .unknown)
        let changed = UserViewValue.object(["id": .string("edit"), "type": .string("fileChange"), "status": .string("completed")])
        XCTAssertTrue(try CodexProductObservation.evidence(item: changed, origin: origin, messageID: "edit", worktree: "/fixture", scope: "scope").invalidatesVerification == true)
    }
}
