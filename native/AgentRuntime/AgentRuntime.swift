import Foundation
public struct AgentRuntimeView:Sendable,Identifiable {
    public let id:String
    public var phase="initializing"
    public var modelActive=false
    public var speechActive=false
    public var tool:String?
    public var lastSeen=Date()
    public var connected=true
    public var messages:[RuntimeMessage]=[]
    public var progress:String?
    var sessionID:String
    var runID:String
    var sequence = -1
    public var phaseLabel:String { ["initializing":"啟動中","standby":"待命中","listening":"聆聽中","thinking":"思考中","speaking":"播報中","shutdown":"已停止","error":"發生錯誤"][phase] ?? phase }
    public var isLive:Bool {connected && Date().timeIntervalSince(lastSeen)<=15}
    public var connectionLabel:String {connected ? (Date().timeIntervalSince(lastSeen)>15 ? "連線逾時" : "已連線") : "已離線"}
}
public struct RuntimeMessage:Sendable,Identifiable {public let id:String;public let role:String;public var text:String}
extension HostState {
    func runtimePublish(_ p:JSON,principal:String,sessionID:String) throws->JSON {
        let runID=p["run_id"].string!,sequence=p["sequence"].int!,kind=p["event"].string!,data=p["data"]
        var status=runtimes[principal] ?? AgentRuntimeView(id:principal,sessionID:sessionID,runID:runID)
        if status.sessionID != sessionID {
            guard !status.connected || Date().timeIntervalSince(status.lastSeen)>15 else {throw MUPError("runtime_busy","Another live session publishes this agent runtime")}
            status=AgentRuntimeView(id:principal,sessionID:sessionID,runID:runID)
        }
        guard status.runID == runID,sequence>status.sequence else {throw MUPError("duplicate_event","Runtime run or sequence mismatch")}
        status.sequence=sequence;status.lastSeen=Date();status.connected=true
        switch kind {
        case "state_changed":status.phase=data["state"].string ?? status.phase
        case "model_started":status.modelActive=true
        case "model_finished", "model_failed":status.modelActive=false
        case "speech_started":status.speechActive=true
        case "speech_finished":status.speechActive=false
        case "tool_started":status.tool=data["tool"].string
        case "tool_finished", "tool_failed":status.tool=nil
        case "task_progress":status.progress=data["detail"].string
        case "user_message":status.messages.append(RuntimeMessage(id:UUID().uuidString,role:"user",text:data["content"].string ?? ""))
        case "assistant_start":status.messages.append(RuntimeMessage(id:data["message_id"].string ?? UUID().uuidString,role:"assistant",text:""))
        case "assistant_delta":
            if let index=status.messages.lastIndex(where:{$0.id == data["message_id"].string}) {status.messages[index].text=String((status.messages[index].text+(data["content"].string ?? "")).suffix(16384))}
        case "assistant_end":
            if let index=status.messages.lastIndex(where:{$0.id == data["message_id"].string}),let content=data["content"].string {status.messages[index].text=String(content.suffix(16384))}
        case "error":status.phase="error";status.progress=data["detail"].string
        default:break
        }
        if status.messages.count>20 {status.messages.removeFirst(status.messages.count-20)}
        runtimes[principal]=status
        return .object(["accepted_sequence":.n(sequence)])
    }
    public func runtimeViews()->[AgentRuntimeView] {runtimes.values.sorted {$0.id<$1.id}}
    public func sendRuntimeInput(principal:String,text:String) throws {
        guard let status=runtimes[principal],status.connected,Date().timeIntervalSince(status.lastSeen)<=15 else {throw MUPError("offline","Agent is offline")}
        guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,text.utf8.count<=16384 else {throw MUPError("invalid_input","Input is empty or too long")}
        guard runtimeInputs[status.sessionID,default:[]].count<32 else {throw MUPError("quota","Agent input queue is full")}
        runtimeInputs[status.sessionID,default:[]].append(.object(["input_id":.s(UUID().uuidString),"kind":.s("text"),"text":.s(text)]))
    }
    func runtimeInputsPoll(sessionID:String)->JSON {.array(runtimeInputs.removeValue(forKey:sessionID) ?? [])}
}
