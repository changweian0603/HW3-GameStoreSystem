import asyncio
import json
import os
import sys
import shutil
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.protocol import sendf, recvf
from shared.consts import DEV_PORT, DB_PORT, DEFAULT_DB_HOST, STORAGE_DIR

async def db_call(payload):
    try:
        reader, writer = await asyncio.open_connection(DEFAULT_DB_HOST, DB_PORT)
        await sendf(writer, payload)
        resp = await recvf(reader)
        writer.close()
        await writer.wait_closed()
        return resp
    except Exception as e:
        print(f"[DevServer] DB Error: {e}")
        return {"ok": False, "reason": "DB_ERROR"}

async def handle_client(reader, writer):
    user = None
    addr = writer.get_extra_info('peername')
    print(f"[DevServer] Connection from {addr}")
    
    try:
        while True:
            req = await recvf(reader)
            if not req: break
            
            cmd = req.get("type")
            resp = {"type": cmd, "status": "FAIL", "reason": "UNKNOWN"}

            if cmd == "LOGIN":
                u = req.get("user")
                p = req.get("password")
                res = await db_call({"collection": "Users_Dev", "action": "auth", "data": {"user": u, "password": p}})
                if res.get("ok"):
                    user = u
                    resp = {"type": cmd, "status": "OK", "user": user}
                else:
                    resp = {"type": cmd, "status": "FAIL", "reason": res.get("reason")}

            elif cmd == "REGISTER":
                u = req.get("user")
                p = req.get("password")
                res = await db_call({"collection": "Users_Dev", "action": "register", "data": {"user": u, "password": p}})
                resp = {"type": cmd, "status": "OK"} if res.get("ok") else {"type": cmd, "status": "FAIL", "reason": res.get("reason")}

            elif cmd == "UPLOAD_INIT":
                if not user:
                    resp = {"type": cmd, "status": "FAIL", "reason": "NOT_LOGIN"}
                else:
                    meta = req.get("metadata", {})
                    game_id = req.get("game_id") or meta.get("name", "unknown").replace(" ", "_").lower()
                    version = req.get("version")
                    file_size = req.get("file_size")
                    
                    svr_path = Path(__file__).parent / STORAGE_DIR / game_id / version
                    svr_path.mkdir(parents=True, exist_ok=True)
                    target_file = svr_path / f"game_{version}.zip"
                    
                    await sendf(writer, {"type": cmd, "status": "READY_TO_RECV", "game_id": game_id})
                    
                    read_bytes = 0
                    with open(target_file, "wb") as f:
                        while read_bytes < file_size:
                            chunk_size = min(64*1024, file_size - read_bytes)
                            chunk = await reader.readexactly(chunk_size)
                            f.write(chunk)
                            read_bytes += len(chunk)
                    
                    import zipfile
                    try:
                        with zipfile.ZipFile(target_file, 'r') as zip_ref:
                            zip_ref.extractall(svr_path)
                            
                        db_payload = {
                            "collection": "Games",
                            "action": "upload",
                            "data": {
                                "game_id": game_id,
                                "metadata": {
                                    "author": user,
                                    "name": meta.get("name"),
                                    "description": meta.get("description"),
                                    "type": meta.get("type"),
                                    "min_players": meta.get("min_players"),
                                    "max_players": meta.get("max_players"),
                                },
                                "version_info": {
                                    "version": version,
                                    "file_path": str(target_file),
                                    "uploaded_at": 0 # TODO ts
                                }
                            }
                        }
                        await db_call(db_payload)
                        
                        resp = {"type": "UPLOAD_COMPLETE", "status": "OK"}
                        
                    except Exception as e:
                        print(f"Unzip error: {e}")
                        resp = {"type": "UPLOAD_COMPLETE", "status": "FAIL", "reason": "BAD_ZIP"}
            
            elif cmd == "LIST_MY_GAMES":
                glist = await db_call({"collection": "Games", "action": "list", "data": {"include_inactive": True}})
                my_games = []
                if glist.get("ok"):
                    for g in glist.get("games", []):
                        if g.get("author") == user:
                            my_games.append(g)
                resp = {"type": cmd, "status": "OK", "games": my_games}
                
            elif cmd == "OFFSHELF":
                gid = req.get("game_id")
                # TODO: verify ownership
                await db_call({"collection": "Games", "action": "set_active", "data": {"game_id": gid, "is_active": False}})
                resp = {"type": cmd, "status": "OK"}
            
            elif cmd == "LIST_REVIEWS":
                gid = req.get("game_id")
                res = await db_call({"collection": "Reviews", "action": "list", "data": {"game_id": gid}})
                resp = {"type": cmd, "status": "OK", "reviews": res.get("reviews", [])}

            await sendf(writer, resp)
            
    except Exception as e:
        print(f"[DevServer] Error: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", DEV_PORT)
    print(f"[DevServer] Listening on 0.0.0.0:{DEV_PORT}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
