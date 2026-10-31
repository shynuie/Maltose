"""Two independent synthetic agents. Credentials come from the user's Keychain registration UI."""
import asyncio
import getpass
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packages/sdk-python'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_host import endpoint
from maltose import Client,MUPException
async def main():
    investment_token=getpass.getpass('agent.investment 憑證：')
    maltose_token=getpass.getpass('agent.maltose 憑證：')
    url=endpoint()
    async with Client(investment_token,url) as investment, Client(maltose_token,url) as maltose:
        surface_id='market-demo'
        document={'root':{'node_id':'market-root','type':'stack','props':{},'children':[
            {'node_id':'intro','type':'text','props':{'text':'合成市場資料 · 拖曳縮放，使用右上框選工具選擇區間。'}},
            {'node_id':'chart-synthetic','type':'chart.line','props':{'title':'Synthetic market monitor','data_id':'prices'}},
            {'node_id':'summary','type':'table','props':{'columns':['來源','用途'],'rows':[['合成序列','Awareness 示範'],['本機資料','無交易功能']]}},
            {'node_id':'refresh','type':'button','props':{'label':'請代理重新整理','action_id':'refresh'}}]},'actions':['refresh']}
        try:await investment.request('surface.create',{'surface_id':surface_id,'title':'Market Monitor','document':document})
        except MUPException as e:
            if e.code!='unavailable':raise
        try:await investment.request('data.register',{'data_id':'prices'})
        except MUPException as e:
            if e.code!='unavailable':raise
        await investment.subscribe_context(surface_id=surface_id)
        print('已連線。請在 Host 中縮放／選取、獨立視窗，並授權 agent.maltose 摘要後撤銷。')
        for sequence in range(120):
            points=[[f'2026-10-{i+1:02}',round(100+math.sin(i/3+sequence/20)*8+i/2,2)] for i in range(28)]
            try:await investment.request('data.publish',{'data_id':'prices','sequence':sequence+int(asyncio.get_running_loop().time()*1000),'points':points})
            except MUPException as e:
                if e.code!='duplicate_event':raise
            if sequence%5==0:
                own=await investment.context(surface_id=surface_id)
                selected=own['surfaces'][0].get('selection')
                reference=await investment.request('ui.context.resolve_reference',{'phrase':'this chart'})
                shared=await maltose.context()
                print('Investment selection:',selected,'Reference candidates:',len(reference['candidates']),'Maltose authorized summaries:',[(s['surface_id'],s['title']) for s in shared['surfaces']])
            await asyncio.sleep(1)
if __name__=='__main__':
    try:asyncio.run(main())
    except KeyboardInterrupt:pass
