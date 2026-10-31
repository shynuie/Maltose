import { snapshotSchema, type Snapshot } from './model';
declare global {interface Window {webkit?:{messageHandlers:{maltose:{postMessage:(v:unknown)=>Promise<unknown>}}}}}
let snapshot:Snapshot|undefined;
let sequence=0;
export async function readSnapshot(){
    const value = await window.webkit?.messageHandlers.maltose.postMessage({kind:'ready'});
    if(value) snapshot = snapshotSchema.parse(value);
    return snapshot;
}
export function emit(kind:string,node_id:string,fields:Record<string,unknown>={}){
    if(!snapshot) return;
    void window.webkit?.messageHandlers.maltose.postMessage({surface_id:snapshot.surface_id,document_revision:snapshot.document_revision,sequence:++sequence,kind,node_id,...fields}).catch(()=>{});
}
