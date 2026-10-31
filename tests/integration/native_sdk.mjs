import {Client} from '../../packages/sdk-typescript/dist/index.js';
const client=await new Client(process.env.MALTOSE_TEST_A,'ws://127.0.0.1:'+process.env.MALTOSE_TEST_PORT).connect();
try {
 const snapshot=await client.context();
 if(snapshot.surfaces.length!==1)throw new Error('Missing native surface');
 await client.subscribeContext();
 const restored=await client.reconnect();
 if(restored.surfaces[0].surface_id!=='market')throw new Error('Resync failed');
 console.log('TypeScript SDK/native interoperability passed');
} finally {client.close();}
