import asyncio,getpass,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packages/sdk-python'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_host import endpoint
from maltose import Client
async def main():
    async with Client(getpass.getpass('代理憑證：'),endpoint()) as client:
        print(await client.request('surface.create',{'surface_id':'hello','title':'Hello Maltose','document':{'root':{'node_id':'hello-text','type':'text','props':{'text':'繁體中文 · 本機互動表面'}}}}))
asyncio.run(main())
