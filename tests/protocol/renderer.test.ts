import {test,expect,vi} from 'vitest';
import {documentSchema,debounce} from '../../packages/renderer/src/model';
test('renderer rejects executable components and unknown props',()=>{
 expect(documentSchema.safeParse({root:{node_id:'x',type:'script',props:{}}}).success).toBe(false);
 expect(documentSchema.safeParse({root:{node_id:'x',type:'text',props:{text:'<script>ignored</script>',onclick:'evil()'}}}).success).toBe(false);
});
test('typed canvas accepts only bounded vector primitives and colors',()=>{
 const valid={root:{node_id:'scene',type:'canvas',props:{width:640,height:480},children:[{node_id:'house',type:'canvas.rect',props:{x:180,y:150,width:220,height:170,color:'#F4B183',label:'小房子'}},{node_id:'caption',type:'canvas.text',props:{x:190,y:370,width:180,height:24,label:'安全文字',color:'#E5E7EB'}}]}};
 expect(documentSchema.safeParse(valid).success).toBe(true);
 expect(documentSchema.safeParse({root:{...valid.root,children:[{node_id:'bad',type:'canvas.rect',props:{x:0,y:0,width:20,height:20,color:'url(javascript:alert(1))'}}]}}).success).toBe(false);
 expect(documentSchema.safeParse({root:{node_id:'orphan',type:'canvas.rect',props:{x:0,y:0,width:20,height:20}}}).success).toBe(false);
 expect(documentSchema.safeParse({root:{...valid.root,children:[{node_id:'nested',type:'stack',props:{},children:[]}]}}).success).toBe(false);
 expect(documentSchema.safeParse({root:{...valid.root,children:[{node_id:'overflow',type:'canvas.rect',props:{x:600,y:0,width:100,height:20}}]}}).success).toBe(false);
});
test('viewport emissions are coalesced without delaying local state',()=>{
 vi.useFakeTimers();const fn=vi.fn();const emit=debounce(fn,120);emit(1);emit(2);expect(fn).not.toHaveBeenCalled();vi.advanceTimersByTime(120);expect(fn).toHaveBeenCalledExactlyOnceWith(2);vi.useRealTimers();
});
