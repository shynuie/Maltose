"""Invoked by Swift TransportTests with ephemeral credentials; never prints secrets."""
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packages/sdk-python'))
from maltose import Client,MUPException
async def main():
    url='ws://127.0.0.1:'+os.environ['MALTOSE_TEST_PORT']
    async with Client(os.environ['MALTOSE_TEST_A'],url) as a, Client(os.environ['MALTOSE_TEST_B'],url) as b:
        own=await a.context();assert own['surfaces'][0]['selection']['node_id']=='chart'
        other=await b.context();assert len(other['surfaces'])==1;assert 'selection' not in other['surfaces'][0];assert other['focused_node_id'] is None
        try:await b.request('surface.get',{'surface_id':'market'})
        except MUPException as error:assert error.code=='forbidden'
        else:raise AssertionError('ACL bypass')
        result=await a.request('ui.patch',{'surface_id':'market','expected_revision':1,'operations':[{'op':'set_props','node_id':'chart','props':{'title':'SDK update'}}]})
        assert result['revision']==2
        try:await a.request('ui.patch',{'surface_id':'market','expected_revision':1,'operations':[{'op':'set_props','node_id':'chart','props':{'title':'stale'}}]})
        except MUPException as error:assert error.code=='revision_conflict'
        else:raise AssertionError('Stale patch accepted')
        await a.subscribe_context()
        after=await a.reconnect();assert after['surfaces'][0]['document_revision']==2
        for kind in ['surface.detach','surface.attach']:await a.request(kind,{'surface_id':'market'})
        await a.request('data.register',{'data_id':'prices'})
        await a.request('data.publish',{'data_id':'prices','sequence':0,'points':[[1,10],[2,20]]})
        try:await b.request('data.publish',{'data_id':'prices','sequence':1,'points':[[1,999]]})
        except MUPException as error:assert error.code=='forbidden'
        else:raise AssertionError('Data ownership bypass')
    print('Python SDK/native interoperability passed')
asyncio.run(main())
