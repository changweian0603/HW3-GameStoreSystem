import asyncio
import json
import argparse
import sys
CHOICES = ["rock", "paper", "scissors"]

def decide(a: str, b: str) -> int:
    if a == b: return 0
    wins = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
    return 1 if (a, b) in wins else -1

async def handle_game_session(reader, writer, expected_token):
    peer = writer.get_extra_info('peername')
    print(f"[RPS Server] Connection from {peer}")
    
    # 1. Auth Handshake (HW3 specific)
    try:
        # Expect token message first
        line = await reader.readline()
        if not line:
            return
        
        try:
            msg = json.loads(line.decode())
            if msg.get("type") != "AUTH" or msg.get("token") != expected_token:
                print(f"[RPS Server] Auth fail. Expected {expected_token}, got {msg.get('token')}")
                writer.write((json.dumps({"type": "AUTH", "status": "FAIL"}) + "\n").encode())
                await writer.drain()
                return
        except:
             return

        writer.write((json.dumps({"type": "AUTH", "status": "OK"}) + "\n").encode())
        await writer.drain()
        print(f"[RPS Server] Client authenticated.")
        
    except Exception as e:
        print(f"[RPS Server] Auth error: {e}")
        return
    pass

clients = [] 

async def acceptor(reader, writer, token):
    global clients
    try:
        line = await reader.readline()
        if not line: return
        msg = json.loads(line.decode())
        if msg.get("type") != "AUTH" or msg.get("token") != token:
            writer.write((json.dumps({"type": "AUTH", "status": "FAIL"}) + "\n").encode())
            await writer.drain()
            writer.close()
            return
            
        writer.write((json.dumps({"type": "AUTH", "status": "OK"}) + "\n").encode())
        await writer.drain()
        
        clients.append({"r": reader, "w": writer, "ipv": writer.get_extra_info('peername')})
        print(f"[RPS] Accepted client {len(clients)}/2")
        
        if len(clients) >= 2:
            # Start Game
            await run_game_loop()
            
    except Exception as e:
        print(f"[RPS] Accept error: {e}")

async def run_game_loop():
    p1 = clients[0]
    p2 = clients[1]
    
    print("[RPS] Starting Game!")
    
    await send_json(p1["w"], {"type": "GAME_START", "opponent": "Player 2"})
    await send_json(p2["w"], {"type": "GAME_START", "opponent": "Player 1"})
    
    score = [0, 0] 
    
    try:
        while True:
            await send_json(p1["w"], {"type": "REQUEST_MOVE"})
            await send_json(p2["w"], {"type": "REQUEST_MOVE"})
            
            moves = await asyncio.gather(
                read_move(p1["r"]),
                read_move(p2["r"])
            )
            
            m1, m2 = moves
            if not m1 or not m2 or m1=='q' or m2=='q':
                break
                
            res = decide(m1, m2)
            if res == 1: score[0] += 1
            elif res == -1: score[1] += 1
            
            round_res = {
                "type": "ROUND_RESULT",
                "p1_move": m1, "p2_move": m2,
                "score": score
            }
            await send_json(p1["w"], round_res)
            await send_json(p2["w"], round_res)
            
    except Exception as e:
        print(f"Game error: {e}")
    finally:
        await broadcast({"type": "GAME_END", "final_score": score})
        sys.exit(0)

async def read_move(reader):
    try:
        line = await reader.readline()
        if not line: return None
        msg = json.loads(line.decode())
        return msg.get("move")
    except: return None

async def send_json(writer, data):
    writer.write((json.dumps(data) + "\n").encode())
    await writer.drain()

async def broadcast(data):
    for c in clients:
        try: await send_json(c["w"], data)
        except: pass

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    
    server = await asyncio.start_server(
        lambda r, w: acceptor(r, w, args.token),
        "0.0.0.0", args.port
    )
    print(f"[RPS Server] Listening on {args.port}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
