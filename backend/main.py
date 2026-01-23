from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
from typing import List, Dict, Set

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, str] = {}
        self.usernames: Dict[WebSocket, str] = {}
        self.message_history: Dict[str, List[Dict]] = {}
        self.room_users: Dict[str, Set[str]] = {}

    async def connect(self, websocket: WebSocket, username: str, room: str):
        self.active_connections[websocket] = room
        self.usernames[websocket] = username
        if room not in self.room_users:
            self.room_users[room] = set()
        self.room_users[room].add(username)
        await self.broadcast_system(room, f"{username} joined the {room} chat")

    def disconnect(self, websocket: WebSocket):
        room = self.active_connections.get(websocket)
        username = self.usernames.get(websocket, "Someone")
        self.active_connections.pop(websocket, None)
        self.usernames.pop(websocket, None)
        if room and username in self.room_users.get(room, set()):
            self.room_users[room].remove(username)
            if not self.room_users[room]:
                del self.room_users[room]
        return username, room

    async def broadcast_room(self, room: str, data: Dict, exclude_sender: WebSocket = None):
        if room not in self.message_history:
            self.message_history[room] = []
        self.message_history[room].append(data)
        if len(self.message_history[room]) > 50:
            self.message_history[room].pop(0)
        
        for ws, user_room in self.active_connections.items():
            if user_room == room and ws != exclude_sender:
                await ws.send_json(data)

    async def broadcast_system(self, room: str, message: str):
        await self.broadcast_room(room, {"type": "system", "message": message})

    async def send_user_list(self, room: str):
        users = list(self.room_users.get(room, set()))
        await self.broadcast_room(room, {"type": "user_list", "users": users})

manager = ConnectionManager()

@app.get("/")
async def root():
    return {"message": "Websocket Chatterbox is running"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        join_data = await websocket.receive_json()
        username = join_data.get("username", "Anonymous")
        room = join_data.get("room", "general")
        await manager.connect(websocket, username, room)

        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")

            if event_type == "chat":
                message = data.get("message", "").strip()
                if message:
                    await manager.broadcast_room(
                        room,
                        {"type": "chat", "username": username, "message": message},
                        websocket
                    )
            elif event_type == "typing":
                await manager.broadcast_room(
                    room,
                    {"type": "typing", "username": username},
                    websocket
                )
            elif event_type == "stop_typing":
                await manager.broadcast_room(
                    room,
                    {"type": "stop_typing", "username": username},
                    websocket
                )
            elif event_type == "switch_room":
                old_room = room
                room = data.get("new_room", room)
                if old_room != room:
                    username = manager.usernames.get(websocket)
                    if username in manager.room_users.get(old_room, set()):
                        manager.room_users[old_room].remove(username)
                    manager.active_connections[websocket] = room
                    if room not in manager.room_users:
                        manager.room_users[room] = set()
                    manager.room_users[room].add(username)
                    await manager.broadcast_system(old_room, f"{username} left the {old_room} chat")
                    await manager.send_user_list(old_room)
                    await manager.broadcast_system(room, f"{username} joined the {room} chat")
                    await manager.send_user_list(room)

    except WebSocketDisconnect:
        username, room = manager.disconnect(websocket)
        if room:
            await manager.broadcast_system(room, f"{username} left the {room} chat")
            await manager.send_user_list(room)

if __name__ == "__main__":
    uvicorn.run("app:app", host="localhost", port=8000, reload=True)