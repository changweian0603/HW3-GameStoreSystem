import argparse, asyncio, json, struct, sys, random, os

_MAX = 65536

def _pack(obj):
    body = json.dumps(obj).encode('utf-8')
    return struct.pack('!I', len(body)) + body

async def sendf(writer, obj):
    try:
        writer.write(_pack(obj))
        await writer.drain()
    except: pass

async def recvf(reader):
    raw = await reader.readexactly(4)
    n = struct.unpack('!I', raw)[0]
    data = await reader.readexactly(n)
    return json.loads(data.decode('utf-8'))

class ClickerServer:
    def __init__(self, port, token, room_id):
        self.port = port
        self.token = token
        self.room_id = room_id
        self.players = {}
        self.running = False
        
    async def broadcast(self, msg):
        dead = []
        for w in list(self.players.keys()):
            try: await sendf(w, msg)
            except: dead.append(w)
        for w in dead: 
            if w in self.players: del self.players[w]

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        try:
            line = await reader.readline()
            if not line: return
            auth = json.loads(line.decode())
            if auth.get("type") != "AUTH" or auth.get("token") != self.token:
                writer.close()
                return
            
            writer.write((json.dumps({"type": "AUTH", "status": "OK"}) + "\n").encode())
            await writer.drain()

            pid = f"P{len(self.players)+1}"
            self.players[writer] = {"name": pid, "score": 0}
            print(f"[{pid}] Connected from {addr}")
            
            await sendf(writer, {"type": "WELCOME", "my_id": pid})

            await self.broadcast_scores()

            while True:
                msg = await recvf(reader)
                t = msg.get("type")
                if t == "CLICK":
                    self.players[writer]["score"] += 1
                    await self.broadcast_scores()
                    
                    if self.players[writer]["score"] >= 50:
                        await self.broadcast({"type": "WINNER", "winner": self.players[writer]["name"]})
                        for p in self.players.values(): p["score"] = 0
                        await self.broadcast_scores()

        except Exception as e:
            print(f"Error {e}")
        finally:
            if writer in self.players: 
                del self.players[writer]
                await self.broadcast_scores()
            
            if len(self.players) == 0:
                print("Last player left, closing server.")
                os._exit(0)

    async def broadcast_scores(self):
        scores = {p["name"]: p["score"] for p in self.players.values()}
        await self.broadcast({"type": "UPDATE", "scores": scores})

    async def serve(self):
        server = await asyncio.start_server(self.handle_client, "0.0.0.0", self.port)
        print(f"Clicker Server on {self.port}")
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    s = ClickerServer(args.port, args.token, args.room_id)
    try: asyncio.run(s.serve())
    except KeyboardInterrupt: pass
