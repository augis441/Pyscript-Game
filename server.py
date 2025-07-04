from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.responses import JSONResponse

app = FastAPI()

DEBUG = False  # Set to True for verbose logging

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

connections = {}  # nickname -> websocket
players_data = {}  # nickname -> player info dict

empty_msg_count = 0
MAX_EMPTY_MSGS = 5

@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def well_known_probe(request: Request):
    return {"status": "ok"}

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down. Closing all websocket connections.")
    for ws in list(connections.values()):
        await ws.close()
    connections.clear()
    players_data.clear()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    nickname = None
    empty_msg_count = 0

    try:
        while True:
            try:
                data = await websocket.receive_json()
                debug_print(f"Received raw data: {data}")
                if not isinstance(data, dict) or not data:
                    empty_msg_count += 1
                    debug_print(f"Ignoring empty or non-dict JSON message ({empty_msg_count}/{MAX_EMPTY_MSGS}): {data}")
                    if empty_msg_count >= MAX_EMPTY_MSGS:
                        print(f"Too many empty/invalid messages from {nickname or websocket.client}, disconnecting.")
                        await websocket.close()
                        break
                    continue
                else:
                    empty_msg_count = 0
            except ValueError as e:
                empty_msg_count += 1
                debug_print(f"Invalid JSON message ({empty_msg_count}/{MAX_EMPTY_MSGS}): {e}")
                if empty_msg_count >= MAX_EMPTY_MSGS:
                    print(f"Too many malformed JSON messages from {nickname or websocket.client}, disconnecting.")
                    await websocket.close()
                    break
                continue
            except Exception as e:
                print(f"Unexpected error receiving JSON: {e}")
                break

            msg_type = data.get("type")
            if not msg_type:
                debug_print(f"Missing 'type' in message: {data}")
                continue

            if msg_type == "ping":
                continue
            elif msg_type == "join":
                nickname = data.get("nickname")
                if nickname:
                    connections[nickname] = websocket
                    players_data[nickname] = {
                        "x": data.get("x", 100),
                        "y": data.get("y", 100),
                        "state": data.get("state", "idle"),
                        "direction": data.get("direction", "down"),
                        "current_frame": data.get("current_frame", 0),
                        "current_time": data.get("current_time", 0),
                        "is_invulnerable": data.get("is_invulnerable", False),
                        "afterimages": data.get("afterimages", [])
                    }
                    debug_print(f"{nickname} joined.")
                else:
                    debug_print("Join message missing 'nickname'")
            elif msg_type == "update" or msg_type == "action":
                if nickname:
                    x = data.get("x")
                    y = data.get("y")
                    if x is not None and y is not None:
                        players_data[nickname] = {
                            "x": x,
                            "y": y,
                            "state": data.get("state", "idle"),
                            "direction": data.get("direction", "down"),
                            "current_frame": data.get("current_frame", 0),
                            "current_time": data.get("current_time", 0),
                            "is_invulnerable": data.get("is_invulnerable", False),
                            "afterimages": data.get("afterimages", [])
                        }
                    else:
                        debug_print(f"Update/action message missing position data: {data}")

                    players_list = [{"nickname": nick, **info} for nick, info in players_data.items()]
                    for conn in list(connections.values()):
                        try:
                            await conn.send_json({"type": "players_update", "players": players_list})
                        except Exception as e:
                            debug_print(f"Failed to send update to a client: {e}")
                else:
                    debug_print("Received 'update' or 'action' message before 'join'")
            else:
                debug_print(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        print(f"{nickname or websocket.client} disconnected.")
    finally:
        if nickname:
            connections.pop(nickname, None)
            players_data.pop(nickname, None)
            players_list = [{"nickname": nick, **info} for nick, info in players_data.items()]
            for conn in list(connections.values()):
                try:
                    await conn.send_json({"type": "players_update", "players": players_list})
                except Exception as e:
                    debug_print(f"Failed to send update to a client: {e}")

@app.get("/")
async def root():
    index_path = Path("frontend/index.html")
    return FileResponse(index_path)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")