import tempfile
import unittest
from fastapi.testclient import TestClient
from app.library import save
from test_app import Store,create_app


class LibraryTests(unittest.TestCase):
    def test_prompt_format_survives_restart_and_invalid_update_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            text="  Review the evidence.\n\n- Cite sources\n- List gaps\n"
            ident=save(store,{"title":"Review","body":text})["id"]
            store.db.close();store=Store(directory)
            self.assertEqual(store.rows("SELECT body FROM library_items WHERE id=?",(ident,))[0]["body"],text)
            with self.assertRaises(ValueError):save(store,{"title":"x","body":"x"*6001},ident)
            with self.assertRaises(ValueError):save(store,{"title":"x","body":"hello"},"missing")
            store.db.close()

    def test_personal_prompt_crud_isolated_from_owner_and_other_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"]
                headers={"X-CSRF-Token":csrf}
                owner=client.post("/api/library",headers=headers,json={"title":"Owner note","body":"owner-only-prompt"}).json()["id"]
                grant=client.post("/api/access/grants",headers=headers,json={"name":"Viewer","role":"viewer"}).json()
                login=client.post("/api/access/login",json={"role":"viewer","code":grant["code"]}).json()
                headers={"X-CSRF-Token":login["csrf"]}
                self.assertEqual(client.get("/api/library").json()["items"],[])
                self.assertEqual(client.patch("/api/library/"+owner,headers=headers,json={"title":"Other","body":"overwrite"}).status_code,400)
                own=client.post("/api/library",headers=headers,json={"title":"Favourite","body":"personal-prompt"}).json()["id"]
                self.assertEqual(len(client.get("/api/library").json()["items"]),1)
                self.assertEqual(client.delete("/api/library/"+own,headers=headers).status_code,200)
                self.assertEqual(store.rows("SELECT body FROM library_items")[0]["body"],"owner-only-prompt")
            store.db.close()
