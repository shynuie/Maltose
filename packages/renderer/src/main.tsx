import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import * as echarts from 'echarts/core';
import {LineChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,DataZoomComponent,BrushComponent,ToolboxComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
import type {Node,Snapshot} from './model';
import {debounce} from './model';
import {readSnapshot,emit} from './bridge';
import './style.css';
echarts.use([LineChart,GridComponent,TooltipComponent,DataZoomComponent,BrushComponent,ToolboxComponent,CanvasRenderer]);
function Chart({node,snapshot}:{node:Node;snapshot:Snapshot}){
    const el=useRef<HTMLDivElement>(null), chart=useRef<echarts.ECharts>(undefined);
    const stream=node.props.data_id?snapshot.streams[node.props.data_id]:undefined;
    const points=stream?.points??node.props.points??[];
    useEffect(()=>{
        if(!el.current)return;
        const c=echarts.init(el.current,undefined,{renderer:'canvas'});chart.current=c;
        c.setOption({animation:false,grid:{left:48,right:24,top:24,bottom:80},xAxis:{type:'category',data:points.map(p=>p[0]),axisLabel:{color:'#94a3b8'}},yAxis:{type:'value',scale:true,splitLine:{lineStyle:{color:'#253244'}},axisLabel:{color:'#94a3b8'}},tooltip:{trigger:'axis'},toolbox:{feature:{brush:{type:['lineX','clear']}}},brush:{xAxisIndex:0,brushMode:'single'},dataZoom:[{type:'inside'},{type:'slider',bottom:12}],series:[{type:'line',data:points.map(p=>p[1]),showSymbol:false,lineStyle:{color:'#61dcc3',width:2},areaStyle:{color:'#61dcc320'}}]});
        const viewport=snapshot.viewport as {node_id?:string;x_domain?:[string|number,string|number]}|null;
        if(viewport?.node_id===node.node_id&&viewport.x_domain)c.dispatchAction({type:'dataZoom',startValue:viewport.x_domain[0],endValue:viewport.x_domain[1]});
        const selection=snapshot.selection as {node_id?:string;value?:{start?:unknown;end?:unknown}}|null;
        if(selection?.node_id===node.node_id&&selection.value)c.dispatchAction({type:'brush',areas:[{brushType:'lineX',xAxisIndex:0,coordRange:[selection.value.start,selection.value.end]}]});
        c.on('datazoom',debounce(()=>{
            const zoom=(c.getOption().dataZoom as Array<{start:number;end:number}>)[0];
            const xs=(c.getOption().xAxis as Array<{data:Array<string|number>}>)[0].data;
            if(xs.length){const range=[xs[Math.round(zoom.start/100*(xs.length-1))],xs[Math.round(zoom.end/100*(xs.length-1))]];emit('viewport_changed',node.node_id,{viewport:{node_id:node.node_id,x_domain:range}});}
        },120));
        c.on('brushEnd',(params:unknown)=>{
            const areas=(params as {areas?:Array<{coordRange?:[number,number]}>}).areas;
            if(!areas?.length){emit('selection_changed',node.node_id,{selection:null});return;}
            if(areas?.[0]?.coordRange){const [a,b]=areas[0].coordRange;const xs=(c.getOption().xAxis as Array<{data:Array<string|number>}>)[0].data;emit('selection_changed',node.node_id,{selection:{node_id:node.node_id,kind:'chart.time_range',value:{start:xs[Math.round(a)]??a,end:xs[Math.round(b)]??b}}});}
        });
        const resize=new ResizeObserver(()=>c.resize());resize.observe(el.current);
        return()=>{resize.disconnect();c.dispose();chart.current=undefined;};
    },[node.node_id]);
    useEffect(()=>{chart.current?.setOption({xAxis:{data:points.map(p=>p[0])},series:[{data:points.map(p=>p[1])}]});},[JSON.stringify(points)]);
    return <section className="chart"><header><strong>{node.props.title??'圖表'}</strong><span>{stream?.stale?'資料已過期':'合成示範資料'}</span></header><div ref={el} style={{height:320}}/></section>;
}
function CanvasScene({node}:{node:Node}){
    const width=node.props.width??640,height=node.props.height??480;
    return <section className="canvas-scene" aria-label={node.props.title??'互動畫布'}><svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={node.props.title??'互動畫布'}>
        <rect x={0} y={0} width={width} height={height} fill={node.props.background_color??'#111827'}/>
        {node.children?.map(element=>{
            const p=element.props,x=p.x??0,y=p.y??0,w=p.width??1,h=p.height??1,color=p.color??'#94A3B8',label=p.label??element.node_id;
            const select=(event:React.SyntheticEvent)=>{event.stopPropagation();emit('selection_changed',element.node_id,{selection:{node_id:element.node_id,kind:'node'}});};
            let shape:React.ReactNode;
            switch(element.type){
                case 'canvas.rect':shape=<rect x={x} y={y} width={w} height={h} fill={color}/>;break;
                case 'canvas.ellipse':shape=<ellipse cx={x+w/2} cy={y+h/2} rx={w/2} ry={h/2} fill={color}/>;break;
                case 'canvas.triangle':shape=<polygon points={`${x+w/2},${y} ${x+w},${y+h} ${x},${y+h}`} fill={color}/>;break;
                case 'canvas.text':shape=<text x={x} y={y+h/2} fill={color} dominantBaseline="middle">{label}</text>;break;
                default:return null;
            }
            return <g key={element.node_id} role="button" tabIndex={0} aria-label={label} data-node-id={element.node_id} onPointerDown={select} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(event);}}}><title>{label}</title>{element.type==='canvas.text'?<><rect x={x} y={y} width={w} height={h} fill="transparent"/>{shape}</>:<>{shape}<text x={x+6} y={y+18} fill="#111827" pointerEvents="none">{label}</text></>}</g>;
        })}
    </svg></section>;
}
function Component({node,snapshot}:{node:Node;snapshot:Snapshot}){
    const focus=()=>node.type==='chart.line'?emit('focus_changed',node.node_id):emit('selection_changed',node.node_id,{selection:{node_id:node.node_id,kind:'node'}});
    let content:React.ReactNode;
    switch(node.type){
        case 'stack':content=<div className="stack">{node.children?.map(n=><Component key={n.node_id} node={n} snapshot={snapshot}/>)}</div>;break;
        case 'text':content=<p>{node.props.text??node.props.title}</p>;break;
        case 'button':content=<button onClick={()=>emit('action',node.node_id,{action_id:node.props.action_id})}>{node.props.label??'執行'}</button>;break;
        case 'table':content=<div className="table"><table><thead><tr>{node.props.columns?.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{node.props.rows?.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{String(v??'')}</td>)}</tr>)}</tbody></table></div>;break;
        case 'chart.line':content=<Chart node={node} snapshot={snapshot}/>;break;
        case 'canvas':content=<CanvasScene node={node}/>;break;
        case 'canvas.rect':case 'canvas.ellipse':case 'canvas.triangle':case 'canvas.text':content=<span>{node.props.label}</span>;break;
    }
    return <div data-node-id={node.node_id} tabIndex={0} onFocus={e=>{if(e.target===e.currentTarget)focus();}} onPointerDown={e=>{e.stopPropagation();focus();}}>{content}</div>;
}
function App(){const [state,setState]=useState<Snapshot>();const [error,setError]=useState(false);
    useEffect(()=>{let active=true;const poll=async()=>{try{const next=await readSnapshot();if(active&&next)setState(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);}catch{if(active)setError(true);}};void poll();const timer=setInterval(()=>void poll(),150);return()=>{active=false;clearInterval(timer);};},[]);
    if(error)return <main role="alert">無法載入已驗證的工作表面。</main>;
    return state?<main><Component key={state.document_revision} node={state.document.root} snapshot={state}/></main>:<main className="empty">等待 Maltose Host…</main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
