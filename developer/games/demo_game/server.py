import sys
import argparse
import asyncio

ROOM_TOKEN = ""

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"[DemoServer] Connection from {addr}")
    
    try:
        line = await reader.readline()
        token = line.decode().strip()
        
        if token != ROOM_TOKEN:
            print(f"[DemoServer] Invalid Token: {token} vs {ROOM_TOKEN}")
            writer.write(b"INVALID TOKEN\n")
            writer.close()
            return
            
        print("[DemoServer] Token Validated!")
        writer.write(b"WELCOME TO DEMO GAME!\n")
        await writer.drain()
        
        while True:
            data = await reader.read(1024)
            if not data: break
            
            msg = data.decode().strip()
            print(f"[DemoServer] Recv: {msg}")
            
            # Echo
            resp = f"Echo: {msg}\n"
            writer.write(resp.encode())
            await writer.drain()
            
    except Exception as e:
        print(f"[DemoServer] Error: {e}")
    finally:
        writer.close()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    
    global ROOM_TOKEN
    ROOM_TOKEN = args.token
    
    server = await asyncio.start_server(handle_client, "0.0.0.0", args.port)
    print(f"[DemoServer] Listening on {args.port} for Room {args.room_id}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
