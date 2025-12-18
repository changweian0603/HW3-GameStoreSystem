import argparse, random, socket, time, signal, os, sys
import struct, json, asyncio

_MAX = 65536

def _pack(obj):
    if isinstance(obj, (dict, list)):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    elif isinstance(obj, str):
        body = obj.encode('utf-8')
    else:
        body = obj
    return struct.pack('!I', len(body)) + body

async def sendf(writer, obj):
    writer.write(_pack(obj))
    await writer.drain()

async def recvf(reader):
    raw = await reader.readexactly(4)
    n = struct.unpack('!I', raw)[0]
    data = await reader.readexactly(n)
    return json.loads(data.decode('utf-8'))

BOARD_W, BOARD_H = 10, 20
DROP_MS_DEFAULT = 600
TARGET_LINES = 20

I_SHAPE = [(-1,0),(0,0),(1,0),(2,0)]
O_SHAPE = [(0,0),(1,0),(0,1),(1,1)]
T_SHAPE = [(-1,0),(0,0),(1,0),(0,1)]
S_SHAPE = [(-1,1),(0,1),(0,0),(1,0)]
Z_SHAPE = [(-1,0),(0,0),(0,1),(1,1)]
J_SHAPE = [(-1,0),(-1,1),(0,0),(1,0)]
L_SHAPE = [(-1,0),(0,0),(1,0),(1,1)]
ALL_SHAPES = [I_SHAPE,O_SHAPE,T_SHAPE,S_SHAPE,Z_SHAPE,J_SHAPE,L_SHAPE]

def rotate_cw(shape): return [(y, -x) for (x,y) in shape]
def rotate_ccw(shape): return [(-y, x) for (x,y) in shape]

class Tetris:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.board = [[0]*BOARD_W for _ in range(BOARD_H)]
        self.score = 0
        self.lines = 0
        self.bag = []
        self.next_queue = []        
        self.dead = False
        self.spawn_piece()

    def _refill_bag(self):
        bag = ALL_SHAPES[:]               
        self.rng.shuffle(bag)
        self.bag.extend(bag)

    def next_piece(self):
        if not self.bag: self._refill_bag()
        return [tuple(p) for p in self.bag.pop(0)]

    def spawn_piece(self):
        while len(self.next_queue) < 3:
            self.next_queue.append(self.next_piece())
        self.px, self.py = (BOARD_W//2), 0
        self.shape = [tuple(p) for p in self.next_queue.pop(0)]
        if self.collide(self.px, self.py, self.shape):
            self.dead = True
        else:
            self.dead = False

    def rotate_right(self):
        if self.dead: return
        cand = rotate_cw(self.shape)
        if not self.collide(self.px, self.py, cand): self.shape = cand

    def rotate_left(self):
        if self.dead: return
        cand = rotate_ccw(self.shape)
        if not self.collide(self.px, self.py, cand): self.shape = cand

    def collide(self, x, y, shape):
        for dx, dy in shape:
            cx, cy = x+dx, y+dy
            if cx < 0 or cx >= BOARD_W or cy < 0 or cy >= BOARD_H: return True
            if self.board[cy][cx]: return True
        return False

    def lock(self):
        for dx, dy in self.shape:
            cx, cy = self.px+dx, self.py+dy
            if 0 <= cy < BOARD_H and 0 <= cx < BOARD_W:
                self.board[cy][cx] = 1
        
        new_rows = [row for row in self.board if not all(row)]
        cleared = BOARD_H - len(new_rows)
        while len(new_rows) < BOARD_H:
            new_rows.insert(0, [0]*BOARD_W)
        self.board = new_rows
        if cleared: self.lines += cleared

    def step_gravity(self):
        if self.dead: return
        ny = self.py + 1
        if self.collide(self.px, ny, self.shape):
            self.lock()
            self.spawn_piece()
        else:
            self.py = ny

    def move(self, dx):
        if self.dead: return
        nx = self.px + dx
        if not self.collide(nx, self.py, self.shape): self.px = nx

    def soft_drop(self):
        if self.dead: return
        ny = self.py + 1
        if not self.collide(self.px, ny, self.shape): self.py = ny
    
    def hard_drop(self):
        if self.dead: return
        while True:
            ny = self.py + 1
            if self.collide(self.px, ny, self.shape):
                self.lock()
                self.spawn_piece()
                break
            else:
                self.py = ny

    def to_rows(self):
        vis = [row[:] for row in self.board]
        if not self.dead:
            for dx, dy in self.shape:
                x, y = self.px+dx, self.py+dy
                if 0 <= x < BOARD_W and 0 <= y < BOARD_H:
                    vis[y][x] = 2
        
        rows = []
        for y in range(BOARD_H):
            s = ''.join('#' if vis[y][x]==1 else ('@' if vis[y][x]==2 else '.') for x in range(BOARD_W))
            rows.append(s)
        return rows

# --- Server Logic ---

class GameServer:
    def __init__(self, port, token, room_id):
        self.port = port
        self.token = token
        self.room_id = room_id
        
        self.drop_ms = DROP_MS_DEFAULT
        self.seed = int(time.time())
        self.players = {}
        self.role_order = ["P1", "P2"]
        self.state = {"P1": Tetris(self.seed), "P2": Tetris(self.seed)}
        self.server = None
        self.tick_task = None
        self.start_ts = None
        self.match_sec = 180
        self._ended = False

    async def _broadcast(self, obj):
        dead = []
        for w in list(self.players.keys()):
            try: await sendf(w, obj)
            except: dead.append(w)
        for w in dead: w.close()

    async def _end(self, reason):
        if self._ended: return
        self._ended = True
        results = {
            "P1": {"lines": self.state["P1"].lines},
            "P2": {"lines": self.state["P2"].lines},
            "reason": reason
        }
        await self._broadcast({"type":"BYE", "reason": reason, "results": results})
        if self.tick_task: self.tick_task.cancel()
        sys.exit(0)

    async def _tick_loop(self):
        try:
            while True:
                if self.start_ts and (time.time() - self.start_ts >= self.match_sec):
                    await self._end("Time Up")
                    return
                
                self.state["P1"].step_gravity()
                self.state["P2"].step_gravity()

                if self.state["P1"].dead or self.state["P2"].dead:
                    await self._end("Top Out")
                    return

                snap = {
                    "type": "SNAPSHOT",
                    "p1": {"board": self.state["P1"].to_rows(), "lines": self.state["P1"].lines},
                    "p2": {"board": self.state["P2"].to_rows(), "lines": self.state["P2"].lines}
                }
                await self._broadcast(snap)
                await asyncio.sleep(self.drop_ms / 1000.0)
        except asyncio.CancelledError:
            pass

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        try:
            # Auth
            line = await reader.readline()
            if not line: return
            msg = json.loads(line.decode())
            if msg.get("type") != "AUTH" or msg.get("token") != self.token:
                writer.write((json.dumps({"type": "AUTH", "status": "FAIL"}) + "\n").encode())
                await writer.drain()
                writer.close()
                return
            
            writer.write((json.dumps({"type": "AUTH", "status": "OK"}) + "\n").encode())
            await writer.drain()

            if len(self.players) >= 2:
                writer.close()
                return

            role = self.role_order[len(self.players)]
            self.players[writer] = {"role": role, "reader": reader}
            
            await sendf(writer, {
                "type": "WELCOME", "role": role, 
                "seed": self.seed, "boardW": BOARD_W, "boardH": BOARD_H
            })
            print(f"[{role}] connected from {addr}")

            if len(self.players) == 2 and not self.tick_task:
                self.start_ts = time.time()
                await self._broadcast({"type": "START", "matchSec": self.match_sec})
                self.tick_task = asyncio.create_task(self._tick_loop())

            # Recv Loop
            while True:
                msg = await recvf(reader)
                if msg.get("type") == "INPUT":
                    act = msg.get("action")
                    st = self.state[role]
                    if act == "L": st.move(-1)
                    elif act == "R": st.move(1)
                    elif act == "SD": st.soft_drop()
                    elif act == "HD": st.hard_drop()
                    elif act == "CW": st.rotate_right()
                    elif act == "CCW": st.rotate_left()
                    
                    snap = {
                        "type": "SNAPSHOT",
                        "p1": {"board": self.state["P1"].to_rows(), "lines": self.state["P1"].lines},
                        "p2": {"board": self.state["P2"].to_rows(), "lines": self.state["P2"].lines}
                    }
                    await self._broadcast(snap)

        except Exception as e:
            print(f"Client error: {e}")
            if not self._ended: await self._end("Peer Disconnected")

    async def serve(self):
        server = await asyncio.start_server(self.handle_client, "0.0.0.0", self.port)
        print(f"[Tetris] Listening on {self.port}")
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
    
    gs = GameServer(args.port, args.token, args.room_id)
    try:
        asyncio.run(gs.serve())
    except KeyboardInterrupt:
        pass
