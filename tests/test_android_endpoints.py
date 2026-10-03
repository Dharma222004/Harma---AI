"""
Tests for Harma Android Device API Endpoints in harma.api.server
"""
import unittest
from httpx import AsyncClient, ASGITransport
from harma.api.server import create_app

class TestAndroidEndpoints(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.app = create_app()

    async def test_android_device_registration_and_heartbeat(self):
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as client:
            # 1. Register Android device
            reg_payload = {
                "device_id": "test-pixel-999",
                "device_name": "Google Pixel 8 Pro",
                "platform": "android",
                "android_version": "14",
                "app_version": "1.0.0",
                "manufacturer": "Google",
                "model": "Pixel 8 Pro",
                "capabilities": ["voice", "microphone", "app_control", "flashlight", "whatsapp_send"],
                "permission_states": {"record_audio": True, "accessibility": True},
                "connection_state": "ONLINE"
            }
            res_reg = await client.post("/api/devices/register", json=reg_payload)
            self.assertEqual(res_reg.status_code, 200)
            self.assertEqual(res_reg.json()["status"], "registered")

            # 2. Heartbeat
            hb_payload = {
                "device_id": "test-pixel-999",
                "status": "ONLINE",
                "battery_level": 88,
                "is_charging": False,
                "active_app": "com.whatsapp"
            }
            res_hb = await client.post("/api/devices/heartbeat", json=hb_payload)
            self.assertEqual(res_hb.status_code, 200)
            self.assertEqual(res_hb.json()["status"], "acknowledged")

            # 3. List devices - ensure our Android device appears
            res_dev = await client.get("/api/devices")
            self.assertEqual(res_dev.status_code, 200)
            data = res_dev.json()
            self.assertEqual(data["devices"]["android"]["device_id"], "test-pixel-999")
            self.assertEqual(data["devices"]["android"]["device_name"], "Google Pixel 8 Pro")
            self.assertEqual(data["devices"]["android"]["status"].upper(), "ONLINE")
            self.assertEqual(len(data["registered_devices"]), 1)

            # 4. Report Action Result
            report_payload = {
                "device_id": "test-pixel-999",
                "task_id": "wa-task-1",
                "action": "WHATSAPP_SEND",
                "status": "ACTION_EXECUTED_VERIFIED",
                "message": "Message sent and verified in WhatsApp conversation.",
                "details": {"recipient": "Bhuvanesh", "message": "hi"}
            }
            res_act = await client.post("/api/devices/test-pixel-999/action-result", json=report_payload)
            self.assertEqual(res_act.status_code, 200)
            self.assertEqual(res_act.json()["status"], "acknowledged")

    async def test_android_auth_session(self):
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as client:
            # Login
            login_res = await client.post("/api/auth/login", json={"username": "admin", "api_token": "token-123"})
            self.assertEqual(login_res.status_code, 200)
            self.assertEqual(login_res.json()["status"], "success")

            # Check session
            sess_res = await client.get("/api/auth/session")
            self.assertEqual(sess_res.status_code, 200)
            self.assertTrue(sess_res.json()["authenticated"])
