import asyncio
import tempfile
import unittest
from app.analysis_styles import select,instruction,catalog
from app.library import save
from test_app import Store,fixture_config,FakeAI
from app.agent import run_turn


class StyleTests(unittest.TestCase):
    def test_auto_manual_and_custom_style_selection_is_bounded_and_account_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            self.assertIsNone(select(store,"What is your name?"))
            self.assertEqual(select(store,"Review this PR")["id"],"review")
            self.assertEqual(select(store,"Debug the failure")["id"],"debug")
            self.assertIsNone(select(store,"Debug the failure","plain"))
            ident=save(store,{"title":"My review","body":"Use my exact evidence table.","kind":"template"})["id"]
            self.assertEqual(select(store,"Question",ident)["body"],"Use my exact evidence table.")
            self.assertTrue(any(item["id"]==ident for item in catalog(store)))
            with self.assertRaises(ValueError):select(store,"Question","foreign-template")
            self.assertNotIn("body",catalog(store)[0])
            store.db.close()

    def test_actual_model_instructions_receive_style_without_exposing_connection_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.save_config(fixture_config())
            template=save(store,{"title":"Private style","body":"Use a concise table. github-private-token","kind":"skill"})["id"]
            config=store.config()
            self.assertNotIn("github-private-token",instruction(store,"review",template,config))
            seen=[]
            class Client(FakeAI):
                def stream(self,**kwargs):
                    seen.append(kwargs["system"])
                    return super().stream(**kwargs)
            # Use the tested identity-independent model path with no requested tools.
            class Answer(Client):
                def __init__(self,cfg):super().__init__(cfg);self.stage=2
            cid=store.new_conversation()
            async def run():
                return [event async for event in run_turn(store,cid,"Review this change",client_factory=Answer,
                    services_factory=lambda cfg:None,model_mode="standard",template_mode=template)]
            asyncio.run(run())
            self.assertIn("concise table",seen[0])
            self.assertIn("never overrides access",seen[0])
            store.db.close()
