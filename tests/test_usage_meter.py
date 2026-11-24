import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from app.store import Store
from app.usage import report, save_rate, save_budget, monthly, reconcile
from app.usage_meter import MeteredClient, Call, responses


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.cfg = {"ai": {"provider": "bedrock"}}
        save_rate(self.store, {"model":"fixture","input":2,"output":10,"cache_read":1,"cache_write":3})

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_connection_test_cache_tokens_and_incomplete_cost_are_separate(self):
        class Client:
            def __init__(self): self.messages = self
            async def create(self, **args):
                return SimpleNamespace(model="fixture", usage=SimpleNamespace(
                    input_tokens=100,output_tokens=10,cache_read_input_tokens=50,cache_creation_input_tokens=20))
        asyncio.run(MeteredClient(Client(),self.store,self.cfg,"Connection test").create(model="fixture"))
        with Call(self.store,self.cfg,"fixture","Chat"):
            pass
        data=report(self.store)
        self.assertEqual(data["totals"]["requests"],1)
        self.assertAlmostEqual(data["totals"]["estimated_usd"],.00041)
        self.assertEqual(data["calls"][0]["status"],"incomplete")
        self.assertEqual(data["calls"][1]["origin"],"Connection test")
        self.assertNotIn("prompt", str(self.store.rows("SELECT * FROM usage_calls")))

    def test_budget_blocks_new_request_and_invoice_replaces_model_month(self):
        with Call(self.store,self.cfg,"fixture","Chat") as call:
            call.complete({"model":"fixture","usage":{"input_tokens":1000000,"output_tokens":0}})
        save_budget(self.store,{"monthly_usd":1,"mode":"stop"})
        with self.assertRaisesRegex(ValueError,"budget reached"):
            with Call(self.store,self.cfg,"fixture","Chat"): pass
        self.assertEqual(len(self.store.rows("SELECT * FROM usage_calls")),1)
        save_budget(self.store,{"monthly_usd":1,"mode":"warn"})
        with Call(self.store,self.cfg,"fixture","Chat"): pass
        current=monthly(self.store)["month"]
        reconcile(self.store,{"month":current,"model":"fixture","amount":3})
        reconcile(self.store,{"month":current,"model":"fixture","amount":4})
        data=monthly(self.store)
        self.assertEqual(len(data["invoices"]),1)
        self.assertEqual(data["invoices"][0]["difference_usd"],2)
        for body in ({"monthly_usd":float("nan"),"mode":"stop"},{"monthly_usd":1,"mode":"other"}):
            with self.assertRaises(ValueError): save_budget(self.store,body)
        with self.assertRaises(ValueError): reconcile(self.store,{"month":"2026-13","model":"x","amount":1})

    def test_chatgpt_missing_usage_and_failure_are_visible(self):
        async def source(*args, **kwargs):
            yield {"type":"response.completed","response":{"model":"fixture","usage":{
                "input_tokens":100,"output_tokens":10,"input_tokens_details":{"cached_tokens":40}}}}
        async def run():
            return [e async for e in responses(self.store,{"ai":{"provider":"chatgpt"}},"Chat",source,None,{"model":"fixture"})]
        asyncio.run(run())
        with self.assertRaises(RuntimeError):
            with Call(self.store,self.cfg,"fixture","Chat"): raise RuntimeError("synthetic failure")
        data=report(self.store)
        self.assertEqual(data["totals"]["cache_read_input_tokens"],40)
        self.assertEqual(data["totals"]["input_tokens"],60)
        self.assertEqual(data["totals"]["unpriced_requests"],1)
        self.assertTrue(any(r["status"]=="failed / usage unavailable" for r in data["calls"]))
