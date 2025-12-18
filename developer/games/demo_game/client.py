import sys
import argparse
import asyncio

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args, unknown = parser.parse_known_args()

    print(f"[DemoClient] Connecting to {args.host}:{args.port} with token {args.token}")
    
    try:
        reader, writer = await asyncio.open_connection(args.host, args.port)
        
        writer.write(f"{args.token}\n".encode())
        await writer.drain()
        
        print("[DemoClient] Connected! Type something to echo (or 'quit'):")
        
        async def recv_loop():
            while True:
                data = await reader.read(1024)
                if not data: break
                print(f"\n[Server] {data.decode().strip()}")
        
        asyncio.create_task(recv_loop())
        
        while True:
            msg = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            msg = msg.strip()
            if not msg: continue
            if msg == "quit": break
            
            writer.write(f"{msg}\n".encode())
            await writer.drain()
            
    except Exception as e:
        print(f"[DemoClient] Error: {e}")
    finally:
        print("Bye")

if __name__ == "__main__":
    asyncio.run(main())
