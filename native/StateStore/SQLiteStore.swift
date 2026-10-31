import Foundation
import CSQLite
/// Accessed exclusively by HostState. The single snapshot transaction also commits idempotency results.
public final class SQLiteStore: @unchecked Sendable {
    private var db: OpaquePointer?
    public init(path: String) throws {
        guard sqlite3_open_v2(path, &db, SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK else { throw MUPError("storage", "Cannot open state store") }
        if path != ":memory:" {try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path)}
        try execute("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=3000;")
        var versionQuery:OpaquePointer?
        guard sqlite3_prepare_v2(db,"PRAGMA user_version",-1,&versionQuery,nil) == SQLITE_OK else {throw MUPError("storage","Cannot read schema version")}
        defer {sqlite3_finalize(versionQuery)}
        guard sqlite3_step(versionQuery) == SQLITE_ROW else {throw MUPError("storage","Cannot read schema version")}
        let version=sqlite3_column_int(versionQuery,0)
        guard version<=1 else {throw MUPError("storage","State schema is newer than this Host")}
        if version == 0 {
            try execute("BEGIN IMMEDIATE; CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL); CREATE TABLE audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, principal TEXT NOT NULL, action TEXT NOT NULL); PRAGMA user_version=1; COMMIT;")
        }
    }
    deinit { sqlite3_close(db) }
    private func execute(_ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else { throw MUPError("storage", "State transaction failed") }
    }
    public func load() throws -> DurableState {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT body FROM state WHERE id=1", -1, &stmt, nil) == SQLITE_OK else { throw MUPError("storage", "Cannot load state") }
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_step(stmt) == SQLITE_ROW else { return DurableState() }
        let data = Data(bytes: sqlite3_column_blob(stmt, 0)!, count: Int(sqlite3_column_bytes(stmt, 0)))
        return try JSONDecoder().decode(DurableState.self, from: data)
    }
    public func save(_ state: DurableState, principal: String, action: String) throws {
        let data = try JSONEncoder().encode(state)
        try execute("BEGIN IMMEDIATE")
        do {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, "INSERT INTO state(id,body) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", -1, &stmt, nil) == SQLITE_OK else { throw MUPError("storage", "Cannot prepare save") }
            defer { sqlite3_finalize(stmt) }
            let result = data.withUnsafeBytes { ptr -> Int32 in
                sqlite3_bind_blob(stmt, 1, ptr.baseAddress, Int32(data.count), unsafeBitCast(-1, to: sqlite3_destructor_type.self))
                return sqlite3_step(stmt)
            }
            guard result == SQLITE_DONE else { throw MUPError("storage", "Cannot save state") }
            var audit: OpaquePointer?
            guard sqlite3_prepare_v2(db, "INSERT INTO audit(at,principal,action) VALUES(?,?,?)", -1, &audit, nil) == SQLITE_OK else { throw MUPError("storage", "Cannot prepare audit") }
            defer { sqlite3_finalize(audit) }
            for (i, value) in [timestamp(),principal,action].enumerated() { _ = value.withCString { sqlite3_bind_text(audit, Int32(i+1), $0, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) } }
            guard sqlite3_step(audit) == SQLITE_DONE else { throw MUPError("storage", "Cannot record audit") }
            try execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 10000); COMMIT")
        } catch { try? execute("ROLLBACK"); throw error }
    }
}
