import unittest
from app.github_guidance import guidance
import test_repository_settings as fixture


class GuidanceTests(unittest.TestCase):
    def test_missing_scope_has_review_option_but_configured_404_is_not_auto_added(self):
        cfg={"github":{"repos":["team/repo"]}}
        args={"service":"github","path":"/repos/team/new/pulls/1"}
        result=guidance(cfg,args,"Repository is outside your configured scope")
        self.assertEqual(result["action"],"validate_repository")
        args["path"]="/repos/team/repo/pulls/999"
        result=guidance(cfg,args,"github: HTTP 404; target not found or hidden")
        self.assertEqual(result["action"],"check_connection")
        self.assertIn("missing or hidden",result["message"])
        self.assertIsNone(guidance(cfg,args,"Request timed out"))
        self.assertEqual(guidance({**cfg,"_private":True},{"repo":"team/new"},"outside scope")["action"],"check_connection")


class GuidanceRouteTests(unittest.TestCase):
    setUp=fixture.RepositorySettingsTests.setUp
    def tearDown(self):
        self.client.app.state.workspaces.close()
        fixture.RepositorySettingsTests.tearDown(self)
    def test_direct_review_route_validates_read_access_and_does_not_save_until_confirmed(self):
        response=self.client.post(f"/api/conversations/{self.cid}/repository-proposal",
            headers=self.headers,json={"repo":"team/new"})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["status"],"pending")
        self.assertNotIn("team/new",self.store.config()["github"]["repos"])
        self.assertTrue(all(request.method=="GET" for request in self.requests))
        self.assertNotIn("github-private-token",response.text)
        self.client.post(f"/api/actions/{response.json()['id']}/confirm",headers=self.headers)
        self.assertIn("team/new",self.store.config()["github"]["repos"])
        self.denied=True
        failed=self.client.post(f"/api/conversations/{self.cid}/repository-proposal",
            headers=self.headers,json={"repo":"team/hidden"})
        self.assertEqual(failed.status_code,400)
        self.assertNotIn("PRIVATE UPSTREAM BODY",failed.text)
        self.assertNotIn("team/hidden",self.store.config()["github"]["repos"])

    def test_viewer_cannot_create_repository_proposal(self):
        grant=self.client.post("/api/access/grants",headers=self.headers,json={"name":"Viewer","role":"viewer"}).json()
        login=self.client.post("/api/access/login",json={"role":"viewer","code":grant["code"]}).json()
        response=self.client.post(f"/api/conversations/{self.cid}/repository-proposal",
            headers={"X-CSRF-Token":login["csrf"]},json={"repo":"team/new"})
        self.assertEqual(response.status_code,403)
