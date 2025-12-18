import asyncio
import json
import argparse
import sys

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    
    try:
        reader, writer = await asyncio.open_connection(args.host, args.port)
        
        # 1. Auth
        writer.write((json.dumps({"type": "AUTH", "token": args.token}) + "\n").encode())
        await writer.drain()
        
        line = await reader.readline()
        if not line: return
        resp = json.loads(line.decode())
        if resp.get("status") != "OK":
            print(f"Auth failed: {resp}")
            return
        
        print("Connected to RPS Server! Waiting for opponent...")
        
        # 2. Game Loop
        choices = ["rock", "paper", "scissors"]
        
        while True:
            line = await reader.readline()
            if not line: break
            
            msg = json.loads(line.decode())
            typ = msg.get("type")
            
            if typ == "GAME_START":
                print(f"\nGame Start! Opponent: {msg.get('opponent')}")
                
            elif typ == "REQUEST_MOVE":
                while True:
                    m = await asyncio.get_event_loop().run_in_executor(None, input, "Your move (rock/paper/scissors/q): ")
                    m = m.strip().lower()
                    if m == 'q':
                        writer.write((json.dumps({"move": "q"}) + "\n").encode())
                        await writer.drain()
                        return
                    if m in choices:
                        writer.write((json.dumps({"move": m}) + "\n").encode())
                        await writer.drain()
                        print("Waiting for opponent...")
                        break
                    print("Invalid move.")
            
            elif typ == "ROUND_RESULT":
                s = msg.get("score")
                print(f"Result: P1({msg.get('p1_move')}) vs P2({msg.get('p2_move')})")
                print(f"Score: You see {s}")
                
            elif typ == "GAME_END":
                print("Game Over!")
                print(f"Final Score: {msg.get('final_score')}")
                break
                
    except Exception as e:
        print(f"Client error: {e}")
    finally:
        try: writer.close(); await writer.wait_closed()
        except: pass

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
