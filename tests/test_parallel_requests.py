import asyncio
import tempfile
import unittest
from unittest.mock import patch
import httpx
from test_app import Store,create_app


class ParallelTests(unittest.IsolatedAsyncioTestCase):
    async def test_limit_releases_and_same_chat_remains_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            app=create_app(store)
            release=asyncio.Event()
            started=asyncio.Event()
            count=0
            async def answer(store,cid,question,**kwargs):
                nonlocal count
                count+=1
                if count==3: started.set()
                await release.wait()
                store.save_turn(cid,[{"role":"user","content":question},{"role":"assistant","content":"Reply "+question}])
                yield {"event":"done"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://testserver") as client:
                login=await client.post("/api/login",json={"password":store.password})
                headers={"X-CSRF-Token":login.json()["csrf"]}
                ids=[store.new_conversation() for _ in range(4)]
                async def ask(cid,text):
                    return await client.post("/api/chat",headers=headers,json={"conversation":cid,"question":text})
                with patch("app.main.run_turn",answer):
                    tasks=[asyncio.create_task(ask(cid,f"parallel-{i}")) for i,cid in enumerate(ids[:3])]
                    try:
                        await asyncio.wait_for(started.wait(),5)
                        self.assertEqual((await client.get("/api/maintenance")).status_code,409)
                        self.assertEqual((await ask(ids[0],"duplicate")).status_code,409)
                        self.assertEqual((await ask(ids[3],"overflow")).status_code,429)
                    finally:
                        release.set()
                        await asyncio.gather(*tasks)
                    self.assertEqual((await ask(ids[3],"after-release")).status_code,200)
                for i,cid in enumerate(ids[:3]):
                    self.assertIn(f"parallel-{i}",str(store.history(cid)))
                    self.assertNotIn("overflow",str(store.history(cid)))
            store.db.close()
