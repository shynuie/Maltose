import Foundation
import Security
import CryptoKit
public protocol CredentialStore: Sendable {
    func credentials() throws -> [String:Data]
    func save(principal: String, token: Data) throws
    func remove(principal: String) throws
}
public struct KeychainCredentials: CredentialStore {
    private let service:String
    public init(service:String = "local.maltose.ui-host.v0.3") {self.service=service}
    public func credentials() throws -> [String:Data] {
        let query: [String:Any] = [kSecClass as String:kSecClassGenericPassword, kSecAttrService as String:service, kSecReturnAttributes as String:true, kSecMatchLimit as String:kSecMatchLimitAll]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return [:] }
        guard status == errSecSuccess else { throw MUPError("keychain", "Credential store unavailable (OSStatus \(status))") }
        var values: [String:Data] = [:]
        for item in result as? [[String:Any]] ?? [] {
            guard let account=item[kSecAttrAccount as String] as? String else {continue}
            let exact:[String:Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrAccount as String:account,kSecReturnData as String:true,kSecMatchLimit as String:kSecMatchLimitOne]
            var data:CFTypeRef?
            let readStatus=SecItemCopyMatching(exact as CFDictionary,&data)
            guard readStatus == errSecSuccess,let token=data as? Data else {throw MUPError("keychain","Cannot read registered credential (OSStatus \(readStatus))")}
            values[account]=token
        }
        return values
    }
    public func save(principal: String, token: Data) throws {
        let query:[String:Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrAccount as String:principal]
        let status=SecItemUpdate(query as CFDictionary,[kSecValueData as String:token] as CFDictionary)
        if status == errSecSuccess {return}
        guard status == errSecItemNotFound else {throw MUPError("keychain","Cannot rotate credential (OSStatus \(status))")}
        let item: [String:Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrAccount as String:principal,kSecValueData as String:token,kSecAttrAccessible as String:kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let addStatus=SecItemAdd(item as CFDictionary,nil)
        guard addStatus == errSecSuccess else {throw MUPError("keychain","Cannot save credential (OSStatus \(addStatus))")}
    }
    public func remove(principal: String) throws {
        let status = SecItemDelete([kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrAccount as String:principal] as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw MUPError("keychain", "Cannot revoke credential (OSStatus \(status))") }
    }
}
public actor AgentRegistry {
    private let store: any CredentialStore
    private var credentialDigests:[String:[UInt8]]?
    private func digests() throws->[String:[UInt8]] {
        if let credentialDigests {return credentialDigests}
        let loaded=try store.credentials().mapValues {Array(SHA256.hash(data:$0))}
        credentialDigests=loaded;return loaded
    }
    public init(store: any CredentialStore = KeychainCredentials()) { self.store = store }
    /// Trusted local user flow only, never available as a remote MUP command.
    public func register(_ principal: String) throws -> String {
        guard principal.range(of: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", options: .regularExpression) != nil else { throw MUPError("invalid_principal", "Invalid agent identifier") }
        let existing=try digests()
        guard existing[principal] != nil || existing.count<32 else {throw MUPError("quota","Agent registration quota reached")}
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw MUPError("credential", "Secure random unavailable") }
        let token = Data(bytes).base64EncodedString()
        try store.save(principal: principal, token: Data(token.utf8))
        credentialDigests?[principal]=Array(SHA256.hash(data:Data(token.utf8)))
        return token
    }
    /// Atomic admission for pairing: an existing identity may never inherit another approval.
    public func registerNew(_ principal:String) throws->String {
        guard try digests()[principal] == nil else {throw MUPError("principal_exists","Agent ID already exists; revoke it explicitly or choose a new ID")}
        return try register(principal)
    }
    public func authenticate(_ token: String) throws -> String {
        let digest = Array(SHA256.hash(data: Data(token.utf8)))
        for (principal, expected) in try digests() {
            var difference: UInt8 = 0
            for i in digest.indices { difference |= digest[i] ^ expected[i] }
            if difference == 0 { return principal }
        }
        throw MUPError("unauthenticated", "Invalid or revoked credential")
    }
    public func revoke(_ principal: String) throws { try store.remove(principal: principal);credentialDigests?.removeValue(forKey:principal) }
    public func principals() throws -> [String] { try digests().keys.sorted() }
}
