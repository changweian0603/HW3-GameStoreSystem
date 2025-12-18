import asyncio
import json
import os
import sys
import random
import uuid
import subprocess
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.protocol import sendf, recvf
from shared.consts import LOBBY_PORT, DB_PORT, DEFAULT_DB_HOST, STORAGE_DIR

# --- Globals ---
ONLINE_PLAYERS = {} # { username: {writer, status} }
ROOMS = {}          # { room_id: {id, game_id, game_version, min_players, status, host, port, token, players: [], proc} }
INVITES = {}        # { username: [invites...] }

# --- DB Helpers ---
async def db_call(payload):
    try:
        reader, writer = await asyncio.open_connection(DEFAULT_DB_HOST, DB_PORT)
        await sendf(writer, payload)
        resp = await recvf(reader)
        writer.close()
        await writer.wait_closed()
        return resp
    except Exception as e:
        print(f"[Lobby] DB Error: {e}")
        return {"ok": False, "reason": "DB_ERROR"}

async def db_auth_player(user, pwd):
    return await db_call({"collection": "Users_Player", "action": "auth", "data": {"user": user, "password": pwd}})

async def db_reg_player(user, pwd):
    return await db_call({"collection": "Users_Player", "action": "register", "data": {"user": user, "password": pwd}})

async def db_list_games():
    return await db_call({"collection": "Games", "action": "list"})

async def db_get_game(gid):
    return await db_call({"collection": "Games", "action": "get", "data": {"game_id": gid}})

async def db_submit_review(user, gid, rating, comments):
    return await db_call({
        "collection": "Reviews", 
        "action": "submit", 
        "data": {"user": user, "game_id": gid, "rating": rating, "comment": comments}
    })

async def db_record_play(user, gid):
    return await db_call({"collection": "Users_Player", "action": "record_play", "data": {"user": user, "game_id": gid}})

async def db_list_reviews(gid):
    return await db_call({"collection": "Reviews", "action": "list", "data": {"game_id": gid}})

# --- Game Process Managment ---

def get_free_port():
    while True:
        port = random.randint(20000, 30000)
        return port

def load_game_config(game_id, version):
    base = Path(__file__).parent / STORAGE_DIR / game_id / version
    cfg_path = base / "game_config.json"
    if not cfg_path.exists():
        return None, base
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return cfg, base
    except:
        return None, base

async def start_game_server(room_id, game_id, version, token):
    try:
        cfg, base_path = load_game_config(game_id, version)
        if not cfg:
            print(f"[Lobby] Config not found for {game_id} {version}")
            return None, None

        port = get_free_port()
        cmd_template = cfg.get("server_cmd", [])
        if not cmd_template:
            print(f"[Lobby] No server_cmd for {game_id}")
            return None, None
            
        cmd = list(cmd_template)
        cmd.extend(["--port", str(port), "--token", token, "--room-id", str(room_id)])
        
        print(f"[Lobby] Launching game {game_id}: {cmd}")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(base_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return proc, port
        
    except Exception as e:
        print(f"[Lobby] Failed to start game server: {e}")
        return None, None

async def monitor_game_process(room_id, proc):
    try:
        await proc.wait()
        print(f"[Lobby] Game {room_id} process finished.")
    except Exception as e:
        print(f"[Lobby] Monitor error for {room_id}: {e}")
    finally:
        if room_id in ROOMS:
            room = ROOMS[room_id]
            print(f"[Lobby] Closing room {room_id} and resetting players.")
            
            for p in room["players"]:
                if p in ONLINE_PLAYERS:
                    ONLINE_PLAYERS[p]["status"] = "Idle"
            
            del ROOMS[room_id]


async def handle_client(reader, writer):
    user = None
    addr = writer.get_extra_info('peername')
    print(f"[Lobby] New connection from {addr}")
    
    try:
        while True:
            req = await recvf(reader)
            if not req: break
            
            cmd = req.get("type")
            resp = {"type": cmd, "status": "FAIL", "reason": "UNKNOWN_CMD"}
            
            # --- AUTH ---
            if cmd == "LOGIN":
                u = req.get("user")
                p = req.get("password")
                
                if u in ONLINE_PLAYERS:
                    resp = {"type": cmd, "status": "FAIL", "reason": "ALREADY_LOGGED_IN"}
                else:
                    auth = await db_auth_player(u, p)
                    if auth.get("ok"):
                        user = u
                        ONLINE_PLAYERS[user] = {"writer": writer, "status": "Idle"}
                        resp = {"type": cmd, "status": "OK", "user": user}
                    else:
                        resp = {"type": cmd, "status": "FAIL", "reason": auth.get("reason", "AUTH_FAIL")}
            
            elif cmd == "REGISTER":
                u = req.get("user")
                p = req.get("password")
                reg = await db_reg_player(u, p)
                resp = {"type": cmd, "status": "OK"} if reg.get("ok") else {"type": cmd, "status": "FAIL", "reason": reg.get("reason")}

            # --- STORE ---
            elif cmd == "LIST_GAMES":
                g = await db_list_games()
                if g.get("ok"):
                    resp = {"type": cmd, "status": "OK", "games": g.get("games", [])}
                else:
                    resp = {"type": cmd, "status": "FAIL"}

            elif cmd == "DOWNLOAD_GAME":
                gid = req.get("game_id")
                ginfo = await db_get_game(gid)
                if not ginfo.get("ok"):
                    resp = {"type": cmd, "status": "FAIL", "reason": "GAME_NOT_FOUND"}
                else:
                    game = ginfo["game"]
                    latest = game.get("latest_version")
                    ver_entry = next((v for v in game.get("versions", []) if v["version"] == latest), None)
                    if not ver_entry:
                        resp = {"type": cmd, "status": "FAIL", "reason": "VERSION_NOT_FOUND"}
                    else:
                        fpath = ver_entry.get("file_path")
                        if not os.path.exists(fpath):
                            resp = {"type": cmd, "status": "FAIL", "reason": "FILE_MISSING"}
                        else:
                            fsize = os.path.getsize(fpath)
                            await sendf(writer, {"type": cmd, "status": "OK", "size": fsize, "version": latest, "filename": f"{gid}_{latest}.zip"})
                            with open(fpath, "rb") as f:
                                while True:
                                    chunk = f.read(64*1024)
                                    if not chunk: break
                                    writer.write(chunk)
                                    await writer.drain()
                            continue 


            # --- REVIEWS ---
            elif cmd == "SUBMIT_REVIEW":
                gid = req.get("game_id")
                rating = req.get("rating")
                comment = req.get("comment")
                res = await db_submit_review(user, gid, rating, comment)
                resp = {"type": cmd, "status": "OK"} if res.get("ok") else {"type": cmd, "status": "FAIL", "reason": res.get("reason", "ERROR")}
            
            elif cmd == "LIST_REVIEWS":
                gid = req.get("game_id")
                res = await db_list_reviews(gid)
                resp = {"type": cmd, "status": "OK", "reviews": res.get("reviews", [])}

            # --- LOBBY / ROOMS ---
            elif cmd == "LIST_ONLINE":
                users_list = [{"name": u, "status": d["status"]} for u, d in ONLINE_PLAYERS.items()]
                rooms_list = [
                    {"id": r, "game_id": d["game_id"], "host": d["host"], "players": len(d["players"]), "status": d["status"]} 
                    for r, d in ROOMS.items()
                ]
                resp = {"type": cmd, "status": "OK", "users": users_list, "rooms": rooms_list}

            elif cmd == "CREATE_ROOM":
                gid = req.get("game_id")
                host_ver = req.get("game_version")
                
                ginfo = await db_get_game(gid)
                if not ginfo.get("ok"):
                    resp = {"type": cmd, "status": "FAIL", "reason": "GAME_NOT_FOUND"}
                else:
                    game = ginfo["game"]
                    latest = game.get("latest_version")
                    if host_ver != latest:
                        resp = {"type": cmd, "status": "FAIL", "reason": f"VERSION_MISMATCH needed: {latest}"}
                    else:
                        rid = str(uuid.uuid4())[:8]
                        token = str(uuid.uuid4())
                        proc, port = await start_game_server(rid, gid, latest, token)
                        
                        if not proc:
                             resp = {"type": cmd, "status": "FAIL", "reason": "LAUNCH_FAIL"}
                        else:
                            ONLINE_PLAYERS[user]["status"] = f"In Room {rid}"
                            ROOMS[rid] = {
                                "id": rid,
                                "game_id": gid,
                                "game_version": latest,
                                "min_players": game.get("min_players", 1),
                                "max_players": game.get("max_players", 2),
                                "status": "WAITING",
                                "host": user,
                                "port": port,
                                "token": token,
                                "players": [user],
                                "proc": proc
                            }
                            await db_record_play(user, gid)
                            resp = {
                                "type": cmd, "status": "OK", 
                                "room_id": rid, "port": port, "token": token, 
                                "min_players": game.get("min_players", 1),
                                "host": "127.0.0.1"
                            }
            
            elif cmd == "JOIN_ROOM":
                rid = req.get("room_id")
                client_ver = req.get("game_version")
                
                if rid not in ROOMS:
                    resp = {"type": cmd, "status": "FAIL", "reason": "ROOM_NOT_FOUND"}
                else:
                    room = ROOMS[rid]
                    if client_ver != room["game_version"]:
                         resp = {"type": cmd, "status": "FAIL", "reason": f"VERSION_MISMATCH room: {room['game_version']}"}
                    elif len(room["players"]) >= room.get("max_players", 2): 
                         resp = {"type": cmd, "status": "FAIL", "reason": "ROOM_FULL"}
                    elif room["status"] != "WAITING":
                         resp = {"type": cmd, "status": "FAIL", "reason": "GAME_ALREADY_STARTED"}
                    else:
                         ROOMS[rid]["players"].append(user)
                         ONLINE_PLAYERS[user]["status"] = f"In Room {rid}"
                         await db_record_play(user, room["game_id"])
                         resp = {
                                "type": cmd, "status": "OK", 
                                "room_id": rid, "port": room["port"], "token": room["token"], 
                                "host": "127.0.0.1"
                        }

            elif cmd == "ROOM_STATUS":
                rid = req.get("room_id")
                if rid in ROOMS:
                    room = ROOMS[rid]
                    resp = {
                        "type": cmd, "status": "OK", 
                        "room_status": room["status"], 
                        "players": room["players"],
                        "min_players": room["min_players"]
                    }
                else:
                    resp = {"type": cmd, "status": "FAIL", "reason": "ROOM_NOT_FOUND"}

            elif cmd == "START_GAME":
                rid = req.get("room_id")
                if rid in ROOMS:
                    room = ROOMS[rid]
                    if room["host"] != user:
                        resp = {"type": cmd, "status": "FAIL", "reason": "NOT_HOST"}
                    elif len(room["players"]) < room["min_players"]:
                        resp = {"type": cmd, "status": "FAIL", "reason": f"NEED_MORE_PLAYERS ({len(room['players'])}/{room['min_players']})"}
                    else:
                        room["status"] = "PLAYING"
                        for p in room["players"]:
                            if p in ONLINE_PLAYERS: ONLINE_PLAYERS[p]["status"] = "Playing"
                        
                        asyncio.create_task(monitor_game_process(rid, room["proc"]))
                        
                        resp = {"type": cmd, "status": "OK"}
                else:
                     resp = {"type": cmd, "status": "FAIL", "reason": "ROOM_NOT_FOUND"}
            
            elif cmd == "LEAVE_ROOM":
                rid = req.get("room_id")
                if rid in ROOMS:
                    room = ROOMS[rid]
                    if user in room["players"]:
                         room["players"].remove(user)
                         ONLINE_PLAYERS[user]["status"] = "Idle"
                         if room["host"] == user:
                             room["status"] = "CLOSED" 
                             del ROOMS[rid]
                             try: room["proc"].terminate()
                             except: pass
                    resp = {"type": cmd, "status": "OK"}
                else:
                    resp = {"type": cmd, "status": "OK"}

            await sendf(writer, resp)

    except Exception as e:
        print(f"[Lobby] Client Error: {e}")
    finally:
        if user:
            print(f"[Lobby] User {user} disconnected, cleaning up...")
            if user in ONLINE_PLAYERS:
                del ONLINE_PLAYERS[user]
            
            rooms_to_close = []
            for rid, r in ROOMS.items():
                if r["host"] == user:
                    rooms_to_close.append(rid)
                elif user in r["players"]:
                    if user in r["players"]: r["players"].remove(user)
            
            for rid in rooms_to_close:
                proc = ROOMS[rid].get("proc")
                if proc:
                    try:
                        proc.terminate()
                    except: pass
                del ROOMS[rid]

        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", LOBBY_PORT)
    print(f"[Lobby] Listening on 0.0.0.0:{LOBBY_PORT}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
