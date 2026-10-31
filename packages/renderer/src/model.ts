import { z } from 'zod';
const idSchema=z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/);
const colorSchema=z.string().regex(/^#[0-9A-Fa-f]{6}$/);
export const propsSchema = z.object({
 text:z.string().max(16384).optional(),title:z.string().max(16384).optional(),label:z.string().max(16384).optional(),action_id:idSchema.optional(),
 columns:z.array(z.string().max(256)).max(32).optional(),
 rows:z.array(z.array(z.union([z.string().max(4096),z.number(),z.boolean(),z.null()])).max(32)).max(1000).optional(),
 points:z.array(z.tuple([z.union([z.string().min(1).max(256),z.number()]),z.union([z.string().min(1).max(256),z.number()])])).max(10000).optional(),
 data_id:idSchema.optional(),sensitive:z.boolean().optional(),x:z.number().min(0).max(4096).optional(),y:z.number().min(0).max(4096).optional(),
 width:z.number().min(1).max(4096).optional(),height:z.number().min(1).max(4096).optional(),color:colorSchema.optional(),background_color:colorSchema.optional()
}).strict();
export type NodeType='stack'|'text'|'button'|'table'|'chart.line'|'canvas'|'canvas.rect'|'canvas.ellipse'|'canvas.triangle'|'canvas.text';
export type Node = {node_id:string;type:NodeType;props:z.infer<typeof propsSchema>;children?:Node[]};
const primitiveTypes:NodeType[]=['canvas.rect','canvas.ellipse','canvas.triangle','canvas.text'];
export const nodeSchema:z.ZodType<Node> = z.lazy(()=>z.object({node_id:idSchema,type:z.enum(['stack','text','button','table','chart.line','canvas','canvas.rect','canvas.ellipse','canvas.triangle','canvas.text']),props:propsSchema,children:z.array(nodeSchema).max(256).optional()}).strict()).superRefine((node,ctx)=>{
 if(node.type==='canvas'){
  if(node.props.width===undefined||node.props.height===undefined)ctx.addIssue({code:'custom',path:['props'],message:'Canvas requires width and height'});
  if(node.children?.some(child=>!primitiveTypes.includes(child.type)))ctx.addIssue({code:'custom',path:['children'],message:'Canvas accepts only typed vector elements'});
  for(const [index,child] of (node.children??[]).entries()){
   const p=child.props;
   if(p.x!==undefined&&p.y!==undefined&&p.width!==undefined&&p.height!==undefined&&node.props.width!==undefined&&node.props.height!==undefined&&(p.x+p.width>node.props.width||p.y+p.height>node.props.height))ctx.addIssue({code:'custom',path:['children',index,'props'],message:'Canvas elements must fit inside the canvas'});
  }
 }else if(primitiveTypes.includes(node.type)){
  for(const key of ['x','y','width','height'] as const)if(node.props[key]===undefined)ctx.addIssue({code:'custom',path:['props',key],message:'Canvas element requires bounded geometry'});
  if(node.props.label!==undefined&&node.props.label.length>2048)ctx.addIssue({code:'custom',path:['props','label'],message:'Canvas label is too long'});
  if(node.children?.length)ctx.addIssue({code:'custom',path:['children'],message:'Canvas elements cannot contain children'});
 }else if(node.type!=='stack'&&node.children?.length)ctx.addIssue({code:'custom',path:['children'],message:'Only stacks and canvases may contain children'});
});
export const documentSchema = z.object({root:nodeSchema,actions:z.array(idSchema).max(128).optional()}).strict().superRefine(({root},ctx)=>{
 const visit=(node:Node,parent:NodeType|undefined,path:(string|number)[])=>{
  if(primitiveTypes.includes(node.type)&&parent!=='canvas')ctx.addIssue({code:'custom',path,message:'Canvas elements must be children of a canvas'});
  if(parent==='canvas'&&!primitiveTypes.includes(node.type))ctx.addIssue({code:'custom',path,message:'Canvas accepts only typed vector elements'});
  node.children?.forEach((child,index)=>visit(child,node.type,[...path,'children',index]));
 };
 visit(root,undefined,['root']);
});
export const snapshotSchema = z.object({surface_id:z.string(),document_revision:z.number().int(),document:documentSchema,selection:z.unknown().nullable(),viewport:z.unknown().nullable(),streams:z.record(z.object({points:z.array(z.tuple([z.union([z.string(),z.number()]),z.union([z.string(),z.number()])])),stale:z.boolean()}))}).strict();
export type Snapshot = z.infer<typeof snapshotSchema>;
export function debounce<T extends unknown[]>(fn:(...a:T)=>void,ms:number){let timer:ReturnType<typeof setTimeout>;return (...a:T)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...a),ms);};}
