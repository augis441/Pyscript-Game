from js import window, WebSocket, JSON
from pyodide.ffi import create_proxy
import json
import asyncio

class MultiplayerClient:
    def __init__(self, player, nickname):
        self.player = player
        self.nickname = nickname
        self.ws = None
        self.other_players = {}
        self.connected = False

        # Create proxies for event handlers
        self.on_open_proxy = create_proxy(lambda e: self._handle_open(e))
        self.on_message_proxy = create_proxy(self.on_message)
        self.on_error_proxy = create_proxy(self.on_error)
        self.on_close_proxy = create_proxy(self.on_close)

    async def connect(self):
        self.ws = WebSocket.new(f"ws://{window.location.host}/ws")
        self.ws.addEventListener("open", self.on_open_proxy)
        self.ws.addEventListener("message", self.on_message_proxy)
        self.ws.addEventListener("error", self.on_error_proxy)
        self.ws.addEventListener("close", self.on_close_proxy)

        # Await connection
        self._open_promise = asyncio.Future()
        await self._open_promise
        self.connected = True

    def _handle_open(self, event):
        print("WebSocket connected")
        self.send({"type": "join", "nickname": self.nickname})
        if not self._open_promise.done():
            self._open_promise.set_result(True)


    def on_message(self, event):
        try:
            data = json.loads(event.data)
            print(f"Received message: {data}")  # Debug log
            if data.get("type") == "players_update":
                self.other_players = {
                    p["nickname"]: {"x": p["x"], "y": p["y"]}
                    for p in data["players"]
                    if p["nickname"] != self.nickname
                }
        except Exception as e:
            print(f"Error processing message: {e}")

    def on_close(self, event):
        print("WebSocket closed")
        self.connected = False
        if not self._open_promise.done():
            self._open_promise.set_exception(RuntimeError("WebSocket closed"))
        self._cleanup()

    def on_error(self, event):
        print(f"WebSocket error: {event}")
        self.connected = False
        if not self._open_promise.done():
            self._open_promise.set_exception(RuntimeError("WebSocket error"))

    def send(self, data):
        if self.ws and self.ws.readyState == 1:
            if not isinstance(data, dict) or not data:
                print(f"Prevented sending invalid data: {data}")
                return
            try:
                message = JSON.stringify(data)
                if message == "{}":
                    print(f"Warning: JSON.stringify produced empty object for data: {data}")
                    return
                print(f"Sending message: {message}")
                self.ws.send(message)
            except Exception as e:
                print(f"Error sending message: {e}")
        else:
            print("WebSocket not open. Could not send:", data)


    def send_position_update(self):
        self.send({
            "type": "update",
            "x": self.player.x,
            "y": self.player.y
        })

    def get_other_players(self):
        return self.other_players

    async def keep_alive(self):
        while self.connected:
            await asyncio.sleep(20)
            self.send({"type": "ping"})

    def _cleanup(self):
        if self.ws:
            self.ws.removeEventListener("open", self.on_open_proxy)
            self.ws.removeEventListener("message", self.on_message_proxy)
            self.ws.removeEventListener("error", self.on_error_proxy)
            self.ws.removeEventListener("close", self.on_close_proxy)
        self.on_open_proxy.destroy()
        self.on_message_proxy.destroy()
        self.on_error_proxy.destroy()
        self.on_close_proxy.destroy()