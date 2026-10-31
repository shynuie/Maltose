import Foundation
import MaltoseCore
@main struct HeadlessHost {
    static func main() async throws {
        let args=CommandLine.arguments
        func value(_ flag:String)->String? {guard let i=args.firstIndex(of:flag),i+1<args.count else {return nil};return args[i+1]}
        let registry=AgentRegistry()
        if let principal=value("--register") { print(try await registry.register(principal));return }
        if let principal=value("--revoke") { try await registry.revoke(principal);return }
        guard let statePath=value("--state") else {print("Usage: MaltoseHost --state PATH [--port 8765] | --register AGENT | --revoke AGENT");return}
        let host=try HostState(path:statePath)
        let server=try LoopbackServer(host:host,registry:registry,port:UInt16(value("--port") ?? "8765") ?? 8765)
        let port=try await server.start()
        print("Maltose MUP v0.3 listening at 127.0.0.1:\(port)")
        // Keeping this process alive does not grant observation of any other application.
        while !Task.isCancelled {try await Task.sleep(for:.seconds(30))}
        server.stop()
    }
}
