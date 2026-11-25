import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.store import Store
from test_app import create_app


class FavoritesTests(unittest.TestCase):
    def test_pin_reopen_preserves_usage_format_and_excludes_tool_results(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);cid=store.new_conversation("Review")
            store.save_turn(cid,[{"role":"user","content":"**My question**"},
                                 {"role":"assistant","content":[{"type":"text","text":"```json\n{\"ok\": true}\n```"},{"type":"tool_use","name":"api_read","input":{}}]},
                                 {"role":"user","content":[{"type":"tool_result","content":"HIDDEN TOOL BODY"}]}],{"model":"fixture","usage":{"input_tokens":17}})
            turn=store.rows("SELECT id FROM turns")[0]["id"]
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"];headers={"X-CSRF-Token":csrf}
                path=f"/api/conversations/{cid}/favorites/{turn}/assistant"
                self.assertEqual(client.post(path,headers=headers,json={"pinned":True}).status_code,200)
                favorite=client.get("/api/favorites").json()["entries"][0]
                self.assertEqual(favorite["text"],'```json\n{"ok": true}\n```')
                self.assertNotIn("HIDDEN TOOL BODY",json.dumps(client.get("/api/favorites").json()))
                metadata=json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
                self.assertEqual(metadata["usage"]["input_tokens"],17)
                self.assertEqual(client.post(path.replace(cid,"wrong-chat"),headers=headers,json={"pinned":True}).status_code,400)
                self.assertEqual(client.post(path,headers=headers,json={"pinned":"yes"}).status_code,400)
            store.db.close();store=Store(directory)
            self.assertEqual(json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])["favorite_roles"],["assistant"])
            with patch.dict("os.environ",{"AIMATE_MESSAGE_FAVORITES_ENABLED":"0"}):
                with TestClient(create_app(store)) as disabled:
                    self.assertEqual(disabled.get("/api/favorites").status_code,404)
            self.assertEqual(json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])["favorite_roles"],["assistant"])
            store.db.close()

    def test_paging_and_unpin_remove_reference_without_changing_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);cid=store.new_conversation()
            for i in range(51):
                store.save_turn(cid,[{"role":"user","content":str(i)}],{"favorite_roles":["user"]})
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"];headers={"X-CSRF-Token":csrf}
                first=client.get("/api/favorites").json();self.assertEqual(len(first["entries"]),50)
                second=client.get("/api/favorites",params={"before_turn":first["next_before_turn"]}).json()
                self.assertEqual(len(second["entries"]),1);self.assertIsNone(second["next_before_turn"])
                turn=second["entries"][0]["turn"]
                client.post(f"/api/conversations/{cid}/favorites/{turn}/user",headers=headers,json={"pinned":False})
                self.assertEqual(len(client.get("/api/favorites").json()["entries"]),50)
                self.assertEqual(len(store.rows("SELECT id FROM turns")),51)
            store.db.close()
